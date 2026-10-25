"""SQLite persistence.

- `events` is append-only (enforced by triggers): the record of what happened.
- `state_versions` holds one state snapshot per processed event: what was believed after it.
- `transitions` logs what the model proposed and what the validator accepted or rejected.

State versions and transitions are derived data and can be rebuilt from the event log.
"""

import json
import sqlite3
from datetime import datetime

from .schema import empty_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT,
    ref TEXT,
    text TEXT NOT NULL,
    UNIQUE (project, id)
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TABLE IF NOT EXISTS state_versions (
    project TEXT NOT NULL,
    version INTEGER NOT NULL,
    event_id TEXT,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project, version)
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    kind TEXT NOT NULL,
    config_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    auto_accept INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_scan_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS import_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    project TEXT NOT NULL,
    external_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    event_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE (source_id, external_id)
);
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    title TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    origin TEXT NOT NULL DEFAULT 'user',
    confirmed INTEGER NOT NULL DEFAULT 1,
    source_claim TEXT,
    source_event TEXT,
    reminders_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    reason TEXT NOT NULL,
    ref_json TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    dismissed_at TEXT
);
CREATE TABLE IF NOT EXISTS assistant_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    model TEXT,
    review_json TEXT,
    error TEXT,
    latency_ms INTEGER
);
CREATE TABLE IF NOT EXISTS synth_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    event_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    format TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    parsed_json TEXT NOT NULL,
    excerpt TEXT,
    UNIQUE (project, sha256)
);
CREATE TABLE IF NOT EXISTS synth_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    baseline_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    comparison_json TEXT NOT NULL,
    constraints_json TEXT,
    checks_json TEXT,
    analysis_json TEXT,
    model TEXT,
    error TEXT,
    latency_ms INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    event_id TEXT NOT NULL,
    version_before INTEGER,
    version_after INTEGER,
    model TEXT,
    latency_ms INTEGER,
    proposed_json TEXT,
    applied_json TEXT,
    rejected_json TEXT,
    warnings_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
"""


def normalize_ts(value=None):
    """Return a naive local-time 'YYYY-MM-DDTHH:MM:SS' string. Inputs carrying a timezone (e.g. Git
    author dates) are converted to local time so they compare correctly with local timestamps."""
    if value is None or value == "":
        return datetime.now().replace(microsecond=0).isoformat()
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if len(text) == 10:
            text += "T00:00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()


def now_ts():
    return normalize_ts(None)


class Store:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
        if "name" not in cols:  # migration for databases created before display names existed
            self.conn.execute("ALTER TABLE projects ADD COLUMN name TEXT")
        if "priority" not in cols:  # migration: user-set importance (high / normal / low)
            self.conn.execute("ALTER TABLE projects ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
        if "sample" not in cols:  # migration: sample/synthetic projects are labelled in the UI
            self.conn.execute("ALTER TABLE projects ADD COLUMN sample INTEGER NOT NULL DEFAULT 0")
        rcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(assistant_reviews)")}
        if "kind" not in rcols:  # migration: reviews and catch-ups share the opinions table
            self.conn.execute("ALTER TABLE assistant_reviews ADD COLUMN kind TEXT NOT NULL DEFAULT 'review'")
        self.conn.commit()

    def close(self):
        self.conn.close()

    # projects -----------------------------------------------------------------------------
    def ensure_project(self, project):
        self.conn.execute(
            "INSERT OR IGNORE INTO projects (id, created_at) VALUES (?, ?)", (project, now_ts())
        )
        self.conn.commit()

    def set_project_name(self, project, name):
        self.ensure_project(project)
        with self.conn:
            self.conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project))

    def project_name(self, project):
        row = self.conn.execute("SELECT name FROM projects WHERE id = ?", (project,)).fetchone()
        return (row["name"] if row and row["name"] else project)

    def project_is_sample(self, project):
        row = self.conn.execute("SELECT sample FROM projects WHERE id = ?", (project,)).fetchone()
        return bool(row and row["sample"])

    def set_project_sample(self, project, sample=True):
        self.ensure_project(project)
        with self.conn:
            self.conn.execute("UPDATE projects SET sample = ? WHERE id = ?", (1 if sample else 0, project))

    def project_priority(self, project):
        row = self.conn.execute("SELECT priority FROM projects WHERE id = ?", (project,)).fetchone()
        return row["priority"] if row and row["priority"] else "normal"

    def set_project_priority(self, project, priority):
        if priority not in ("high", "normal", "low"):
            raise ValueError("priority must be high, normal or low")
        with self.conn:
            self.conn.execute("UPDATE projects SET priority = ? WHERE id = ?", (priority, project))

    # assistant reviews: Nemotron's opinion about a state version. Never claims, never evidence.
    # synthesis runs: structured index of imported Yosys reports. The report itself is evidence
    # (an append-only synthesis_report event); this row links to it by event_id and is never edited.
    def add_synth_run(self, project, event_id, filename, sha, fmt, parsed, excerpt):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO synth_runs (project, event_id, filename, sha256, format, imported_at, parsed_json, excerpt)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project, event_id, filename, sha, fmt, now_ts(), json.dumps(parsed), excerpt))
        return self.get_synth_run(cur.lastrowid)

    def _synth_row(self, row):
        if row is None:
            return None
        d = dict(row)
        d["parsed"] = json.loads(d.pop("parsed_json"))
        return d

    def get_synth_run(self, run_id):
        return self._synth_row(self.conn.execute("SELECT * FROM synth_runs WHERE id = ?", (run_id,)).fetchone())

    def synth_run_by_hash(self, project, sha):
        return self._synth_row(self.conn.execute(
            "SELECT * FROM synth_runs WHERE project = ? AND sha256 = ?", (project, sha)).fetchone())

    def synth_runs(self, project):
        return [self._synth_row(r) for r in self.conn.execute(
            "SELECT * FROM synth_runs WHERE project = ? ORDER BY id", (project,))]

    def add_synth_analysis(self, project, run_id, baseline_id, comparison, constraints, checks):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO synth_analyses (project, run_id, baseline_id, created_at, comparison_json, constraints_json,"
                " checks_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project, run_id, baseline_id, now_ts(), json.dumps(comparison), json.dumps(constraints), json.dumps(checks)))
        return self.get_synth_analysis(cur.lastrowid)

    def set_synth_explanation(self, analysis_id, analysis=None, model=None, error=None, latency_ms=None):
        with self.conn:
            self.conn.execute("UPDATE synth_analyses SET analysis_json = ?, model = ?, error = ?, latency_ms = ? WHERE id = ?",
                              (json.dumps(analysis) if analysis else None, model, error, latency_ms, analysis_id))
        return self.get_synth_analysis(analysis_id)

    def _analysis_row(self, row):
        if row is None:
            return None
        d = dict(row)
        for k in ("comparison", "constraints", "checks", "analysis"):
            raw = d.pop(f"{k}_json")
            d[k] = json.loads(raw) if raw else None
        return d

    def get_synth_analysis(self, analysis_id):
        return self._analysis_row(self.conn.execute("SELECT * FROM synth_analyses WHERE id = ?", (analysis_id,)).fetchone())

    def synth_analyses(self, project):
        return [self._analysis_row(r) for r in self.conn.execute(
            "SELECT * FROM synth_analyses WHERE project = ? ORDER BY id", (project,))]

    def add_review(self, project, version, trigger, model, review=None, error=None, latency_ms=None, kind="review"):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO assistant_reviews (project, version, created_at, trigger, model, review_json, error, latency_ms, kind)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project, version, now_ts(), trigger, model, json.dumps(review) if review else None, error, latency_ms, kind))
        return cur.lastrowid

    def latest_review(self, project, successful=True, kind="review"):
        q = ("SELECT * FROM assistant_reviews WHERE project = ? AND kind = ?" + (" AND error IS NULL" if successful else "")
             + " ORDER BY id DESC LIMIT 1")
        row = self.conn.execute(q, (project, kind)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["review"] = json.loads(d.pop("review_json")) if d.get("review_json") else None
        return d

    def projects(self):
        return [r["id"] for r in self.conn.execute("SELECT id FROM projects ORDER BY created_at")]

    # events -------------------------------------------------------------------------------
    def append_event(self, project, text, source="note", event_type=None, occurred_at=None, ref=None):
        self.ensure_project(project)
        text = (text or "").strip()
        if not text:
            raise ValueError("event text is empty")
        with self.conn:
            n = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE project = ?", (project,)
            ).fetchone()[0]
            event_id = f"E{n + 1}"
            self.conn.execute(
                "INSERT INTO events (project, id, occurred_at, recorded_at, source, event_type, ref, text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project, event_id, normalize_ts(occurred_at), now_ts(), source, event_type, ref, text),
            )
        return self.get_event(project, event_id)

    def get_event(self, project, event_id):
        row = self.conn.execute(
            "SELECT * FROM events WHERE project = ? AND id = ?", (project, event_id)
        ).fetchone()
        return dict(row) if row else None

    def events(self, project):
        rows = self.conn.execute("SELECT * FROM events WHERE project = ? ORDER BY seq", (project,))
        return [dict(r) for r in rows]

    def events_by_id(self, project):
        return {e["id"]: e for e in self.events(project)}

    # state --------------------------------------------------------------------------------
    def latest_state(self, project):
        row = self.conn.execute(
            "SELECT state_json FROM state_versions WHERE project = ? ORDER BY version DESC LIMIT 1",
            (project,),
        ).fetchone()
        return json.loads(row["state_json"]) if row else empty_state(project)

    def state_at(self, project, version):
        if version == 0:
            return empty_state(project)
        row = self.conn.execute(
            "SELECT state_json FROM state_versions WHERE project = ? AND version = ?",
            (project, version),
        ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def save_state(self, state):
        with self.conn:
            self._insert_state(state)

    def _insert_state(self, state):
        self.conn.execute(
            "INSERT INTO state_versions (project, version, event_id, state_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (state["project"], state["version"], state["last_event_id"], json.dumps(state), now_ts()),
        )

    def commit_transition(self, state, project, event_id, version_before, model, latency_ms,
                          proposed, applied, rejected, warnings):
        """New state + its transition record in ONE transaction: never half an update."""
        with self.conn:
            self._insert_state(state)
            self._insert_transition(project, event_id, version_before, state["version"], model, latency_ms,
                                    proposed, applied, rejected, warnings, None)

    # transitions ------------------------------------------------------------------------
    def save_transition(self, project, event_id, version_before, version_after, model, latency_ms,
                        proposed, applied, rejected, warnings, error=None):
        with self.conn:
            self._insert_transition(project, event_id, version_before, version_after, model, latency_ms,
                                    proposed, applied, rejected, warnings, error)

    def _insert_transition(self, project, event_id, version_before, version_after, model, latency_ms,
                           proposed, applied, rejected, warnings, error):
        self.conn.execute(
            "INSERT INTO transitions (project, event_id, version_before, version_after, model,"
            " latency_ms, proposed_json, applied_json, rejected_json, warnings_json, error, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project, event_id, version_before, version_after, model, latency_ms,
             json.dumps(proposed), json.dumps(applied), json.dumps(rejected),
             json.dumps(warnings), error, now_ts()),
        )

    def transitions(self, project):
        rows = self.conn.execute("SELECT * FROM transitions WHERE project = ? ORDER BY id", (project,))
        out = []
        for r in rows:
            t = dict(r)
            for k in ("proposed_json", "applied_json", "rejected_json", "warnings_json"):
                t[k[:-5]] = json.loads(t.pop(k) or "null")
            out.append(t)
        return out

    def unprocessed_events(self, project):
        rows = self.conn.execute(
            "SELECT e.* FROM events e WHERE e.project = ? AND NOT EXISTS ("
            " SELECT 1 FROM transitions t WHERE t.project = e.project AND t.event_id = e.id"
            " AND t.error IS NULL) ORDER BY e.seq",
            (project,),
        )
        return [dict(r) for r in rows]

    def pending_events(self, project):
        """Events without a successful transition, each with the error of its latest attempt (or None)."""
        last = {}
        for t in self.transitions(project):
            last[t["event_id"]] = t
        return [{**e, "last_error": (last.get(e["id"]) or {}).get("error")} for e in self.unprocessed_events(project)]

    def retryable_pending(self, project):
        """Pending events that sync may apply automatically: never-attempted ones and those that failed
        for transient reasons (offline, rate limit, server error, key fixed). Not: awaiting review,
        rejected by the user, or validator failures."""
        from .llm import retryable
        return [e for e in self.pending_events(project) if e["last_error"] is None or retryable(e["last_error"])]

    def clear_derived(self, project):
        """Drop state versions and transitions so they can be rebuilt from the event log."""
        with self.conn:
            self.conn.execute("DELETE FROM state_versions WHERE project = ?", (project,))
            self.conn.execute("DELETE FROM transitions WHERE project = ?", (project,))

    # sources & imports (staged evidence: nothing here affects the state until accepted) -------
    def add_source(self, project, kind, config, auto_accept=False):
        self.ensure_project(project)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sources (project, kind, config_json, auto_accept, created_at) VALUES (?, ?, ?, ?, ?)",
                (project, kind, json.dumps(config), int(bool(auto_accept)), now_ts()))
        return self.get_source(cur.lastrowid)

    def _source_row(self, row):
        if row is None:
            return None
        d = dict(row)
        d["config"] = json.loads(d.pop("config_json"))
        d["enabled"] = bool(d["enabled"])
        d["auto_accept"] = bool(d["auto_accept"])
        return d

    def get_source(self, source_id):
        return self._source_row(self.conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone())

    def sources(self, project=None):
        if project:
            rows = self.conn.execute("SELECT * FROM sources WHERE project = ? ORDER BY id", (project,))
        else:
            rows = self.conn.execute("SELECT * FROM sources ORDER BY id")
        return [self._source_row(r) for r in rows]

    def update_source(self, source_id, **fields):
        allowed = {"enabled", "auto_accept", "last_scan_at", "last_error"}
        sets = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items() if k in allowed}
        if sets:
            with self.conn:
                self.conn.execute(f"UPDATE sources SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                                  (*sets.values(), source_id))
        return self.get_source(source_id)

    def remove_source(self, source_id):
        """Remove a source and its not-yet-accepted items. Accepted items stay (their evidence is permanent)."""
        with self.conn:
            self.conn.execute("DELETE FROM import_items WHERE source_id = ? AND status IN ('pending', 'skipped')",
                              (source_id,))
            self.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def stage_item(self, source, item):
        """Insert a candidate import; returns False if this source already knows the item."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO import_items (source_id, project, external_id, occurred_at, title, payload_json,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source["id"], source["project"], item["external_id"], normalize_ts(item["occurred_at"]),
                 item["title"], json.dumps(item), now_ts()))
        return cur.rowcount == 1

    def known_external_ids(self, source_id):
        return {r[0] for r in self.conn.execute("SELECT external_id FROM import_items WHERE source_id = ?", (source_id,))}

    def _item_row(self, row):
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        return d

    def import_items(self, project, status=None):
        if status:
            rows = self.conn.execute("SELECT * FROM import_items WHERE project = ? AND status = ? ORDER BY occurred_at, id",
                                     (project, status))
        else:
            rows = self.conn.execute("SELECT * FROM import_items WHERE project = ? ORDER BY occurred_at, id", (project,))
        return [self._item_row(r) for r in rows]

    def get_item(self, item_id):
        return self._item_row(self.conn.execute("SELECT * FROM import_items WHERE id = ?", (item_id,)).fetchone())

    def set_item(self, item_id, status, event_id=None, error=None):
        with self.conn:
            self.conn.execute("UPDATE import_items SET status = ?, event_id = COALESCE(?, event_id), error = ?,"
                              " decided_at = ? WHERE id = ?", (status, event_id, error, now_ts(), item_id))

    # milestones (user commitments; not evidence-derived claims) --------------------------------
    def add_milestone(self, project, title, due_at=None, reminders=None, notes=None, origin="user",
                      confirmed=True, source_claim=None, source_event=None):
        self.ensure_project(project)
        ts = now_ts()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO milestones (project, title, due_at, origin, confirmed, source_claim, source_event,"
                " reminders_json, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project, title, normalize_ts(due_at) if due_at else None, origin, int(bool(confirmed)),
                 source_claim, source_event, json.dumps(reminders or []), notes, ts, ts))
        return self.get_milestone(cur.lastrowid)

    def _milestone_row(self, row):
        if row is None:
            return None
        d = dict(row)
        d["reminders"] = json.loads(d.pop("reminders_json") or "[]")
        d["confirmed"] = bool(d["confirmed"])
        return d

    def get_milestone(self, mid):
        return self._milestone_row(self.conn.execute("SELECT * FROM milestones WHERE id = ?", (mid,)).fetchone())

    def milestones(self, project=None):
        order = " ORDER BY due_at IS NULL, due_at, id"
        if project:
            rows = self.conn.execute("SELECT * FROM milestones WHERE project = ?" + order, (project,))
        else:
            rows = self.conn.execute("SELECT * FROM milestones" + order)
        return [self._milestone_row(r) for r in rows]

    def update_milestone(self, mid, **fields):
        allowed = {"title", "due_at", "status", "confirmed", "notes", "reminders", "closed_at"}
        sets = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "reminders":
                sets["reminders_json"] = json.dumps(v or [])
            elif k == "due_at":
                sets[k] = normalize_ts(v) if v else None
            elif k == "confirmed":
                sets[k] = int(bool(v))
            else:
                sets[k] = v
        sets["updated_at"] = now_ts()
        with self.conn:
            self.conn.execute(f"UPDATE milestones SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                              (*sets.values(), mid))
        return self.get_milestone(mid)

    def delete_milestone(self, mid):
        with self.conn:
            self.conn.execute("DELETE FROM milestones WHERE id = ?", (mid,))
            self.conn.execute("DELETE FROM notices WHERE dedupe_key LIKE ?", (f"milestone:{mid}:%",))

    # notices (deduplicated reminders and alerts) -------------------------------------------------
    def add_notice(self, project, kind, dedupe_key, title, reason, ref=None):
        """Insert once per dedupe_key; returns True if new."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO notices (project, kind, dedupe_key, title, reason, ref_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project, kind, dedupe_key, title, reason, json.dumps(ref or {}), now_ts()))
        return cur.rowcount == 1

    def notices(self, include_dismissed=False):
        q = "SELECT * FROM notices" + ("" if include_dismissed else " WHERE dismissed_at IS NULL") + " ORDER BY id DESC"
        out = []
        for r in self.conn.execute(q):
            d = dict(r)
            d["ref"] = json.loads(d.pop("ref_json") or "{}")
            out.append(d)
        return out

    def mark_notice(self, notice_id, delivered=False, dismissed=False):
        with self.conn:
            if delivered:
                self.conn.execute("UPDATE notices SET delivered_at = COALESCE(delivered_at, ?) WHERE id = ?",
                                  (now_ts(), notice_id))
            if dismissed:
                self.conn.execute("UPDATE notices SET dismissed_at = ? WHERE id = ?", (now_ts(), notice_id))

    # settings -----------------------------------------------------------------------------------
    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key, value):
        with self.conn:
            self.conn.execute("INSERT INTO settings (key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET"
                              " value_json = excluded.value_json", (key, json.dumps(value)))

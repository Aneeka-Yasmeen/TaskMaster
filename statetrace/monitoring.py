from datetime import datetime

from . import view as V
from .reminders import in_quiet_hours, milestones_with_status, prefs as reminder_prefs
from .store import now_ts
from .summary import change_labels, core_state, project_summary

DEFAULTS = {
    "monitoring": False,        # Background monitoring: Off by default
    "notifications": False,     # Windows notifications: Off by default
    "paused": False,            # "Pause all monitoring" without losing the other choices
    "interval_minutes": 15,     # how often the companion scans enabled sources
    "hotkey_enabled": True,
    "hotkey": "ctrl+alt+t",  # read by the companion at start; change here or with --hotkey
    "enabled_at": None,         # when monitoring was last switched on
    "enabled_after_notice": None,  # notices with an id <= this predate opting in and are never pushed
}
ALIVE_SECONDS = 90


def companion_prefs(store):
    p = dict(DEFAULTS)
    p.update(store.get_setting("companion", {}) or {})
    return p


def set_companion_prefs(store, update):
    p = companion_prefs(store)
    for k in ("monitoring", "notifications", "paused", "hotkey_enabled"):
        if k in update:
            if not isinstance(update[k], bool):
                raise ValueError(f"{k} must be true or false")
            p[k] = update[k]
    if "hotkey" in update:
        from .winapi import parse_hotkey
        parse_hotkey(update["hotkey"])  # raises ValueError with a readable reason
        p["hotkey"] = str(update["hotkey"]).strip().lower()
    if "interval_minutes" in update:
        minutes = int(update["interval_minutes"])
        if not 5 <= minutes <= 1440:
            raise ValueError("interval_minutes must be between 5 and 1440")
        p["interval_minutes"] = minutes
    if update.get("monitoring") is True and not companion_prefs(store)["monitoring"]:
        # never flood the user with notices that predate opting in; ids are exact where
        # second-resolution timestamps are not
        p["enabled_at"] = now_ts()
        p["enabled_after_notice"] = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM notices").fetchone()[0]
    store.set_setting("companion", p)
    return p


def active(p):
    """Background work happens only when monitoring is on and not paused."""
    return bool(p["monitoring"] and not p["paused"])


def record_status(store, status):
    allowed = {"pid", "hotkey", "hotkey_label", "hotkey_error", "backend", "started_at", "last_scan_at", "last_error", "version"}
    s = {k: v for k, v in (status or {}).items() if k in allowed}
    s["seen_at"] = now_ts()
    store.set_setting("companion_status", s)
    return s


def companion_status(store, now=None):
    now = now or datetime.now().replace(microsecond=0)
    s = store.get_setting("companion_status", {}) or {}
    seen = s.get("seen_at")
    alive = bool(seen) and (now - datetime.fromisoformat(seen)).total_seconds() <= ALIVE_SECONDS
    p = companion_prefs(store)
    return {**s, "alive": alive, "monitoring_active": alive and active(p)}


def notification_text(notice, project_name):
    """Short, non-sensitive text: no commit messages, blocker text or evidence content."""
    kind = notice["kind"]
    if kind in ("milestone_due", "milestone_overdue"):
        return "TaskMaster deadline", f"{project_name}: {notice['title']}"[:180]
    if kind == "stale":
        return "TaskMaster", f"{project_name} has had no new evidence for a while. Review its state."
    if kind == "imports":
        return "TaskMaster", f"{notice['title']} in {project_name}. Review before it affects the state."
    if kind == "test":
        return "TaskMaster", "Windows notifications are working."
    return "TaskMaster", notice["title"][:120]


def deliverable(store, now=None):
    """Notices the companion may push now. Respects the existing reminder rules: notifications
    only when opted in and monitoring is active, never during quiet hours, never twice, never
    for notices created before monitoring was enabled (test notices excepted)."""
    now = now or datetime.now().replace(microsecond=0)
    p = companion_prefs(store)
    rp = reminder_prefs(store)
    if not (p["notifications"] and active(p)):
        return {"notices": [], "reason": "notifications off" if not p["notifications"] else "monitoring off or paused"}
    pending = [n for n in store.notices() if not n.get("delivered_at")]
    if p.get("enabled_after_notice") is not None:
        pending = [n for n in pending if n["kind"] == "test" or n["id"] > p["enabled_after_notice"]]
    elif p["enabled_at"]:
        pending = [n for n in pending if n["kind"] == "test" or n["created_at"] > p["enabled_at"]]
    if in_quiet_hours(rp, now) or not rp["enabled"]:
        pending = [n for n in pending if n["kind"] == "test"]
        reason = "quiet hours" if rp["enabled"] else "reminders disabled"
    else:
        reason = None
    names = {pid: store.project_name(pid) for pid in {n["project"] for n in pending}}
    out = []
    for n in pending:
        title, body = notification_text(n, names.get(n["project"], n["project"]))
        target = {"imports": f"/p/{n['project']}/inbox"}.get(n["kind"], f"/p/{n['project']}")
        out.append({"id": n["id"], "kind": n["kind"], "title": title, "body": body, "path": target})
    return {"notices": out, "reason": reason}


def companion_brief(store, project, now=None):
    """Compact, evidence-backed view of one project for the popup. Missing state stays missing."""
    now_iso = (now or datetime.now().replace(microsecond=0)).isoformat()
    s = project_summary(store, project, now_iso)
    state = store.latest_state(project)
    view = V.build_view(state)
    one = lambda f: (view["fields"][f][0] if view["fields"][f] else None)  # noqa: E731

    def claim(c):
        if not c:
            return None
        return {"id": c["id"], "value": c["value"], "verification": c["verification"],
                "contested": bool(c.get("contested")), "evidence": c["evidence"], "as_of": c["as_of"],
                "stale": s["stale"]}

    blocker, nxt = claim(one("current_blocker")), claim(one("next_step"))
    ms = milestones_with_status(store, project, datetime.fromisoformat(now_iso))
    if nxt:
        m = next((x for x in ms if x["source_claim"] == nxt["id"] and x["status"] == "open"), None)
        nxt["commitment"] = "committed" if m else "proposed"
        nxt["due_at"] = m["due_at"] if m else None
    upcoming = next((x for x in ms if x["status"] == "open" and x["confirmed"] and x["due_at"]), None)

    latest = None
    events = store.events_by_id(project)
    for t in reversed(store.transitions(project)):
        if t["error"] or not any(a["op"] != "NOOP" for a in t["applied"]):
            continue
        a = store.state_at(project, t["version_before"]) or state
        b = store.state_at(project, t["version_after"]) or state
        before, after = core_state(a), core_state(b)
        e = events.get(t["event_id"], {})
        latest = {"event": t["event_id"], "occurred_at": e.get("occurred_at"), "source": e.get("source"),
                  "text": (e.get("text") or "")[:160], "labels": change_labels(before, after, V.diff_states(a, b))[:4]}
        break
    return {
        "project": {k: s[k] for k in ("id", "name", "health", "flags", "last_updated", "age_days", "stale",
                                      "open_contradictions", "events", "confidence", "pending_imports")},
        "blocker": blocker,
        "next_step": nxt,
        "latest_change": latest,
        "milestone": {k: upcoming[k] for k in ("id", "title", "due_at", "state", "at_risk", "reasons")} if upcoming else None,
        "failed_imports": len(store.import_items(project, "failed")),
    }


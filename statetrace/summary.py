"""Derived, explainable read models for the dashboard: project health, before/after diffs of a
transition, and the evidence index (which claims each piece of evidence supports or ended).

Every number here is computed from claims with a stated rule; nothing is estimated.
"""

from datetime import datetime, timedelta

from . import view as V
from .schema import FIELD_LABELS, SCALAR_FIELDS

STALE_DAYS = 7
CORE_FIELDS = ("last_action", "current_status", "current_blocker", "next_step")
HEALTH_RULES = {
    "needs_review": "has at least one unresolved contradiction",
    "blocked": "has an active current blocker",
    "stale": f"no new evidence for {STALE_DAYS}+ days",
    "active": "none of the above",
    "confidence": ("high: >=70% of current-state claims verified by artifacts, no open contradictions, "
                   "not stale; low: open contradiction, stale, or <40% verified; otherwise medium"),
}


def _now(now=None):
    return now or datetime.now().replace(microsecond=0).isoformat()


def _days(a, b):
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400
    except (TypeError, ValueError):
        return None


def _brief(c):
    if not c:
        return None
    return {"id": c["id"], "value": c["value"], "verification": c["verification"],
            "confidence": c["confidence"], "evidence": c["evidence"], "as_of": c["as_of"],
            "contested": c.get("contested", False), "key": c.get("key")}


def project_summary(store, project, now=None):
    now = _now(now)
    state = store.latest_state(project)
    events = store.events(project)
    view = V.build_view(state)
    f = view["fields"]
    one = lambda k: (f[k][0] if f[k] else None)  # noqa: E731
    core = [c for k in CORE_FIELDS for c in f[k]] + f["status_items"]
    verified = sum(1 for c in core if c["verification"] == "verified")
    open_x = [x for x in view["contradictions"] if x["status"] == "open"]
    last = state.get("last_updated")
    age = _days(last, now) if last else None
    stale = age is not None and age >= STALE_DAYS
    verified_times = [c["as_of"] for c in core if c["verification"] == "verified"]
    ratio = verified / len(core) if core else 0
    if open_x or stale or ratio < 0.4:
        confidence = "low"
    elif ratio >= 0.7:
        confidence = "high"
    else:
        confidence = "medium"
    flags = []
    if open_x:
        flags.append("needs_review")
    if one("current_blocker"):
        flags.append("blocked")
    if stale:
        flags.append("stale")
    health = flags[0] if flags else ("active" if events else "empty")
    # activity: evidence per day over the last 14 days (by when it happened)
    end = datetime.fromisoformat(now).date()
    days = [(end - timedelta(days=13 - i)).isoformat() for i in range(14)]
    counts = {d: 0 for d in days}
    for e in events:
        d = e["occurred_at"][:10]
        if d in counts:
            counts[d] += 1
    return {
        "id": project,
        "name": store.project_name(project),
        "sample": store.project_is_sample(project),
        "health": health,
        "flags": flags,
        "goal": _brief(one("goal")),
        "current_status": _brief(one("current_status")),
        "current_blocker": _brief(one("current_blocker")),
        "next_step": _brief(one("next_step")),
        "last_action": _brief(one("last_action")),
        "last_updated": last,
        "age_days": round(age, 2) if age is not None else None,
        "last_verified": max(verified_times) if verified_times else None,
        "stale": stale,
        "open_contradictions": len(open_x),
        "open_questions": len(f["open_questions"]),
        "support": {"verified": verified, "total": len(core)},
        "confidence": confidence,
        "events": len(events),
        "pending_imports": len(store.import_items(project, "pending")),
        "version": state.get("version", 0),
        "activity": [counts[d] for d in days],
        "activity_days": days,
    }


def workspace_summary(store, now=None):
    from . import priority  # local import: priority -> reminders -> summary
    when = datetime.fromisoformat(now) if now else None
    projects = [project_summary(store, p, now) for p in store.projects() if p != "-"]
    for p in projects:
        p["priority"] = priority.score(store, p, when)
        r = store.latest_review(p["id"])
        p["review"] = ({"direction": r["review"]["direction"], "headline": r["review"]["headline"],
                        "top_suggestion": (r["review"]["suggestions"] or [{}])[0].get("title"),
                        "version": r["version"], "created_at": r["created_at"]} if r and r.get("review") else None)
    # most urgent first; ties: most recent evidence first (projects with no evidence last)
    projects.sort(key=lambda p: (p["priority"]["score"], p["last_updated"] or ""), reverse=True)
    today = _now(now)[:10]
    return {
        "projects": projects,
        "health": {
            "active": sum(1 for p in projects if not p["stale"]),
            "blocked": sum(1 for p in projects if "blocked" in p["flags"]),
            "updated_today": sum(1 for p in projects if (p["last_updated"] or "")[:10] == today),
            "needs_review": sum(1 for p in projects if p["stale"] or p["open_contradictions"]),
        },
        "rules": HEALTH_RULES,
        "priority_rules": __import__("statetrace.priority", fromlist=["RULES"]).RULES,
    }


def core_state(state):
    view = V.build_view(state)
    out = {k: _brief(view["fields"][k][0]) if view["fields"][k] else None for k in SCALAR_FIELDS}
    out["status_items"] = {c["key"]: _brief(c) for c in view["fields"]["status_items"]}
    out["open_contradictions"] = [x["id"] for x in view["contradictions"] if x["status"] == "open"]
    return out


def change_labels(before, after, changes):
    """Short human labels such as 'Blocker cleared' or 'timing updated'."""
    labels = []
    for k in ("current_blocker", "next_step", "current_status", "last_action", "goal"):
        a, b = before.get(k), after.get(k)
        name = FIELD_LABELS[k]
        if a and not b:
            labels.append(f"{name} cleared")
        elif b and not a:
            labels.append(f"{name} set")
        elif a and b and a["id"] != b["id"]:
            labels.append(f"{name} updated")
    for key, b in after["status_items"].items():
        a = before["status_items"].get(key)
        if a is None:
            labels.append(f"{key.replace('_', ' ')} added")
        elif a["id"] != b["id"]:
            labels.append(f"{key.replace('_', ' ')} updated")
    for c in changes:
        if c["kind"] == "contradiction_opened":
            labels.append(f"Contradiction {c['contradiction']} opened")
        elif c["kind"] == "contradiction_resolved":
            labels.append(f"Contradiction {c['contradiction']} resolved")
        elif c["kind"] == "added" and c["field"] in ("decisions", "attempts", "open_questions"):
            labels.append(f"{FIELD_LABELS[c['field']][:-1] if c['field'] != 'attempts' else 'Attempt'} recorded")
        elif c["kind"] == "invalidated" and c["field"] == "open_questions":
            labels.append("Question resolved")
    return labels


def transition_detail(store, project, event_id):
    t = next((t for t in reversed(store.transitions(project)) if t["event_id"] == event_id), None)
    event = store.get_event(project, event_id)
    if event is None:
        return None
    if t is None:
        return {"event": event, "transition": None}
    a = store.state_at(project, t["version_before"]) or store.latest_state(project)
    b = store.state_at(project, t["version_after"]) or a
    before, after = core_state(a), core_state(b)
    changes = V.diff_states(a, b) if not t["error"] else []
    return {
        "event": event,
        "transition": {k: t[k] for k in ("version_before", "version_after", "model", "latency_ms",
                                         "applied", "rejected", "warnings", "error")},
        "before": before,
        "after": after,
        "changes": changes,
        "labels": change_labels(before, after, changes) if not t["error"] else [],
    }


def evidence_index(store, project):
    """Every event with the claims it supports, the claims it ended, and its contradictions."""
    state = store.latest_state(project)
    trans = {t["event_id"]: t for t in store.transitions(project)}
    out = []
    for e in store.events(project):
        eid = e["id"]
        supports = [dict(_brief(c), field=c["field"], status=c["status"])
                    for c in state["claims"].values() if eid in c["evidence"]]
        ended = [dict(_brief(c), field=c["field"], status=c["status"])
                 for c in state["claims"].values() if c.get("ended_by") == eid]
        xs = [{"id": x["id"], "status": x["status"], "description": x["description"]}
              for x in state["contradictions"].values() if eid in x["event_ids"]]
        t = trans.get(eid)
        out.append({**e, "supports": supports, "ended": ended, "contradictions": xs,
                    "processed": bool(t and not t["error"]), "error": t["error"] if t else None,
                    "rejected": len(t["rejected"]) if t else 0})
    return out

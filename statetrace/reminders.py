"""Milestones, at-risk rules and deduplicated reminders.

Milestones are user commitments, kept separate from evidence-derived claims. A milestone with
origin "inferred" (a date suggested from evidence) stays unconfirmed, is never reminded about,
and is shown as a suggestion until the user confirms it.

At-risk rules are deterministic and every flag carries its reasons. No completion probabilities.
"""

from datetime import datetime, timedelta

from .summary import project_summary

DEFAULT_PREFS = {
    "enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "08:00",
    "default_reminders": [1440, 120],  # minutes before the due time
    "stale_alerts": True,
}
RISK_RULES = {
    "overdue": "the due date has passed and the milestone is still open",
    "due_soon": "due within 72 hours",
    "blocked": "the project has an active blocker and the milestone is due within 7 days",
    "contested": "the project has an unresolved contradiction and the milestone is due within 7 days",
    "stale": "the project has had no new evidence for 7+ days and the milestone is due within 14 days",
}


def prefs(store):
    p = dict(DEFAULT_PREFS)
    p.update(store.get_setting("notifications", {}) or {})
    return p


def set_prefs(store, update):
    p = prefs(store)
    for k in DEFAULT_PREFS:
        if k in update:
            p[k] = update[k]
    for k in ("quiet_start", "quiet_end"):
        datetime.strptime(str(p[k]), "%H:%M")  # validate HH:MM
    p["default_reminders"] = sorted({int(m) for m in p["default_reminders"] if int(m) > 0}, reverse=True)
    p["enabled"], p["stale_alerts"] = bool(p["enabled"]), bool(p["stale_alerts"])
    store.set_setting("notifications", p)
    return p


def in_quiet_hours(p, now):
    t = now.strftime("%H:%M")
    a, b = p["quiet_start"], p["quiet_end"]
    return (a <= t < b) if a <= b else (t >= a or t < b)


def _human(delta):
    s = abs(delta.total_seconds())
    if s < 3600:
        return f"{int(s // 60)} min"
    if s < 86400 * 2:
        return f"{int(s // 3600)} h"
    return f"{int(s // 86400)} days"


def assess(m, summary, now):
    """Return {state, at_risk, reasons}. `summary` is the project's project_summary."""
    if m["status"] in ("done", "dropped"):
        return {"state": m["status"], "at_risk": False, "reasons": []}
    if not m["confirmed"]:
        return {"state": "unconfirmed", "at_risk": False,
                "reasons": ["Date inferred from evidence; confirm it before it is treated as a deadline"]}
    if not m["due_at"]:
        return {"state": "no_date", "at_risk": False, "reasons": []}
    due = datetime.fromisoformat(m["due_at"])
    left = due - now
    reasons, rules = [], []
    if left.total_seconds() < 0:
        rules.append("overdue")
        reasons.append(f"Overdue by {_human(left)}")
    elif left <= timedelta(hours=72):
        rules.append("due_soon")
        reasons.append(f"Due in {_human(left)}")
    if left <= timedelta(days=7):
        if summary.get("current_blocker"):
            rules.append("blocked")
            reasons.append(f"Project is blocked: {summary['current_blocker']['value']}")
        if summary.get("open_contradictions"):
            rules.append("contested")
            reasons.append(f"{summary['open_contradictions']} unresolved contradiction(s) in the project state")
    if left <= timedelta(days=14) and summary.get("stale"):
        rules.append("stale")
        reasons.append(f"No new evidence for {int(summary.get('age_days') or 0)} days")
    state = "overdue" if "overdue" in rules else "due_soon" if "due_soon" in rules else "upcoming"
    return {"state": state, "at_risk": bool(rules), "rules": rules, "reasons": reasons}


def milestones_with_status(store, project=None, now=None):
    now = now or datetime.now().replace(microsecond=0)
    summaries = {}
    out = []
    for m in store.milestones(project):
        if m["project"] not in summaries:
            summaries[m["project"]] = project_summary(store, m["project"], now.isoformat())
        s = summaries[m["project"]]
        out.append({**m, "project_name": s["name"], **assess(m, s, now)})
    return out


def generate_notices(store, now=None):
    """Create due/overdue/stale notices once each (dedupe keys). Returns the newly created ones.
    Rescheduling a milestone changes its key, so the reminder re-arms for the new date."""
    now = now or datetime.now().replace(microsecond=0)
    p = prefs(store)
    created = []
    if not p["enabled"]:
        return created
    for m in milestones_with_status(store, now=now):
        if m["status"] != "open" or not m["confirmed"] or not m["due_at"]:
            continue
        if m["reminders"] == [-1]:  # the user asked for no reminders on this milestone
            continue
        due = datetime.fromisoformat(m["due_at"])
        offsets = [o for o in (m["reminders"] or p["default_reminders"]) if o > 0]
        if now >= due:
            key = f"milestone:{m['id']}:overdue:{m['due_at']}"
            if store.add_notice(m["project"], "milestone_overdue", key, f"Overdue: {m['title']}",
                                "; ".join(m["reasons"]), {"milestone": m["id"]}):
                created.append(key)
            continue
        due_offsets = [o for o in offsets if now >= due - timedelta(minutes=o)]
        if due_offsets:
            o = min(due_offsets)  # only the most specific reminder that is due
            key = f"milestone:{m['id']}:{o}:{m['due_at']}"
            if store.add_notice(m["project"], "milestone_due", key, f"Due in {_human(due - now)}: {m['title']}",
                                "; ".join(m["reasons"]) or "Reminder you asked for", {"milestone": m["id"]}):
                created.append(key)
    if p["stale_alerts"]:
        for pid in store.projects():
            s = project_summary(store, pid, now.isoformat())
            if s["stale"] and s["events"]:
                key = f"stale:{pid}:{s['last_updated']}"
                if store.add_notice(pid, "stale", key, f"{s['name']} may be stale",
                                    f"No new evidence for {int(s['age_days'])} days", {}):
                    created.append(key)
    return created


def notices_for_delivery(store, now=None):
    """Undismissed notices plus whether delivery should be quiet right now."""
    now = now or datetime.now().replace(microsecond=0)
    p = prefs(store)
    return {"notices": store.notices(), "quiet": in_quiet_hours(p, now) or not p["enabled"], "prefs": p,
            "rules": RISK_RULES}

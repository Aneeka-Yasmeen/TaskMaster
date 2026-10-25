"""Which project needs attention first: a deterministic score with stated reasons.

Score (higher = more urgent):
  overdue milestone 100 · due within 3 days 80 · within 7 days 60 · within 14 days 30
  + you marked the project High priority 40 (Low: -30)
  + active blocker 20 · unresolved contradiction 15 · updates waiting to sync 10
  + stale (7+ days without evidence) 10 · commits waiting for review 5
  + Nemotron's latest review says off track / blocked 15 (at risk 8)
"""

from datetime import datetime, timedelta

from .reminders import milestones_with_status

RULES = ("Overdue deadline 100; due ≤3 days 80; ≤7 days 60; ≤14 days 30; High priority +40 (Low −30); "
         "blocked +20; unresolved contradiction +15; updates waiting to sync +10; stale +10; commits to review +5; "
         "Nemotron's latest review: off track or blocked +15, at risk +8.")


def _when(delta):
    s = delta.total_seconds()
    if s < 0:
        return "overdue"
    if s < 86400:
        return f"due in {max(1, int(s // 3600))} h"
    return f"due in {int(s // 86400)} days"


def score(store, summary, now=None):
    now = now or datetime.now().replace(microsecond=0)
    pid = summary["id"]
    pts, reasons = 0, []
    ms = [m for m in milestones_with_status(store, pid, now)
          if m["status"] == "open" and m["confirmed"] and m["due_at"]]
    nxt = min(ms, key=lambda m: m["due_at"]) if ms else None
    if nxt:
        left = datetime.fromisoformat(nxt["due_at"]) - now
        for limit, p in ((timedelta(0), 100), (timedelta(days=3), 80), (timedelta(days=7), 60), (timedelta(days=14), 30)):
            if left <= limit:
                pts += p
                reasons.append(f"{nxt['title']}: {_when(left)}")
                break
    prio = store.project_priority(pid)
    if prio == "high":
        pts += 40
        reasons.append("you marked it High priority")
    elif prio == "low":
        pts -= 30
    if summary.get("current_blocker"):
        pts += 20
        reasons.append("blocked")
    if summary.get("open_contradictions"):
        pts += 15
        reasons.append("conflicting evidence to settle")
    queued = len(store.retryable_pending(pid))
    if queued:
        pts += 10
        reasons.append(f"{queued} update{'s' if queued > 1 else ''} waiting to sync")
    if summary.get("stale"):
        pts += 10
        reasons.append(f"no evidence for {int(summary.get('age_days') or 0)} days")
    r = store.latest_review(pid)
    verdict = (r or {}).get("review", {}).get("direction") if r else None
    if verdict in ("off_track", "blocked"):
        pts += 15
        reasons.append(f"Nemotron: {verdict.replace('_', ' ')}")
    elif verdict == "at_risk":
        pts += 8
        reasons.append("Nemotron: at risk")
    if summary.get("pending_imports"):
        pts += 5
        reasons.append(f"{summary['pending_imports']} commits to review")
    return {"score": pts, "reasons": reasons, "priority": prio, "queued": queued,
            "next_deadline": {k: nxt[k] for k in ("id", "title", "due_at", "state", "at_risk", "reasons")} if nxt else None}

"""Read model: turn a state into what the engineer sees, and compare state versions.

Answers to the fixed questions are rendered deterministically from validated claims, so every
sentence carries citations the validator already checked. Nothing here is generated text.
"""

from datetime import datetime

from .schema import FIELD_LABELS, KEYED_FIELDS, LIST_FIELDS, SCALAR_FIELDS


def build_view(state):
    """{"fields": {field: [active claims]}, "contradictions": [...], "last_updated": ts}."""
    fields = {f: [] for f in SCALAR_FIELDS + LIST_FIELDS + KEYED_FIELDS}
    for c in state["claims"].values():
        if c["status"] == "active" and c["field"] in fields:
            fields[c["field"]].append(c)
    return {
        "project": state["project"],
        "version": state.get("version"),
        "fields": fields,
        "contradictions": list(state["contradictions"].values()),
        "last_updated": state.get("last_updated"),
        "ended": [c for c in state["claims"].values() if c["status"] != "active"],
    }


def cite(ids):
    return "[" + ", ".join(ids) + "]" if ids else "[no evidence]"


def _mark(c):
    if c.get("contested"):
        return "⚠"
    return {"verified": "✓", "reported": "◐", "inferred": "~"}.get(c.get("verification"), "◐")


def _claim_line(c, label=None):
    label = label or (c.get("key") or "")
    prefix = f"{label}: " if label else ""
    note = ""
    if c.get("verification") == "reported":
        note = " (reported only — no supporting artifact)"
    elif c.get("verification") == "inferred":
        note = " (inferred)"
    if c.get("contested"):
        note += " (CONTESTED — see contradictions)"
    return f"{_mark(c)} {prefix}{c['value']}{note} {cite(c.get('evidence'))}"


def _days_since(ts, now):
    try:
        a = datetime.fromisoformat(ts)
        b = datetime.fromisoformat(now)
    except (TypeError, ValueError):
        return None
    return (b - a).days


def _one(view, field):
    items = view["fields"].get(field) or []
    return items[0] if items else None


def where_am_i(view, now=None, events=None, name=None):
    now = now or datetime.now().replace(microsecond=0).isoformat()
    out = []
    days = _days_since(view.get("last_updated"), now)
    header = f"Project {name or view['project']}"
    if view.get("last_updated"):
        header += f" — last evidence {view['last_updated'][:10]}"
        if days is not None and days >= 1:
            header += f" ({days} days ago)"
    out.append(header)
    if days is not None and days >= 7:
        out.append(f"You have been away {days} days. Here is the reconstructed state:")
    for field in ("goal", "current_status"):
        c = _one(view, field)
        if c:
            out.append(f"{FIELD_LABELS[field]}: {_claim_line(c, '')}")
    items = sorted(view["fields"]["status_items"], key=lambda c: c.get("as_of") or "")
    if items:
        out.append("Status by subject:")
        out.extend("  " + _claim_line(c) for c in items)
    verified_actions = [c for c in view["fields"]["last_action"] + items
                        if c.get("verification") == "verified"]
    if verified_actions:
        latest = max(verified_actions, key=lambda c: c.get("as_of") or "")
        out.append(f"Last verified result: {latest['value']} {cite(latest['evidence'])}")
    c = _one(view, "last_action")
    if c:
        out.append(f"Last action: {_claim_line(c, '')}")
    c = _one(view, "current_blocker")
    out.append(f"Current blocker: {_claim_line(c, '') if c else 'none recorded'}")
    c = _one(view, "next_step")
    out.append(f"Next step: {_claim_line(c, '') if c else 'none recorded'}")
    open_x = [x for x in view["contradictions"] if x["status"] == "open"]
    if open_x:
        out.append("Unresolved contradictions:")
        out.extend(f"  ! {x['id']}: {x['description']} {cite(x['event_ids'])}" for x in open_x)
    qs = view["fields"]["open_questions"]
    if qs:
        out.append("Open questions:")
        out.extend("  " + _claim_line(q, "") for q in qs)
    return "\n".join(out)


def what_blocks_me(view):
    out = []
    c = _one(view, "current_blocker")
    out.append(f"Current blocker: {_claim_line(c, '') if c else 'none recorded'}")
    failing = [s for s in view["fields"]["status_items"]
               if any(w in s["value"].lower() for w in ("fail", "violat", "negative", "mismatch", "drop"))
               and not any(w in s["value"].lower() for w in ("pass", " met", "0 failing"))]
    if failing:
        out.append("Failing items:")
        out.extend("  " + _claim_line(s) for s in failing)
    open_x = [x for x in view["contradictions"] if x["status"] == "open"]
    if open_x:
        out.append("Unresolved contradictions (the state cannot be trusted here until settled):")
        out.extend(f"  ! {x['id']}: {x['description']} {cite(x['event_ids'])}" for x in open_x)
    cleared = [c for c in view["ended"] if c["field"] == "current_blocker"]
    if cleared:
        out.append("Earlier blockers (no longer current):")
        for c in sorted(cleared, key=lambda c: c["as_of"]):
            out.append(f"  - {c['value']} {cite(c['evidence'])} — ended by {c['ended_by']}"
                       f" ({c['status']})")
    return "\n".join(out)


def what_did_i_try(view):
    out = []
    # superseded attempts were restated with their outcome; show only the latest version
    attempts = view["fields"]["attempts"] + [
        c for c in view["ended"] if c["field"] == "attempts" and c["status"] != "superseded"]
    if attempts:
        out.append("Attempts:")
        for c in sorted(attempts, key=lambda c: c["as_of"]):
            out.append(f"  {c['as_of'][:10]} {_claim_line(c, '')}")
    decisions = view["fields"]["decisions"] + [c for c in view["ended"] if c["field"] == "decisions"]
    if decisions:
        out.append("Decisions:")
        for c in sorted(decisions, key=lambda c: c["as_of"]):
            state = "" if c["status"] == "active" else f" — {c['status']} by {c['ended_by']}"
            out.append(f"  {c['as_of'][:10]} {_claim_line(c, '')}{state}")
    superseded = [c for c in view["ended"] if c["field"] == "status_items"]
    if superseded:
        out.append("Earlier results that have since changed:")
        for c in sorted(superseded, key=lambda c: c["as_of"]):
            out.append(f"  {c['as_of'][:10]} {c.get('key')}: {c['value']} {cite(c['evidence'])}"
                       f" → replaced by {c.get('superseded_by') or c['ended_by']}")
    return "\n".join(out) or "Nothing recorded yet."


def what_was_reversed(view):
    out = []
    ended = [c for c in view["ended"] if c["field"] in ("decisions", "attempts")
             and c["status"] in ("invalidated", "superseded")]
    for c in sorted(ended, key=lambda c: c["as_of"]):
        if c["field"] == "attempts" and c["status"] == "superseded":
            continue  # restated with its outcome, not reversed
        out.append(f"✕ {c['value']} {cite(c['evidence'])} — {c['status']} by {c['ended_by']}"
                   f"{': ' + c['end_reason'] if c.get('end_reason') else ''}")
    abandoned = [c for c in view["fields"]["attempts"]
                 if any(w in c["value"].lower() for w in ("abandon", "dropped", "revert", "gave up"))]
    for c in abandoned:
        out.append(f"✕ {c['value']} {cite(c['evidence'])}")
    if not out:
        return "No decisions have been reversed so far."
    return "Reversed or abandoned:\n" + "\n".join("  " + line for line in out)


def what_next(view):
    out = []
    c = _one(view, "next_step")
    out.append(f"Planned next step: {_claim_line(c, '') if c else 'none recorded'}")
    c = _one(view, "current_blocker")
    if c:
        out.append(f"It should address the current blocker: {_claim_line(c, '')}")
    open_x = [x for x in view["contradictions"] if x["status"] == "open"]
    for x in open_x:
        out.append(f"Settle contradiction {x['id']} with an artifact: {x['description']} {cite(x['event_ids'])}")
    unverified = [s for s in view["fields"]["status_items"] if s["verification"] != "verified"]
    for s in unverified:
        out.append(f"Produce evidence for reported-only claim: {_claim_line(s)}")
    for q in view["fields"]["open_questions"]:
        out.append(f"Open question: {_claim_line(q, '')}")
    return "\n".join(out)


def find_claims(state, query):
    """Locate claims for a "why" question: by claim id, field name, key, or text."""
    q = query.strip()
    claims = state["claims"]
    if q.upper() in claims:
        return [claims[q.upper()]]
    q_low = q.lower()
    for prefix in ("the ", "my ", "our "):
        if q_low.startswith(prefix):
            q_low = q_low[len(prefix):]
    q_low = q_low.strip().replace(" ", "_")
    field_hits = [c for c in claims.values() if c["status"] == "active"
                  and (c["field"] == q_low or c["field"].startswith(q_low))]
    if field_hits:
        return field_hits
    words = [w for w in q.lower().replace("_", " ").split() if len(w) > 2 and w not in STOP]
    scored = []
    for c in claims.values():
        hay = f"{c['field']} {c.get('key') or ''} {c['value']}".lower().replace("_", " ")
        score = sum(1 for w in words if w in hay)
        if score:
            scored.append((score, c["status"] == "active", c["as_of"], c))
    scored.sort(key=lambda t: t[:3], reverse=True)
    return [t[3] for t in scored[:3]]


STOP = {"why", "does", "the", "system", "believe", "that", "this", "what", "is", "are", "think",
        "current", "how", "know", "you", "about"}


def explain(state, events, query):
    hits = find_claims(state, query)
    if not hits:
        return f"No claim matches {query!r}."
    out = []
    if all(c["status"] != "active" for c in hits):
        out.append(f"Nothing matching {query!r} is currently believed. Closest earlier beliefs:")
    for c in hits:
        out.append(f"{c['id']} {c['field']}{'[' + c['key'] + ']' if c.get('key') else ''} = {c['value']!r}")
        out.append(f"  status: {c['status']}{', CONTESTED' if c.get('contested') else ''};"
                   f" verification: {c['verification']}; confidence: {c['confidence']}; as of {c['as_of']}")
        if c.get("rationale"):
            out.append(f"  engine rationale: {c['rationale']}")
        out.append("  supported by:")
        for eid in c["evidence"]:
            e = events.get(eid)
            if e:
                out.append(f"    {eid} {e['occurred_at']} [{e['source']}] {e['text'][:220]}")
        prev = c.get("supersedes")
        chain = []
        while prev and prev in state["claims"]:
            p = state["claims"][prev]
            chain.append(f"    {p['id']} {p['value']!r} {cite(p['evidence'])} — {p['status']} by {p['ended_by']}")
            prev = p.get("supersedes")
        if chain:
            out.append("  replaced earlier beliefs:")
            out.extend(chain)
        if c["status"] != "active":
            out.append(f"  ended by {c['ended_by']} ({c['ended_at']}): {c.get('end_reason') or ''}")
        for x in state["contradictions"].values():
            if c["id"] in x["claim_ids"]:
                out.append(f"  contradiction {x['id']} ({x['status']}): {x['description']} {cite(x['event_ids'])}")
                if x.get("resolution"):
                    out.append(f"    resolved by {x['resolved_by']}: {x['resolution']}")
    return "\n".join(out)


def diff_states(a, b):
    """What changed between two state versions."""
    changes = []
    for cid, c in b["claims"].items():
        old = a["claims"].get(cid)
        if old is None:
            changes.append({"kind": "added", "claim": cid, "field": c["field"], "key": c.get("key"),
                            "value": c["value"], "evidence": c["evidence"], "status": c["status"]})
        elif old["status"] != c["status"]:
            changes.append({"kind": c["status"], "claim": cid, "field": c["field"], "key": c.get("key"),
                            "value": c["value"], "by": c.get("ended_by")})
        elif old.get("contested") != c.get("contested"):
            changes.append({"kind": "contested" if c.get("contested") else "uncontested", "claim": cid,
                            "field": c["field"], "value": c["value"]})
    for xid, x in b["contradictions"].items():
        old = a["contradictions"].get(xid)
        if old is None:
            changes.append({"kind": "contradiction_opened", "contradiction": xid, "value": x["description"]})
        elif old["status"] != x["status"]:
            changes.append({"kind": "contradiction_" + x["status"], "contradiction": xid,
                            "value": x.get("resolution") or x["description"]})
    return changes

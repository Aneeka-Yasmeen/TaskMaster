"""Prompts for the state engine, the rewrite baseline, and grounded question answering."""

from .schema import KEYED_FIELDS, LIST_FIELDS, SCALAR_FIELDS, VERIFIABLE_SOURCES

_RULES = f"""
STATE FIELDS
- Single-valued (one current value each): {", ".join(SCALAR_FIELDS)}.
  last_action = the most recent concrete thing done. current_blocker = what currently prevents
  progress (invalidate it when evidence shows it is cleared).
- Lists: {", ".join(LIST_FIELDS)}. attempts = approaches tried and their outcome (history the
  engineer will want later; keep them even when the approach was abandoned).
- Keyed: {", ".join(KEYED_FIELDS)} = per-subject status. Always use field "status_items" plus a
  "key" naming the subject in snake_case (e.g. functional_simulation, axi_interface, synthesis,
  timing, resource_utilization, hardware_test). The key is NOT a field name.
  Reuse an existing key when the subject is the same.
- "field" must be exactly one of: {", ".join(SCALAR_FIELDS + LIST_FIELDS + KEYED_FIELDS)}.
- Optional details: decisions may carry "reason" and "tradeoff"; attempts may carry "outcome";
  open_questions may carry "progress": "open" or "investigating". Resolve a question with
  INVALIDATE (rationale = the answer).

EVIDENCE RULES
- verification "verified" only if the claim is directly supported by a machine artifact
  (sources: {", ".join(sorted(VERIFIABLE_SOURCES))}). A person's note, chat or meeting summary
  only supports "reported". Something nobody stated but you deduce is "inferred".
- Never claim that something passed, completed, or works unless the evidence says so. If a note
  claims completion that no artifact supports, record it as reported, not verified.
- Cite evidence ids exactly as given (E<number>). Do not invent ids.
- Prefer specific values (numbers, names, file/report ids) over vague summaries.
- If a note conflicts with a verified claim, do NOT overwrite the verified claim: emit CONTRADICT
  against it. Contradictions must be surfaced, not silently resolved.
- If later artifact evidence settles an open contradiction, emit RESOLVE for it.
- Evidence marked LATE-ARRIVING describes the past. It must not change current fields that were
  established by newer evidence; at most record it in attempts, or emit NOOP.
""".strip()

ENGINE_SYSTEM = f"""You are the state transition function of an engineering project tracker.
You receive the CURRENT STATE (a set of claims with ids, provenance and timestamps) and ONE piece
of NEW EVIDENCE. You do not rewrite the state. You output the minimal list of operations that the
new evidence justifies. A deterministic validator applies them.

OPERATIONS
- ADD: a new claim. Fields: field, value, (key for status_items), verification, confidence, evidence_ids.
- UPDATE: replace an existing active claim. Fields: target_claim_id, field, value, (key), verification, confidence, evidence_ids.
- INVALIDATE: an active claim is no longer true (e.g. a blocker was cleared). Fields: target_claim_id, field, evidence_ids, rationale.
- CONTRADICT: new evidence conflicts with an existing claim and the conflict cannot be settled from the
  evidence. Fields: target_claim_id, field, value (describe the conflict), evidence_ids.
- RESOLVE: an open contradiction is settled. Fields: target_contradiction_id, value (how), evidence_ids.
- NOOP: the evidence changes nothing. Fields: rationale.

{_RULES}

Every operation also gets a short "rationale".

CHECKLIST for every new evidence (answer each silently, emit operations for each "yes"):
1. Does it change last_action or current_status?
2. Does it clear, replace or make moot the current_blocker? (A fix that passes, or an
   architecture change that abandons the failing design, clears it: INVALIDATE or UPDATE it.)
3. Does it reveal a new blocker? A failing test/report on the critical path is a blocker.
4. Which status_items subjects does it change? Use UPDATE with the existing claim id.
5. Is the current next_step now done (INVALIDATE) or is a new one named (ADD/UPDATE)?
6. Is it an approach tried (attempts), a decision (decisions) or a question (open_questions)?
7. Does it conflict with a verified claim (CONTRADICT) or settle an open contradiction (RESOLVE)?

OUTPUT: only a JSON object, no prose:
{{"operations": [
 {{"op": "UPDATE", "target_claim_id": "C3", "field": "current_blocker", "value": "...",
   "verification": "verified", "confidence": "high", "evidence_ids": ["E8"], "rationale": "..."}},
 {{"op": "UPDATE", "target_claim_id": "C5", "field": "status_items", "key": "timing", "value": "...",
   "verification": "verified", "confidence": "high", "evidence_ids": ["E8"], "rationale": "..."}},
 {{"op": "ADD", "field": "decisions", "value": "...", "reason": "...", "tradeoff": "...",
   "verification": "reported", "confidence": "medium", "evidence_ids": ["E9"], "rationale": "..."}}
]}}
"""

BASELINE_SYSTEM = f"""You maintain the current state of an engineering project. You receive the
CURRENT STATE as JSON and ONE piece of NEW EVIDENCE. Output the complete updated state as JSON.

{_RULES}

OUTPUT: only a JSON object with exactly these keys:
{{"goal": {{"value": "...", "evidence": ["E1"]}} or null,
 "last_action": same shape or null, "current_status": same, "current_blocker": same, "next_step": same,
 "open_questions": [{{"value": "...", "evidence": ["E.."]}}], "decisions": [...], "attempts": [...],
 "status_items": [{{"key": "timing", "value": "...", "verification": "verified|reported|inferred", "evidence": ["E.."]}}],
 "contradictions": [{{"description": "...", "event_ids": ["E.."], "status": "open|resolved"}}]}}
"""

ANSWER_SYSTEM = """You answer an engineer's question about their project using ONLY the project
state and evidence given. Cite evidence ids in square brackets after each statement, e.g. [E8].
Distinguish verified facts from things that were only reported. If the state does not contain the
answer, say so. Be concise: at most 8 short lines."""


def _short(text, n=220):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def format_claim(c):
    key = f"{c['key']} = " if c.get("key") else ""
    flags = " CONTESTED" if c.get("contested") else ""
    if c.get("progress") == "investigating":
        flags += " INVESTIGATING"
    return (f"[{c['id']}] {key}\"{_short(c['value'])}\" | {c['verification']}, {c['confidence']}"
            f"{flags} | evidence: {', '.join(c['evidence'])} | as_of {c['as_of']}")


def render_state_for_prompt(state):
    lines = []
    claims = [c for c in state["claims"].values() if c["status"] == "active"]
    for field in SCALAR_FIELDS + LIST_FIELDS + KEYED_FIELDS:
        fc = [c for c in claims if c["field"] == field]
        if not fc:
            lines.append(f"{field}: (none)")
            continue
        lines.append(f"{field}:")
        lines.extend("  " + format_claim(c) for c in fc)
    xs = [x for x in state["contradictions"].values() if x["status"] == "open"]
    lines.append("open_contradictions:" + ("" if xs else " (none)"))
    for x in xs:
        lines.append(f"  [{x['id']}] {_short(x['description'])} | claims: {', '.join(x['claim_ids'])}"
                     f" | evidence: {', '.join(x['event_ids'])}")
    return "\n".join(lines)


def render_event(e, full=True):
    text = e["text"] if full else _short(e["text"], 160)
    kind = f"{e['source']}" + (f"/{e['event_type']}" if e.get("event_type") else "")
    ref = f" ref={e['ref']}" if e.get("ref") else ""
    return f"{e['id']} {e['occurred_at']} [{kind}{ref}] {text}"


def engine_user_prompt(state, recent_events, event):
    late = ""
    if state.get("last_updated") and event["occurred_at"] < state["last_updated"]:
        late = (f"\nLATE-ARRIVING: this evidence occurred at {event['occurred_at']}, before the "
                f"latest state update ({state['last_updated']}). Treat it as historical.")
    recent = "\n".join(render_event(e, full=False) for e in recent_events) or "(none)"
    return f"""CURRENT STATE (version {state['version']}, last updated {state.get('last_updated')})
{render_state_for_prompt(state)}

RECENT EVIDENCE (already processed, for context only)
{recent}

NEW EVIDENCE
id: {event['id']}
occurred_at: {event['occurred_at']}
source: {event['source']}{' (verifiable artifact)' if event['source'] in VERIFIABLE_SOURCES else ' (human report)'}
type: {event.get('event_type') or 'unspecified'}
ref: {event.get('ref') or '-'}{late}
text: {event['text']}

Return the operations JSON."""

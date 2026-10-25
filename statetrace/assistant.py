"""TaskMaster's assistant layer: Nemotron thinks, the user decides.

- answer(): questions go to Nemotron FIRST, grounded in the validated state, the evidence log and
  the stored-state answer. If the model can't be reached, the stored-state answer is returned and
  labelled as such. Citations in model answers are checked against the evidence log.
- review(): Nemotron compares the evidence-backed state with the goal and deadlines and says
  whether the project is moving in the right direction, with concerns and suggestions.
- Reviews are the model's OPINION. They are stored separately (assistant_reviews), never become
  claims or evidence, and are never acted on automatically. The user can turn a suggestion into
  an update or a milestone; that goes through the normal engine + validator.
- Autonomy (Settings): off | selected projects | all projects. It controls only *automatic*
  reviews and background monitoring scope. It never allows changing the state on its own.
"""

import json
import re
import time
from datetime import datetime

from . import view as V
from .ask import classify, answer as stored_answer, _structure
from .llm import LLMError, extract_json
from .prompts import render_event, render_state_for_prompt
from .reminders import milestones_with_status
from .summary import project_summary

ACCESS_LEVELS = ("off", "selected", "all")
DIRECTIONS = ("on_track", "at_risk", "off_track", "blocked", "unclear")
SUGGESTION_KINDS = ("next_step", "investigate", "decision", "evidence_needed", "milestone")

ASSISTANT_SYSTEM = """You are TaskMaster, an engineering project assistant (think: a sharp senior engineer
reviewing a colleague's project). You receive a project's VALIDATED STATE (claims with evidence ids,
verified = backed by a log/report/test, reported = a person said so), its evidence log, deadlines
and a stored-state summary.

Rules:
- Ground every factual statement in the evidence; cite evidence ids like [E12]. Only ids that start with E
  and appear in the EVIDENCE LOG are evidence. Claim ids like C19 are NOT evidence: never cite them, and
  never invent an E number.
- Distinguish verified facts from reported ones. Never claim something passed or is done without evidence.
- You may reason, compare, prioritise and suggest. You never claim to have done anything.
- Be direct and concise. Plain text, no markdown headings, at most 9 short lines."""

REVIEW_SYSTEM = """You are TaskMaster's project reviewer. Compare the project's VALIDATED STATE and EVIDENCE with
its GOAL and DEADLINES, and judge whether work is moving in the right direction.

Return ONLY a JSON object:
{"direction": "on_track|at_risk|off_track|blocked|unclear",
 "headline": "one sentence verdict",
 "progress": [{"text": "...", "evidence": ["E7"]}],
 "concerns": [{"text": "...", "evidence": ["E10"]}],
 "suggestions": [{"title": "short imperative", "why": "...", "kind": "next_step|investigate|decision|evidence_needed|milestone", "evidence": ["E10"]}],
 "questions": ["..."],
 "confidence": "low|medium|high"}

Rules: cite only evidence ids (E…) that appear in the EVIDENCE LOG. Claim ids (C…) are not evidence. At most 3 progress items, 3 concerns,
3 suggestions, 2 questions. Prefer suggestions that unblock the critical path or produce missing
verification (e.g. a test or report for a claim that is only reported). Mention deadline risk when
a deadline is close. Suggestions are advice for the engineer; do not present them as done."""


# settings -----------------------------------------------------------------------------------------
def access_prefs(store):
    p = {"access": "off", "projects": []}
    p.update(store.get_setting("assistant", {}) or {})
    return p


def set_access(store, access=None, projects=None):
    p = access_prefs(store)
    if access is not None:
        if access not in ACCESS_LEVELS:
            raise ValueError("access must be off, selected or all")
        p["access"] = access
    if projects is not None:
        known = set(store.projects())
        p["projects"] = [x for x in projects if x in known]
    store.set_setting("assistant", p)
    return p


def allowed(prefs, project):
    return prefs["access"] == "all" or (prefs["access"] == "selected" and project in prefs["projects"])


# context ------------------------------------------------------------------------------------------
def _context(store, project, now=None):
    now = now or datetime.now().replace(microsecond=0)
    state = store.latest_state(project)
    events = store.events(project)
    ms = [m for m in milestones_with_status(store, project, now) if m["status"] == "open"]
    s = project_summary(store, project, now.isoformat())
    lines = [f"PROJECT: {s['name']} (state version {state['version']}, last evidence {s['last_updated']}, "
             f"today {now.isoformat()}, stale: {s['stale']})",
             "", "VALIDATED STATE", render_state_for_prompt(state), "", "DEADLINES (set by the user)"]
    lines += [f"- {m['title']}: due {m['due_at'] or 'no date'}; {m['state']}" + (f"; at risk: {'; '.join(m['reasons'])}" if m["at_risk"] else "")
              for m in ms] or ["- none"]
    lines += ["", "EVIDENCE LOG (oldest first)"] + [render_event(e, full=False) for e in events[-40:]]
    return "\n".join(lines), {e["id"]: e for e in events}, state


def normalize_citations(text):
    """Seen live: Nemotron writes 【E7】 or (E7). Normalise to [E7] so the UI links the evidence."""
    text = re.sub(r"[【\[(]\s*(E\d+(?:\s*[,，;、]\s*E\d+)*)\s*[】\])]",
                  lambda m: "[" + ", ".join(re.findall(r"E\d+", m.group(1))) + "]", text)
    return text


def _check_citations(text, events):
    cited = set(re.findall(r"\bE\d+\b", text))
    return sorted(c for c in cited if c in events), sorted(c for c in cited if c not in events)


# Nemotron-first answers ---------------------------------------------------------------------------
def answer(store, project, question, llm, now=None):
    """Nemotron first; the stored-state answer is always computed too (grounding + fallback)."""
    base = stored_answer(store, project, question, llm=None, now=now)
    if llm is None or not hasattr(llm, "chat"):
        base["mode"] = "stored state (Nemotron not connected)"
        base["source"] = "stored"
        return base
    ctx, events, state = _context(store, project, datetime.fromisoformat(now) if now else None)
    prompt = (f"{ctx}\n\nSTORED-STATE ANSWER (deterministic, from validated claims; use it, but think beyond it)\n"
              f"{base['text']}\n\nQUESTION: {question}\n\nAnswer the question. Start with a one-line direct answer.")
    t0 = time.perf_counter()
    try:
        text = llm.chat(ASSISTANT_SYSTEM, prompt, max_tokens=5000)  # room for reasoning tokens
    except LLMError as e:
        base["mode"] = f"stored state (Nemotron unavailable: {str(e)[:120]})"
        base["source"] = "stored"
        return base
    text = normalize_citations(re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip())
    if not text:
        base["mode"] = "stored state (Nemotron returned nothing)"
        base["source"] = "stored"
        return base
    good, invented = _check_citations(text, events)
    for bad in invented:
        text = re.sub(rf"\b{bad}\b", f"{bad}(?)", text)
    view = V.build_view(state)
    out = _structure(classify(question), text, view, events,
                     f"Nemotron · {getattr(llm, 'name', 'model')} · grounded in state v{state['version']}")
    out.update({"source": "nemotron", "headline": text.splitlines()[0][:200], "latency_ms": int((time.perf_counter() - t0) * 1000),
                "invented_citations": invented, "stored": {"headline": base["headline"], "text": base["text"]}})
    if invented:
        out["text"] += f"\n\n[validator] cited evidence that doesn't exist: {', '.join(invented)}"
    if not good:
        out["text"] += "\n\n[validator] this answer cites no evidence; treat it as an opinion."
    return out


# reviews ------------------------------------------------------------------------------------------
def _clean_items(items, events, limit, keys):
    out = []
    for it in (items or [])[:limit]:
        if isinstance(it, str):
            it = {keys[0]: it}
        if not isinstance(it, dict) or not str(it.get(keys[0], "")).strip():
            continue
        ev = [e for e in (it.get("evidence") or []) if isinstance(e, str) and e in events]
        clean = {k: str(it.get(k, "")).strip()[:300] for k in keys}
        clean["evidence"] = ev
        out.append(clean)
    return out


def review(store, project, llm, trigger="manual", force=False, now=None):
    """Ask Nemotron for a progress review of the current state version (cached per version)."""
    state = store.latest_state(project)
    last = store.latest_review(project)
    if last and last["version"] == state["version"] and not force:
        return {**last, "cached": True}
    if llm is None or not hasattr(llm, "chat"):
        raise LLMError("Nemotron is not connected")
    ctx, events, _ = _context(store, project, now)
    t0 = time.perf_counter()
    try:
        raw = llm.chat(REVIEW_SYSTEM, ctx + "\n\nReturn the review JSON.", json_mode=True, max_tokens=6000)
        data = extract_json(raw)
    except LLMError as e:
        store.add_review(project, state["version"], trigger, getattr(llm, "name", None), error=str(e),
                         latency_ms=int((time.perf_counter() - t0) * 1000))
        raise
    direction = str(data.get("direction", "unclear")).lower()
    clean = {
        "direction": direction if direction in DIRECTIONS else "unclear",
        "headline": str(data.get("headline", "")).strip()[:300],
        "progress": _clean_items(data.get("progress"), events, 3, ("text",)),
        "concerns": _clean_items(data.get("concerns"), events, 3, ("text",)),
        "suggestions": _clean_items(data.get("suggestions"), events, 3, ("title", "why", "kind")),
        "questions": [str(q).strip()[:200] for q in (data.get("questions") or [])[:2] if str(q).strip()],
        "confidence": str(data.get("confidence", "low")).lower() if str(data.get("confidence", "")).lower() in ("low", "medium", "high") else "low",
    }
    for sgg in clean["suggestions"]:
        if sgg["kind"] not in SUGGESTION_KINDS:
            sgg["kind"] = "next_step"
    rid = store.add_review(project, state["version"], trigger, getattr(llm, "name", None), review=clean,
                           latency_ms=int((time.perf_counter() - t0) * 1000))
    return {**store.latest_review(project), "id": rid, "cached": False}


# catch-up: "Where did I leave off, and what should I do next?" ----------------------------------
CATCHUP_SYSTEM = """You are TaskMaster. The engineer is returning to this project and asks:
"Where did I leave off, and what should I do next?" Reconstruct the answer ONLY from the VALIDATED STATE.

Return ONLY a JSON object:
{"headline": "one sentence: where things stand",
 "left_off": [{"text": "...", "claims": ["C3"]}],
 "established": [{"text": "...", "claims": ["C5"]}],
 "blockers": [{"text": "...", "claims": ["C7"]}],
 "next_action": {"text": "short imperative", "why": "...", "claims": ["C9"]} or null,
 "no_next_action_reason": "only when next_action is null",
 "uncertain": [{"text": "...", "claims": ["C4"]}],
 "missing_evidence": ["what would have to be logged/run to know more"]}

Rules:
- Every item must reference the claim ids (C…) in the VALIDATED STATE that support it. Do not cite E ids here;
  TaskMaster attaches the evidence from the claims itself.
- An item you cannot support with a claim id must have "claims": [] - it will be shown as your inference.
- TaskMaster displays the referenced claim's own text as the fact. Your "text" is shown only as your wording,
  so never add numbers, results or outcomes the claim does not state.
- next_action: reference the next_step claim if one exists. An action that is not recorded is shown as your suggestion.
- "established" = only claims marked verified. Anything reported or CONTESTED goes in "uncertain" or "blockers".
- Open contradictions are blockers until resolved.
- If the state does not justify a next action, set next_action to null and explain why. Do not invent work.
- At most 3 items per list. Be concise and concrete."""

SECTION_KEYS = ("left_off", "established", "blockers", "uncertain")
BASIS_RANK = {"verified": 0, "reported": 1, "inferred": 2}
GROUNDING_VERSION = 3  # cached catch-ups built by older grounding rules are not reused

# Grounding: a displayed FACT is always the stored value of a validated claim. Nemotron's sentence is kept
# only as a labelled note, and only if it introduces no number or pass/fail-type word the claim lacks
# (seen live: a sentence about E8 attached to a claim backed by E3; a sentence can also exaggerate).
_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:\s*/\s*\d+)?")
_RESULT_WORDS = {
    "pass": r"pass(?:es|ed|ing)?", "fail": r"fail(?:s|ed|ing|ures?)?", "fixed": r"fix(?:ed|es)",
    "met": r"met|meets", "works": r"works?|working", "closed": r"closed?|closure", "done": r"done|complete[sd]?",
    "clean": r"clean", "resolved": r"resolved?", "verified": r"verified|confirmed", "broken": r"broken",
    "violation": r"violat\w*", "error": r"errors?", "mismatch": r"mismatch\w*", "blocked": r"blocked|blocking",
}


def _facts(text):
    t = (text or "").lower()
    nums = {re.sub(r"\s+", "", n) for n in _NUM_RE.findall(t)}
    words = {k for k, rx in _RESULT_WORDS.items() if re.search(rf"\b(?:{rx})\b", t)}
    return nums, words


def unsupported_in(sentence, sources):
    """Numbers and result words in `sentence` that none of the `sources` texts contain."""
    nums, words = _facts(sentence)
    ok_nums, ok_words = set(), set()
    for src in sources:
        n, w = _facts(src)
        ok_nums |= n
        ok_words |= w
    return sorted(nums - ok_nums) + sorted(words - ok_words)


def _claim_text(c):
    return (f"{c['key'].replace('_', ' ')}: " if c.get("key") else "") + str(c["value"])


def _ground(item, state, events, notes, kind="item"):
    """Ground one model item. Facts come from the referenced *active* claims (their stored values, evidence
    and verification); the model's sentence is never given a verification badge on its own.
    kind="next_action": the action counts as recorded only if it references an active next_step claim;
    otherwise it is Nemotron's suggestion, shown as such with the claims it was based on."""
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict) or not str(item.get("text", "")).strip():
        return None
    model_text = str(item["text"]).strip()[:300]
    refs = [c for c in (item.get("claims") or []) if isinstance(c, str)]
    claims = []
    for cid in refs:
        c = state["claims"].get(cid)
        if c is None:
            notes.append(f"{cid} does not exist (dropped)")
        elif c["status"] != "active":
            notes.append(f"{cid} is {c['status']}, no longer current (dropped)")
        elif c not in claims:
            claims.append(c)
    why = str(item.get("why") or "").strip()[:300]
    if not claims:  # nothing in the validated state supports it: an inference, never a fact
        out = {"text": model_text, "claims": [], "basis": "inference", "evidence": [], "as_of": None, "contested": False}
        if why:
            out["why"] = why
        return out
    sources = [_claim_text(c) for c in claims]
    if kind == "next_action" and not any(c["field"] == "next_step" for c in claims):
        # the action itself is not recorded anywhere; the claims are only what it was based on
        out = {"text": model_text, "claims": [], "basis": "suggestion", "evidence": [], "as_of": None,
               "contested": False, "based_on": [{"id": c["id"], "text": _claim_text(c), "verification": c["verification"],
                                                 "contested": bool(c.get("contested")), "evidence": c["evidence"]} for c in claims]}
        bad = unsupported_in(model_text, sources)
        if bad:
            out["unsupported_terms"] = bad
            notes.append(f"Nemotron's suggested next action mentions {', '.join(bad)}, which the cited claims don't state")
        if why and not unsupported_in(why, sources):
            out["why"] = why
        return out
    if kind == "next_action":
        claims = [c for c in claims if c["field"] == "next_step"] + [c for c in claims if c["field"] != "next_step"]
        claims = claims[:1]  # the recorded next step is the fact; other refs were context
        sources = [_claim_text(claims[0])]
    out = {"text": " · ".join(_claim_text(c) for c in claims)[:400], "claims": [c["id"] for c in claims]}
    out["evidence"] = sorted({e for c in claims for e in c["evidence"] if e in events}, key=lambda x: int(x[1:]))
    out["contested"] = any(c.get("contested") for c in claims)
    weakest = max((c["verification"] for c in claims), key=lambda v: BASIS_RANK.get(v, 3))
    out["basis"] = "contested" if out["contested"] else weakest
    out["as_of"] = min(c["as_of"] for c in claims)
    if " ".join(model_text.lower().split()) != " ".join(out["text"].lower().split()):
        bad = unsupported_in(model_text, sources)
        if bad:
            notes.append(f"Nemotron's sentence for {', '.join(out['claims'])} mentions {', '.join(bad)}, "
                         "which the claim doesn't state; showing the claim instead")
        elif set(re.findall(r"[a-z0-9]+", model_text.lower())) - set(re.findall(r"[a-z0-9]+", " ".join(sources).lower())):
            out["note"] = model_text  # Nemotron's wording (adds words, no new facts): shown as such, never badged
        # else: the sentence only restates the claim (seen live: 'key = "value"' echoes); nothing to add
    if why:
        if unsupported_in(why, sources):
            notes.append(f"Nemotron's explanation for {', '.join(out['claims'])} went beyond the claim; hidden")
        else:
            out["why"] = why
    return out


def _stored_catchup(state, events):
    """Deterministic fallback straight from validated claims. No model involved."""
    active = [c for c in state["claims"].values() if c["status"] == "active"]
    by = lambda *fields: [c for c in active if c["field"] in fields]
    item = lambda c: {"text": (f"{c['key']}: " if c.get("key") else "") + str(c["value"]), "claims": [c["id"]]}
    raw = {
        "headline": "",
        "left_off": [item(c) for c in sorted(by("last_action", "current_status"), key=lambda c: c["as_of"], reverse=True)[:3]],
        "established": [item(c) for c in by("status_items", "decisions") if c["verification"] == "verified" and not c.get("contested")][:3],
        "blockers": [item(c) for c in by("current_blocker")][:3],
        "uncertain": [item(c) for c in active if c["field"] != "goal" and (c.get("contested") or c["verification"] != "verified")
                      and c["field"] in ("status_items", "current_status")][:3],
        "missing_evidence": [f"{c['key'] or c['field']} is only {c['verification']} - no log, test or report confirms it"
                             for c in by("status_items") if c["verification"] != "verified"][:3],
    }
    nxt = by("next_step")
    raw["next_action"] = item(nxt[0]) if nxt else None
    raw["no_next_action_reason"] = "" if nxt else "No next step is recorded in the evidence."
    return raw


def _assemble(raw, state, events, source, mode, s):
    notes = []
    out = {"source": source, "mode": mode, "version": state["version"], "stale": bool(s.get("stale")),
           "last_evidence": s.get("last_updated"), "headline": str(raw.get("headline") or "").strip()[:300],
           "grounding": GROUNDING_VERSION}
    for k in SECTION_KEYS:
        out[k] = [g for g in (_ground(i, state, events, notes) for i in (raw.get(k) or [])[:3]) if g]
    # "established" must be verified: demote anything weaker instead of trusting the model's placement
    weak = [i for i in out["established"] if i["basis"] != "verified"]
    out["established"] = [i for i in out["established"] if i["basis"] == "verified"]
    out["uncertain"] = (out["uncertain"] + weak)[:4]
    if weak:
        notes.append(f"{len(weak)} item(s) moved from 'established' to 'uncertain': not verified")
    nxt = _ground(raw.get("next_action"), state, events, notes, kind="next_action") if raw.get("next_action") else None
    out["next_action"] = nxt
    out["no_next_action_reason"] = "" if nxt else (str(raw.get("no_next_action_reason") or "").strip()[:300]
                                                     or "The evidence does not justify a specific next action yet.")
    out["missing_evidence"] = [str(m).strip()[:200] for m in (raw.get("missing_evidence") or [])[:3] if str(m).strip()]
    out["contradictions"] = [{"id": x["id"], "description": x["description"], "claims": x["claim_ids"], "evidence": x["event_ids"]}
                             for x in state["contradictions"].values() if x["status"] == "open"]
    out["validator_notes"] = notes
    out["headline_source"] = "nemotron" if out["headline"] else "claims"
    if out["headline"]:
        # the headline is a summary across the whole state: it may not add numbers or results no claim states
        active = [_claim_text(c) for c in state["claims"].values() if c["status"] == "active"]
        active += [x["description"] for x in state["contradictions"].values() if x["status"] == "open"]
        bad = unsupported_in(out["headline"], active)
        if bad:
            notes.append(f"Nemotron's headline mentioned {', '.join(bad)}, which no current claim states; replaced")
            out["headline"], out["headline_source"] = "", "claims"
    if not out["headline"]:
        out["headline"] = (out["left_off"][0]["text"] if out["left_off"] else "No recorded progress yet.")
    if not any(out[k] for k in SECTION_KEYS) and not nxt:
        out["empty"] = True
    return out


def catch_up(store, project, llm, force=False, now=None, use_model=True):
    """Structured catch-up for the current state version. Nemotron proposes the narrative and points at
    claim ids; verification, evidence and staleness come from the validated claims. Cached per version."""
    state = store.latest_state(project)
    events = {e["id"]: e for e in store.events(project)}
    s = project_summary(store, project, now)
    last = store.latest_review(project, kind="catchup")
    if last and last["version"] == state["version"] and not force and (last["review"] or {}).get("grounding") == GROUNDING_VERSION:
        return {**last["review"], "cached": True, "created_at": last["created_at"], "latency_ms": last["latency_ms"]}

    def fallback(reason):
        return {**_assemble(_stored_catchup(state, events), state, events, "stored", reason, s), "cached": False}

    if not state["claims"]:
        return fallback("stored state (no validated claims yet; nothing to reconstruct)")
    if not use_model:
        out = fallback("stored state (deterministic, from validated claims; no model call)")
        if last and (last["review"] or {}).get("grounding") == GROUNDING_VERSION:
            out["previous_nemotron_version"] = last["version"]
        return out
    if llm is None or not hasattr(llm, "chat"):
        return fallback("stored state (Nemotron not connected)")
    ctx, _, _ = _context(store, project, datetime.fromisoformat(now) if now else None)
    t0 = time.perf_counter()
    try:
        data = extract_json(llm.chat(CATCHUP_SYSTEM, ctx + "\n\nReturn the catch-up JSON.", json_mode=True, max_tokens=6000))  # seen live: 2000 left no room after reasoning
        if not isinstance(data, dict):
            raise LLMError("catch-up response was not a JSON object")
    except LLMError as e:
        latency = int((time.perf_counter() - t0) * 1000)
        store.add_review(project, state["version"], "catch-up", getattr(llm, "name", None), error=str(e)[:300],
                         latency_ms=latency, kind="catchup")
        out = fallback(f"stored state (Nemotron unavailable or malformed: {str(e)[:120]})")
        out["model_error"] = str(e)[:300]
        return out
    latency = int((time.perf_counter() - t0) * 1000)
    out = _assemble(data, state, events, "nemotron",
                    f"Nemotron · {getattr(llm, 'name', 'model')} · checked against state v{state['version']}", s)
    out["latency_ms"] = latency
    store.add_review(project, state["version"], "catch-up", getattr(llm, "name", None), review=out,
                     latency_ms=latency, kind="catchup")
    return {**out, "cached": False}


def review_json_safe(r):
    return json.loads(json.dumps(r)) if r else None

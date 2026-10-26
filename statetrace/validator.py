"""Deterministic provenance/validation layer.

The model *proposes* operations; this module decides what actually changes. Rules:

1. Every claim cites evidence. Unknown evidence ids are stripped (and counted as invented
   citations); the triggering evidence is always cited.
2. "verified" requires at least one cited artifact from a verifiable source (report, log,
   commit, ...). Otherwise the claim is downgraded to "reported". Confidence is capped by
   verification level.
3. Staleness: evidence that occurred before a claim's own evidence cannot supersede or
   invalidate it (late-arriving notes do not resurrect old blockers).
4. Scalar fields hold one active claim; adding a new one supersedes the old one. Keyed
   status items supersede by key. Nothing is deleted: ended claims keep who ended them and why.
5. Contradictions are recorded and the claims they touch are marked contested; they stay open
   until a RESOLVE operation cites evidence that settles them.
"""

import copy
import re

from .schema import (
    ALL_FIELDS, CONFIDENCE_CAP, CONFIDENCE_LEVELS, CONFIDENCE_RANK, KEYED_FIELDS, LIST_FIELDS,
    MAX_OPS_PER_EVENT, MAX_VALUE_CHARS, OPS, SCALAR_FIELDS, VERIFIABLE_SOURCES,
)


# Sources that only prove a change was recorded (not its outcome).
CHANGE_ONLY_SOURCES = {"git_commit"}
# Outcome language: claims like these need a test/sim/report artifact to be verified.
RESULT_RE = re.compile(
    r"\b(pass(es|ed|ing)?|fail(s|ed|ing|ure)?|met|meets|works?|working|validated|verified|"
    r"closes timing|timing closed|wns|slack|regression|no errors?)\b|\b\d+\s*/\s*\d+\b",
    re.I)


class OpRejected(Exception):
    pass


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def normalize_key(key):
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")[:60]


def active_claims(state, field=None):
    return [
        c for c in state["claims"].values()
        if c["status"] == "active" and (field is None or c["field"] == field)
    ]


class TransitionLog:
    def __init__(self):
        self.applied = []
        self.rejected = []
        self.warnings = []

    def as_dict(self):
        return {"applied": self.applied, "rejected": self.rejected, "warnings": self.warnings}


def apply_operations(state, operations, event, events):
    """Return (new_state, log). `events` maps evidence id -> event row for this project."""
    new = copy.deepcopy(state)
    log = TransitionLog()
    if not isinstance(operations, list):
        log.warnings.append({"type": "malformed_output", "detail": "operations is not a list"})
        operations = []
    if len(operations) > MAX_OPS_PER_EVENT:
        log.warnings.append({"type": "too_many_ops", "detail": f"kept first {MAX_OPS_PER_EVENT}"})
    for raw in operations[:MAX_OPS_PER_EVENT]:
        if not isinstance(raw, dict):
            log.rejected.append({"op": raw, "reason": "operation is not an object"})
            continue
        try:
            _apply_one(new, raw, event, events, log)
        except OpRejected as e:
            log.rejected.append({"op": raw, "reason": str(e)})
    _close_moot_contradictions(new, event, log)
    new["version"] = state["version"] + 1
    new["last_event_id"] = event["id"]
    if not new["last_updated"] or event["occurred_at"] > new["last_updated"]:
        new["last_updated"] = event["occurred_at"]
    return new, log


# ---------------------------------------------------------------------------------------------

def _apply_one(state, raw, event, events, log):
    op = str(raw.get("op", "")).upper().strip()
    if op not in OPS:
        raise OpRejected(f"unknown op {op!r}")
    rationale = str(raw.get("rationale", ""))[:MAX_VALUE_CHARS]
    if op == "NOOP":
        log.applied.append({"op": "NOOP", "rationale": rationale})
        return

    evidence = _clean_evidence(raw.get("evidence_ids"), event, events, log)
    if op == "RESOLVE":
        _resolve(state, raw, evidence, event, rationale, log, events)
        return

    field, key = _repair_field(state, raw, log)
    if field not in ALL_FIELDS:
        raise OpRejected(f"unknown field {field!r}")
    value = str(raw.get("value") or "").strip()[:MAX_VALUE_CHARS]
    if field == "open_questions":
        # seen live: the model writes the progress into the text, e.g. "[open] Whether ..."
        m = re.match(r"^\[(open|investigating)\]\s*", value, flags=re.I)
        if m:
            value = value[m.end():]
            raw = dict(raw, progress=raw.get("progress") or m.group(1).lower())
    verification, confidence = _verification(raw, evidence, events, log)
    target = _resolve_target(state, raw, field, key, value, log)

    if op == "ADD":
        if not value:
            raise OpRejected("ADD without a value")
        if field in KEYED_FIELDS and not key:
            key = normalize_key(" ".join(value.split()[:3]))
        if field in LIST_FIELDS and target is not None:
            # Same item restated: strengthen provenance instead of duplicating.
            target["evidence"] = sorted(set(target["evidence"]) | set(evidence), key=_eid_order)
            target["as_of"] = max(target["as_of"], event["occurred_at"])
            log.applied.append({"op": "REINFORCE", "claim": target["id"], "evidence": evidence})
            return
        # A scalar/keyed field that already has an active claim is superseded (UPDATE path);
        # otherwise a fresh claim is created (target stays None).
    if op in ("ADD", "UPDATE"):
        if not value:
            raise OpRejected("UPDATE without a value")
        if target is None:
            if field in KEYED_FIELDS and not key:
                raise OpRejected("UPDATE of status item without a key or target")
        else:
            _check_target(target, field, event)
            reason = _protect_verified(target, "UPDATE", verification, evidence, events, log,
                                       claimed=f"{event.get('text', '')} {value} {rationale}")
            if reason:
                _contradict(state, target, _converted_description(event, value or rationale, target, reason),
                            evidence, event, log, converted=reason)
                return
        claim = _new_claim(state, field, key or (target or {}).get("key"), value, verification,
                           confidence, evidence, event, rationale)
        _copy_details(claim, raw, target)
        if target is not None:
            _end(target, "superseded", event, rationale, superseded_by=claim["id"])
            claim["supersedes"] = target["id"]
        log.applied.append({"op": "UPDATE" if target else "ADD", "claim": claim["id"],
                            "field": field, "key": claim["key"], "value": value,
                            "verification": verification, "supersedes": claim.get("supersedes")})
        return

    if op == "INVALIDATE":
        if target is None:
            raise OpRejected(f"INVALIDATE: no active claim to invalidate in {field}")
        _check_target(target, field, event)
        reason = _protect_verified(target, "INVALIDATE", verification, evidence, events, log,
                                   claimed=f"{event.get('text', '')} {value} {rationale}")
        if reason:
            _contradict(state, target, _converted_description(event, rationale or value or "it no longer holds", target, reason),
                        evidence, event, log, converted=reason)
            return
        _end(target, "invalidated", event, rationale or value, evidence=evidence)
        log.applied.append({"op": "INVALIDATE", "claim": target["id"], "field": field,
                            "reason": rationale or value})
        return

    if op == "CONTRADICT":
        if target is None:
            raise OpRejected("CONTRADICT: no existing claim identified")
        description = value or rationale
        if not description:
            raise OpRejected("CONTRADICT without a description")
        if event["occurred_at"] < target["as_of"]:
            # Seen live: a late-arriving outdated note "contradicted" a newer passing sim log.
            # Older evidence describes the past; it cannot contest a belief established after it.
            raise OpRejected(f"stale evidence: {event['id']} ({event['occurred_at']}) predates {target['id']} "
                             f"({target['as_of']}); it describes the past, not a conflict")
        _contradict(state, target, description, evidence, event, log)


def _contradict(state, target, description, evidence, event, log, converted=None):
    for x in state["contradictions"].values():
        if x["status"] == "open" and x["opened_by"] == event["id"]:
            # One piece of evidence conflicting with several claims is one contradiction.
            if target["id"] in x["claim_ids"]:
                raise OpRejected(f"duplicate of contradiction {x['id']}")
            x["claim_ids"].append(target["id"])
            x["event_ids"] = sorted(set(x["event_ids"]) | set(target["evidence"]), key=_eid_order)
            target["contested"] = True
            log.applied.append({"op": "CONTRADICT", "contradiction": x["id"], "claim": target["id"],
                                "description": x["description"], "merged": True, "converted": converted})
            return
    xid = f"X{state['next_contradiction']}"
    state["next_contradiction"] += 1
    state["contradictions"][xid] = {
        "id": xid,
        "description": description[:MAX_VALUE_CHARS],
        "claim_ids": [target["id"]],
        "event_ids": sorted(set(evidence) | set(target["evidence"]), key=_eid_order),
        "status": "open",
        "opened_by": event["id"],
        "opened_at": event["occurred_at"],
        "resolved_by": None,
        "resolution": None,
    }
    target["contested"] = True
    log.applied.append({"op": "CONTRADICT", "contradiction": xid, "claim": target["id"],
                        "description": description, "converted": converted})


def _protect_verified(target, op, new_verification, evidence, events, log, claimed=""):
    """Verified facts must not be ended by weaker evidence. Returns a reason when the operation
    has to become a contradiction instead (seen live: a commit message claiming "14/14 pass"
    cleared a blocker that a test artifact had established).

    - status_items (measured results): only a verified replacement, or an invalidation backed by
      a test/sim/report artifact, may end a verified item.
    - current_blocker: commits alone cannot clear or replace a verified blocker. A person's report
      may (abandoning a design is a human decision), but that is logged - unless the person is
      asserting a result ("fixed, all 256 vectors pass"): seen live, a chat message cleared a blocker
      that a failing sim log had established. A claimed result needs a re-run, so it becomes a
      contradiction instead.
    """
    if target is None or target.get("verification") != "verified":
        return None
    sources = {events[e]["source"] for e in evidence if e in events}
    artifact = (sources & VERIFIABLE_SOURCES) - CHANGE_ONLY_SOURCES
    human = sources - VERIFIABLE_SOURCES
    if target["field"] == "status_items":
        if op == "UPDATE" and new_verification == "verified":
            return None
        if op == "INVALIDATE" and artifact:
            return None
        return "a verified result can only be replaced by another verified result"
    if target["field"] == "current_blocker":
        if artifact:
            return None
        if human and RESULT_RE.search(claimed or ""):
            return "a person's report of a result does not override what an artifact showed; re-run it to confirm"
        if human:
            log.warnings.append({"type": "verified_claim_ended_by_report",
                                 "detail": f"{target['id']} (verified) was ended on the strength of a person's report"})
            return None
        return "a commit can only show that a change was made, not that a verified blocker is fixed"
    return None


def _converted_description(event, claim_text, target, reason):
    src = {"git_commit": "Commit", "note": "A note", "chat": "A chat message", "meeting": "A meeting note"}.get(
        event["source"], event["source"].replace("_", " ").capitalize())
    implied = claim_text[:160].rstrip(". ")  # outside the f-string: reusing quotes inside needs Python 3.12+
    return (f"{src} ({event['id']}) implies: {implied}. But {target['id']} is verified by "
            f"{', '.join(target['evidence'])}, and {reason}. Needs a test, simulation or report to settle.")


def _resolve(state, raw, evidence, event, rationale, log, events=None):
    events = events or {}
    xid = raw.get("target_contradiction_id") or raw.get("target_id")
    open_x = [x for x in state["contradictions"].values() if x["status"] == "open"]
    x = state["contradictions"].get(xid) if xid else (open_x[0] if len(open_x) == 1 else None)
    if x is None:
        raise OpRejected(f"RESOLVE: unknown contradiction {xid!r}")
    if x["status"] != "open":
        raise OpRejected(f"RESOLVE: {x['id']} is already resolved")
    # A contradiction involving verified evidence is settled by an artifact or a human decision, not by a
    # person restating a result (seen live: "the failures are fixed, all vectors pass" in chat).
    sources = {events[e]["source"] for e in evidence if e in events}
    artifact = (sources & VERIFIABLE_SOURCES) - CHANGE_ONLY_SOURCES
    involves_verified = any(state["claims"].get(cid, {}).get("verification") == "verified" for cid in x["claim_ids"])
    if involves_verified and not artifact and RESULT_RE.search(f"{event.get('text', '')} {raw.get('value') or ''} {rationale}"):
        raise OpRejected(f"RESOLVE: {x['id']} involves verified evidence; a reported result can't settle it "
                         "(needs a test, simulation or report)")
    x["status"] = "resolved"
    x["resolved_by"] = event["id"]
    x["resolved_at"] = event["occurred_at"]
    x["resolution"] = str(raw.get("value") or rationale)[:MAX_VALUE_CHARS]
    x["event_ids"] = sorted(set(x["event_ids"]) | set(evidence), key=_eid_order)
    still_open = {cid for o in state["contradictions"].values() if o["status"] == "open"
                  for cid in o["claim_ids"]}
    for cid in x["claim_ids"]:
        if cid in state["claims"] and cid not in still_open:
            state["claims"][cid]["contested"] = False
    log.applied.append({"op": "RESOLVE", "contradiction": x["id"], "resolution": x["resolution"]})


def _repair_field(state, raw, log):
    """Recover the intended field when the model names it slightly wrong.

    Seen in live runs: {"field": "timing", ...} for a status item, a missing field on an UPDATE
    that names its target, {"field": "value", "key": "hardware_test"}. Repairs are logged.
    """
    field = raw.get("field")
    key = raw.get("key")
    if field in ALL_FIELDS:
        return field, (normalize_key(key) if field in KEYED_FIELDS and key else None)
    target = state["claims"].get(raw.get("target_claim_id") or raw.get("target_id") or "")
    if target is not None:
        repaired, key = target["field"], key or target.get("key")
    elif key or (isinstance(field, str) and field.strip() and field not in ("value", "claim")):
        repaired, key = "status_items", key or field
    else:
        return field, None
    log.warnings.append({"type": "field_repaired", "detail": f"{field!r} -> {repaired}"
                         + (f"[{normalize_key(key)}]" if repaired in KEYED_FIELDS and key else "")})
    return repaired, (normalize_key(key) if repaired in KEYED_FIELDS and key else None)


DETAIL_FIELDS = {
    "decisions": ("reason", "tradeoff"),
    "attempts": ("outcome",),
    "open_questions": ("progress",),
}


def _copy_details(claim, raw, target):
    """Optional structured details: why a decision was made, its tradeoff, question progress."""
    for name in DETAIL_FIELDS.get(claim["field"], ()):
        value = raw.get(name) or (target or {}).get(name)
        if value:
            value = str(value).strip()[:MAX_VALUE_CHARS]
            if name == "progress":
                value = value.lower() if value.lower() in ("open", "investigating") else "open"
            claim[name] = value


def _close_moot_contradictions(state, event, log):
    """A contradiction whose claims have all been superseded or invalidated is moot. Seen live:
    a contradiction against an already-replaced blocker otherwise stays open forever."""
    for x in state["contradictions"].values():
        if x["status"] != "open":
            continue
        claims = [state["claims"].get(cid) for cid in x["claim_ids"]]
        if claims and all(c is not None and c["status"] != "active" for c in claims):
            enders = sorted({c["ended_by"] for c in claims if c.get("ended_by")}, key=_eid_order)
            x["status"] = "resolved"
            x["resolved_by"] = event["id"]
            x["resolved_at"] = event["occurred_at"]
            x["auto"] = True
            x["resolution"] = (f"Moot: contested claim(s) {', '.join(x['claim_ids'])} no longer current"
                               f" (ended by {', '.join(enders) or event['id']}).")
            for c in claims:
                c["contested"] = False
            log.applied.append({"op": "RESOLVE", "contradiction": x["id"], "resolution": x["resolution"],
                                "auto": True})


def _eid_order(eid):
    return int(eid[1:]) if eid[1:].isdigit() else 0


def _clean_evidence(ids, event, events, log):
    if isinstance(ids, str):
        ids = [ids]
    cleaned, unknown = [], []
    for eid in ids or []:
        eid = str(eid).strip().strip("[]")
        if eid in events:
            if eid not in cleaned:
                cleaned.append(eid)
        else:
            unknown.append(eid)
    if unknown:
        log.warnings.append({"type": "unknown_evidence_removed", "ids": unknown})
    if event["id"] not in cleaned:
        cleaned.append(event["id"])
    return sorted(cleaned, key=_eid_order)


def _verification(raw, evidence, events, log):
    verification = str(raw.get("verification", "reported")).lower()
    if verification not in ("verified", "reported", "inferred"):
        verification = "reported"
    if verification == "verified" and not any(
        events[e]["source"] in VERIFIABLE_SOURCES for e in evidence
    ):
        log.warnings.append({
            "type": "verification_downgraded",
            "detail": f"{raw.get('field')}: {str(raw.get('value'))[:80]!r} cites no verifiable artifact",
        })
        verification = "reported"
    if verification == "verified":
        verifying = {events[e]["source"] for e in evidence if events[e]["source"] in VERIFIABLE_SOURCES}
        if verifying <= CHANGE_ONLY_SOURCES and RESULT_RE.search(str(raw.get("value") or "")):
            # A commit proves that a change was recorded, not that it passes tests or works.
            log.warnings.append({
                "type": "verification_downgraded",
                "detail": f"{raw.get('field')}: {str(raw.get('value'))[:80]!r} states a result, "
                          "but a commit can only verify that a change was recorded",
            })
            verification = "reported"
    confidence = str(raw.get("confidence", "medium")).lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "medium"
    cap = CONFIDENCE_CAP[verification]
    if CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[cap]:
        confidence = cap
    return verification, confidence


def _resolve_target(state, raw, field, key, value, log=None):
    """Find the claim an operation refers to. Seen live: the model often cites an id that has
    since been superseded, or an id from a different field. A superseded id is followed to its
    current successor (the stale-evidence check still applies to that successor); an id from
    another field is ignored in favour of the field lookup. Both are logged."""
    tid = raw.get("target_claim_id") or raw.get("target_id")
    claim = state["claims"].get(tid) if tid else None
    if claim is not None:
        start = claim
        seen = set()
        while claim["status"] == "superseded" and claim.get("superseded_by") in state["claims"] and claim["id"] not in seen:
            seen.add(claim["id"])
            claim = state["claims"][claim["superseded_by"]]
        if claim["status"] != "active":
            raise OpRejected(f"target {tid} is no longer active ({start['status']})")
        if claim["field"] == field:
            if claim is not start and log is not None:
                log.warnings.append({"type": "target_followed",
                                     "detail": f"{tid} was superseded; applied to its successor {claim['id']}"})
            return claim
        if log is not None:
            log.warnings.append({"type": "target_mismatch_ignored",
                                 "detail": f"{tid} belongs to {claim['field']}, not {field}; looked up by field"})
    elif tid and log is not None:
        log.warnings.append({"type": "unknown_target_ignored", "detail": f"{tid} does not exist; looked up by field"})
    if field in SCALAR_FIELDS:
        found = active_claims(state, field)
        return found[0] if found else None
    if field in KEYED_FIELDS and key:
        for c in active_claims(state, field):
            if c["key"] == key:
                return c
        return None
    if field in LIST_FIELDS and value:
        for c in active_claims(state, field):
            if _norm(c["value"]) == _norm(value):
                return c
    return None


def _check_target(target, field, event):
    if target["field"] != field:
        raise OpRejected(f"target {target['id']} belongs to {target['field']}, not {field}")
    if event["occurred_at"] < target["as_of"]:
        raise OpRejected(
            f"stale evidence: {event['id']} occurred {event['occurred_at']}, before "
            f"{target['id']} was established ({target['as_of']})"
        )


def _new_claim(state, field, key, value, verification, confidence, evidence, event, rationale):
    cid = f"C{state['next_claim']}"
    state["next_claim"] += 1
    claim = {
        "id": cid,
        "field": field,
        "key": key,
        "value": value,
        "status": "active",
        "contested": False,
        "verification": verification,
        "confidence": confidence,
        "evidence": evidence,
        "as_of": event["occurred_at"],
        "created_by": event["id"],
        "rationale": rationale,
        "supersedes": None,
        "superseded_by": None,
        "ended_by": None,
        "ended_at": None,
        "end_reason": None,
    }
    state["claims"][cid] = claim
    return claim


def _end(claim, status, event, reason, superseded_by=None, evidence=None):
    claim["status"] = status
    claim["ended_by"] = event["id"]
    claim["ended_at"] = event["occurred_at"]
    claim["end_reason"] = reason
    claim["superseded_by"] = superseded_by
    if evidence:
        claim["end_evidence"] = evidence

"""Review-before-commit for imported artifacts (used by the Yosys import).

1. The evidence is appended (append-only, like every event).
2. Nemotron proposes operations and the validator dry-runs them. Nothing is committed: the proposal
   is stored as a transition marked AWAITING_REVIEW, so it survives restarts and shows up as pending.
3. The user sees the before/after diff, including what the validator held back, and chooses:
   - Apply: the SAME stored operations are re-validated against the CURRENT state (it may have moved
     on since the proposal) and committed atomically. The model is not called again.
   - Discard: a REJECTED_BY_USER transition is recorded. The evidence stays in the log.
History is never rewritten: every proposal, rejection and commit remains in the transitions log.
"""

from . import view as V
from .engine import StateEngine
from .llm import AWAITING_REVIEW, REJECTED_BY_USER
from .summary import change_labels, core_state


class ProposalError(ValueError):
    pass


class _Named:
    """Engine stand-in for applying a stored proposal: no model call, just the proposing model's name."""
    def __init__(self, name):
        self.name = name


def propose(store, llm, project, event):
    """Ask the model for operations and dry-run them. Returns the proposal detail (or an error)."""
    engine = StateEngine(store, llm)
    old = store.latest_state(project)
    proposed, _preview, log, latency, error = engine.propose(project, event)
    if proposed is None:  # model call failed: same handling as an ordinary failed update
        store.save_transition(project, event["id"], old["version"], old["version"], llm.name, latency,
                              None, [], [], [], error=error)
        return {"event": event, "error": error}
    store.save_transition(project, event["id"], old["version"], old["version"], llm.name, latency, proposed,
                          (log or {}).get("applied", []), (log or {}).get("rejected", []),
                          (log or {}).get("warnings", []),
                          error=f"{AWAITING_REVIEW} proposed by {llm.name}" + (f"; {error}" if error else ""))
    return detail(store, project, event["id"])


def _latest(store, project, event_id):
    return next((t for t in reversed(store.transitions(project)) if t["event_id"] == event_id), None)


def _awaiting(store, project, event_id):
    t = _latest(store, project, event_id)
    if not t or not (t["error"] or "").startswith(AWAITING_REVIEW):
        raise ProposalError(f"{event_id} has no proposed change waiting for review.")
    return t


def detail(store, project, event_id):
    """The proposal re-validated against the current state: what applying it now would change."""
    t = _awaiting(store, project, event_id)
    event = store.get_event(project, event_id)
    old = store.latest_state(project)
    events = store.events_by_id(project)
    engine = StateEngine(store, _Named(t["model"]))
    try:
        new, log = engine.validate(old, events, event, t["proposed"])
        log, error = log.as_dict(), None
    except Exception as e:  # ValidationFailure: show it; Apply will record the same failure
        new, log, error = old, {"applied": [], "rejected": [], "warnings": []}, str(e)
    before, after = core_state(old), core_state(new)
    changes = V.diff_states(old, new) if not error else []
    return {
        "event": event,
        "proposal": {"model": t["model"], "latency_ms": t["latency_ms"], "proposed_at_version": t["version_before"],
                     "current_version": old["version"], "rebased": t["version_before"] != old["version"],
                     "error": error},
        # same shape as summary.transition_detail so the UI's diff component renders it
        "transition": {"version_before": old["version"], "version_after": old["version"] + (1 if not error else 0),
                       "model": t["model"], "latency_ms": t["latency_ms"], "applied": log["applied"],
                       "rejected": log["rejected"], "warnings": log["warnings"], "error": error},
        "before": before, "after": after, "changes": changes,
        "labels": change_labels(before, after, changes) if not error else [],
    }


def pending(store, project):
    out = []
    for e in store.pending_events(project):
        if (e["last_error"] or "").startswith(AWAITING_REVIEW):
            out.append(detail(store, project, e["id"]))
    return out


def apply(store, project, event_id):
    t = _awaiting(store, project, event_id)
    event = store.get_event(project, event_id)
    old = store.latest_state(project)
    r = StateEngine(store, _Named(t["model"])).validate_and_commit(
        project, event, old, store.events_by_id(project), t["proposed"], t["latency_ms"])
    return {"event_id": event_id, "applied": not r.error, "error": r.error,
            "version": r.state["version"], "log": r.log}


def discard(store, project, event_id, reason=""):
    t = _awaiting(store, project, event_id)
    v = store.latest_state(project)["version"]
    note = f"{REJECTED_BY_USER}" + (f": {reason.strip()[:200]}" if reason and reason.strip() else "")
    store.save_transition(project, event_id, v, v, t["model"], 0, t["proposed"], [], [], [], error=note)
    return {"event_id": event_id, "discarded": True}

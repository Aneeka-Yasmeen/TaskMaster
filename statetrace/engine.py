import time

from .llm import LLMError
from .prompts import ENGINE_SYSTEM, engine_user_prompt
from .validator import apply_operations

RECENT_CONTEXT = 6


class ValidationFailure(RuntimeError):
    pass


class TransitionResult:
    def __init__(self, event, state, log, latency_ms, error=None, proposed=None):
        self.event = event
        self.state = state
        self.log = log
        self.latency_ms = latency_ms
        self.error = error
        self.proposed = proposed

    def summary_lines(self):
        if self.error:
            return [f"  ! model call failed, evidence stored, state unchanged: {self.error}"]
        lines = []
        for a in self.log["applied"]:
            op = a["op"]
            if op == "NOOP":
                lines.append(f"  = no change ({a.get('rationale') or 'nothing new'})")
            elif op in ("ADD", "UPDATE"):
                key = f"[{a['key']}] " if a.get("key") else ""
                sup = f" (supersedes {a['supersedes']})" if a.get("supersedes") else ""
                sym = "+" if op == "ADD" else "~"
                lines.append(f"  {sym} {a['claim']} {a['field']} {key}= {a['value'][:90]!r}"
                             f" ({a['verification']}){sup}")
            elif op == "INVALIDATE":
                lines.append(f"  x {a['claim']} {a['field']} no longer current: {a['reason'][:80]}")
            elif op == "CONTRADICT":
                lines.append(f"  ! {a['contradiction']} contradiction on {a['claim']}: {a['description'][:90]}")
            elif op == "RESOLVE":
                lines.append(f"  v {a['contradiction']} resolved: {a['resolution'][:90]}")
            elif op == "REINFORCE":
                lines.append(f"  + {a['claim']} gains evidence {', '.join(a['evidence'])}")
        for r in self.log["rejected"]:
            lines.append(f"  - rejected {r['op'].get('op') if isinstance(r['op'], dict) else r['op']}:"
                         f" {r['reason']}")
        for w in self.log["warnings"]:
            lines.append(f"  ? {w['type']}: {w.get('detail') or w.get('ids')}")
        return lines


class StateEngine:
    def __init__(self, store, llm):
        self.store = store
        self.llm = llm

    def ingest(self, project, text, source="note", event_type=None, occurred_at=None, ref=None):
        event = self.store.append_event(project, text, source, event_type, occurred_at, ref)
        return self.process(project, event)

    def process(self, project, event):
        old = self.store.latest_state(project)
        events = self.store.events_by_id(project)
        prior = [e for e in events.values() if e["seq"] < event["seq"]][-RECENT_CONTEXT:]
        prompt = engine_user_prompt(old, prior, event)
        start = time.perf_counter()
        try:
            proposed, _raw = self.llm.chat_json(ENGINE_SYSTEM, prompt)
        except LLMError as e:
            latency = int((time.perf_counter() - start) * 1000)
            self.store.save_transition(project, event["id"], old["version"], old["version"],
                                       self.llm.name, latency, None, [], [], [], error=str(e))
            return TransitionResult(event, old, {"applied": [], "rejected": [], "warnings": []},
                                    latency, error=str(e))
        latency = int((time.perf_counter() - start) * 1000)
        return self.validate_and_commit(project, event, old, events, proposed, latency)

    def validate(self, old, events, event, proposed):
        """Deterministic: apply proposed operations to a COPY of the state. Saves nothing.
        Raises ValidationFailure on any unexpected error (the state is never partially changed)."""
        ops = proposed.get("operations", []) if isinstance(proposed, dict) else []
        try:
            return apply_operations(old, ops, event, events)
        except Exception as e:  # malformed output the validator didn't anticipate
            raise ValidationFailure(f"[validator] could not apply the model's proposal: {type(e).__name__}: {e}"[:300])

    def validate_and_commit(self, project, event, old, events, proposed, latency):
        try:
            new, log = self.validate(old, events, event, proposed)
        except ValidationFailure as e:
            # recorded, NOT retried automatically (retrying the same output would fail the same way)
            self.store.save_transition(project, event["id"], old["version"], old["version"], self.llm.name,
                                       latency, proposed, [], [], [], error=str(e))
            return TransitionResult(event, old, {"applied": [], "rejected": [], "warnings": []}, latency,
                                    error=str(e), proposed=proposed)
        self.store.commit_transition(new, project, event["id"], old["version"], self.llm.name, latency,
                                     proposed, log.applied, log.rejected, log.warnings)
        return TransitionResult(event, new, log.as_dict(), latency, proposed=proposed)

    def propose(self, project, event):
        """Model proposal + deterministic validation WITHOUT saving: for review-before-commit flows.
        Returns (proposed, new_state_preview, log, latency_ms, error)."""
        old = self.store.latest_state(project)
        events = self.store.events_by_id(project)
        prior = [e for e in events.values() if e["seq"] < event["seq"]][-RECENT_CONTEXT:]
        start = time.perf_counter()
        try:
            proposed, _raw = self.llm.chat_json(ENGINE_SYSTEM, engine_user_prompt(old, prior, event))
        except LLMError as e:
            return None, old, None, int((time.perf_counter() - start) * 1000), str(e)
        latency = int((time.perf_counter() - start) * 1000)
        try:
            new, log = self.validate(old, events, event, proposed)
        except ValidationFailure as e:
            return proposed, old, None, latency, str(e)
        return proposed, new, log.as_dict(), latency, None

    def process_pending(self, project):
        """Manual retry: everything not applied, except changes awaiting review or rejected by the user."""
        from .llm import AWAITING_REVIEW, REJECTED_BY_USER
        todo = [e for e in self.store.pending_events(project)
                if not (e["last_error"] or "").startswith((AWAITING_REVIEW, REJECTED_BY_USER))]
        return [self.process(project, e) for e in todo]

    def rebuild(self, project):
        """Replay the whole event log into a fresh state (event log is the source of truth)."""
        self.store.clear_derived(project)
        return [self.process(project, e) for e in self.store.events(project)]

import json
import time

from .llm import LLMError
from .prompts import BASELINE_SYSTEM
from .schema import KEYED_FIELDS, LIST_FIELDS, SCALAR_FIELDS


class BaselineEngine:
    def __init__(self, llm, project):
        self.llm = llm
        self.project = project
        self.state = {f: None for f in SCALAR_FIELDS}
        self.state.update({f: [] for f in LIST_FIELDS + KEYED_FIELDS})
        self.state["contradictions"] = []
        self.last_updated = None
        self.latencies = []

    def process(self, event):
        user = (f"CURRENT STATE\n{json.dumps(self.state, indent=1)}\n\nNEW EVIDENCE\nid: {event['id']}\n"
                f"occurred_at: {event['occurred_at']}\nsource: {event['source']}\ntext: {event['text']}\n\n"
                "Return the full updated state JSON.")
        start = time.perf_counter()
        try:
            new, _raw = self.llm.chat_json(BASELINE_SYSTEM, user)
        except LLMError as e:
            self.latencies.append(int((time.perf_counter() - start) * 1000))
            return str(e)
        self.latencies.append(int((time.perf_counter() - start) * 1000))
        if isinstance(new, dict):
            for k in list(self.state):
                if k in new:
                    self.state[k] = new[k]
        if not self.last_updated or event["occurred_at"] > self.last_updated:
            self.last_updated = event["occurred_at"]
        return None

    def view(self):
        """Convert the free-form state into the same read model the checks use."""
        fields = {f: [] for f in SCALAR_FIELDS + LIST_FIELDS + KEYED_FIELDS}
        n = 0

        def claim(field, item, key=None):
            nonlocal n
            n += 1
            if isinstance(item, str):
                item = {"value": item}
            if not isinstance(item, dict) or not item.get("value"):
                return None
            ev = item.get("evidence") or []
            ev = [str(e) for e in (ev if isinstance(ev, list) else [ev])]
            return {"id": f"B{n}", "field": field, "key": key or item.get("key"),
                    "value": str(item["value"]), "verification": item.get("verification", "reported"),
                    "confidence": "medium", "evidence": ev, "as_of": self.last_updated or "",
                    "status": "active", "contested": False}

        for f in SCALAR_FIELDS:
            c = claim(f, self.state.get(f))
            if c:
                fields[f].append(c)
        for f in LIST_FIELDS + KEYED_FIELDS:
            items = self.state.get(f) or []
            for item in items if isinstance(items, list) else []:
                c = claim(f, item)
                if c:
                    fields[f].append(c)
        xs = []
        for i, x in enumerate(self.state.get("contradictions") or []):
            if isinstance(x, dict):
                xs.append({"id": f"BX{i + 1}", "description": str(x.get("description", "")),
                           "event_ids": [str(e) for e in x.get("event_ids") or []],
                           "status": x.get("status", "open"), "claim_ids": []})
        return {"project": self.project, "version": None, "fields": fields, "contradictions": xs,
                "last_updated": self.last_updated, "ended": []}

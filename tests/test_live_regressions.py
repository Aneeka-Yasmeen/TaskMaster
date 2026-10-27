import json
import os
import unittest

from statetrace.evaluation import run_scenario
from statetrace.llm import ScriptedLLM
from statetrace.schema import empty_state
from statetrace.validator import apply_operations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


class ReplayLiveRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = load("demo/fft_scenario.json")
        cls.replay = run_scenario(cls.scenario, ScriptedLLM(load("tests/fixtures/live_run_nemotron.json")))
        cls.trace = {t["event"]: t for t in cls.replay["trace"]}

    def results(self, after, category=None):
        return [r for r in self.replay["results"] if r["after"] == after and (category is None or r["category"] == category)]

    def test_invalid_field_names_are_repaired_not_rejected(self):
        # live: E10 used "field": "timing", E14 used "field": "value"; both were rejected originally
        for eid in ("E10", "E14"):
            self.assertIn("field_repaired", self.trace[eid]["warnings"], eid)
            self.assertFalse(any("unknown field" in r for r in self.trace[eid]["rejected"]), eid)

    def test_operation_without_any_field_is_still_rejected(self):
        # live: E7 proposed an ADD with no field, key or target; intent can't be recovered safely
        self.assertTrue(any("unknown field None" in r for r in self.trace["E7"]["rejected"]))

    def test_duplicate_contradictions_from_one_event_are_merged(self):
        # live: E11 contradicted two claims and produced two contradictions
        self.assertEqual(self.trace["E11"]["applied"].count("CONTRADICT"), 2)
        r = self.results("E12", "contradiction")[0]
        self.assertTrue(r["passed"], r["detail"])
        self.assertEqual(r["detail"].count("'X"), 1, "E11 should map to exactly one contradiction")

    def test_contradiction_on_replaced_claim_closes_as_moot(self):
        # live: E7 contradicted blocker C4; E8 replaced C4; the contradiction stayed open forever
        self.assertIn("RESOLVE", self.trace["E8"]["applied"])

    def test_stale_blocker_is_caught_by_the_evaluator(self):
        # live: the model never cleared the bit-reversal blocker after the E4 architecture change.
        # The validator cannot fix a missing operation; the evaluation must report it.
        stale = [r for r in self.results("E6", "staleness") if r["check"].get("field") == "current_blocker"]
        self.assertTrue(stale and not stale[0]["passed"])
        self.assertIn("Bit-reversed", stale[0]["detail"])

    def test_superseded_target_ids_are_followed(self):
        # live: E15 updated timing via an id (C16) that had been superseded; the update was lost
        self.assertIn("target_followed", self.trace["E15"]["warnings"])
        timing = [r for r in self.results("E16", "accuracy") if r["check"].get("match") == ["timing", "wns"]]
        self.assertTrue(timing and timing[0]["passed"], timing and timing[0]["detail"])


class TargetResolution(unittest.TestCase):
    def setUp(self):
        self.events = {f"E{i}": {"id": f"E{i}", "occurred_at": f"2026-01-0{i}T10:00:00", "source": "sim_log", "text": "x"}
                       for i in range(1, 5)}
        self.state = empty_state("p")

    def apply(self, eid, ops):
        self.state, log = apply_operations(self.state, ops, self.events[eid], self.events)
        return log

    def test_follow_superseded_chain_respects_staleness(self):
        self.apply("E2", [{"op": "ADD", "field": "status_items", "key": "timing", "value": "WNS -0.8"}])
        self.apply("E3", [{"op": "UPDATE", "field": "status_items", "key": "timing", "value": "WNS -0.1"}])
        # E1 is older than C2: following C1 -> C2 must still be rejected as stale
        log = self.apply("E1", [{"op": "UPDATE", "target_claim_id": "C1", "field": "status_items", "value": "WNS -2"}])
        self.assertIn("stale", log.rejected[0]["reason"])

    def test_mismatched_target_falls_back_to_field(self):
        self.apply("E1", [{"op": "ADD", "field": "status_items", "key": "timing", "value": "WNS -0.8"},
                          {"op": "ADD", "field": "next_step", "value": "pipeline"}])
        log = self.apply("E2", [{"op": "UPDATE", "target_claim_id": "C1", "field": "next_step", "value": "use DSP48"}])
        active = {c["field"]: c["value"] for c in self.state["claims"].values() if c["status"] == "active"}
        self.assertEqual(active["next_step"], "use DSP48")
        self.assertEqual(active["status_items"], "WNS -0.8")
        self.assertEqual(log.warnings[0]["type"], "target_mismatch_ignored")

    def test_late_arriving_evidence_cannot_open_a_contradiction(self):
        # eval run 1 (Oct 9): the late E12 note "contradicted" the newer passing sim log and stayed open
        self.apply("E3", [{"op": "ADD", "field": "status_items", "key": "axi", "value": "12/12 pass"}])
        log = self.apply("E2", [{"op": "CONTRADICT", "field": "status_items", "key": "axi", "value": "still dropping"}])
        self.assertEqual(self.state["contradictions"], {})
        self.assertIn("predates", log.rejected[0]["reason"])

    def test_invalidated_target_is_not_resurrected(self):
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "AXI"}])
        self.apply("E2", [{"op": "INVALIDATE", "field": "current_blocker"}])
        log = self.apply("E3", [{"op": "UPDATE", "target_claim_id": "C1", "field": "current_blocker", "value": "AXI again"}])
        self.assertIn("no longer active", log.rejected[0]["reason"])


if __name__ == "__main__":
    unittest.main()

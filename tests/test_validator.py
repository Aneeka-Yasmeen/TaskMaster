import json
import os
import sqlite3
import tempfile
import unittest

from statetrace.engine import StateEngine
from statetrace.evaluation import run_scenario
from statetrace.llm import ScriptedLLM, extract_json
from statetrace.schema import empty_state
from statetrace.store import Store
from statetrace.validator import apply_operations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ev(eid, ts, source="note"):
    return {"id": eid, "occurred_at": ts, "source": source, "text": "x"}


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.events = {
            "E1": ev("E1", "2026-01-01T10:00:00", "sim_log"),
            "E2": ev("E2", "2026-01-02T10:00:00", "note"),
            "E3": ev("E3", "2026-01-03T10:00:00", "sim_log"),
            "E4": ev("E4", "2026-01-01T12:00:00", "note"),  # late-arriving
        }
        self.state = empty_state("p")

    def apply(self, eid, ops):
        self.state, log = apply_operations(self.state, ops, self.events[eid], self.events)
        return log

    def active(self, field):
        return [c for c in self.state["claims"].values() if c["status"] == "active" and c["field"] == field]

    def test_add_then_add_supersedes_scalar(self):
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "AXI fails", "verification": "verified", "evidence_ids": ["E1"]}])
        self.apply("E3", [{"op": "ADD", "field": "current_blocker", "value": "timing fails", "verification": "verified", "evidence_ids": ["E3"]}])
        active = self.active("current_blocker")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["value"], "timing fails")
        self.assertEqual(self.state["claims"]["C1"]["status"], "superseded")
        self.assertEqual(self.state["claims"]["C1"]["superseded_by"], "C2")

    def test_note_cannot_verify(self):
        log = self.apply("E2", [{"op": "ADD", "field": "status_items", "key": "hardware", "value": "works",
                                 "verification": "verified", "confidence": "high", "evidence_ids": ["E2"]}])
        c = self.active("status_items")[0]
        self.assertEqual(c["verification"], "reported")
        self.assertEqual(c["confidence"], "medium")
        self.assertEqual(log.warnings[0]["type"], "verification_downgraded")

    def test_commit_cannot_verify_a_result(self):
        self.events["E5"] = ev("E5", "2026-01-04T10:00:00", "git_commit")
        log = self.apply("E5", [
            {"op": "ADD", "field": "last_action", "value": "fix col counter wrap (commit e4b18a0)", "verification": "verified"},
            {"op": "ADD", "field": "status_items", "key": "sim", "value": "all 14/14 tests pass", "verification": "verified"}])
        by_field = {c["field"]: c["verification"] for c in self.state["claims"].values()}
        self.assertEqual(by_field, {"last_action": "verified", "status_items": "reported"})
        self.assertIn("commit can only verify", log.warnings[0]["detail"])

    def test_result_verified_when_a_test_artifact_is_cited_with_the_commit(self):
        self.events["E5"] = ev("E5", "2026-01-04T10:00:00", "git_commit")
        self.apply("E5", [{"op": "ADD", "field": "status_items", "key": "sim", "value": "14/14 pass",
                           "verification": "verified", "evidence_ids": ["E1", "E5"]}])
        self.assertEqual(self.active("status_items")[0]["verification"], "verified")

    def test_commit_cannot_clear_a_verified_blocker(self):
        # seen live (Oct 9): a commit saying "all 14/14 tests pass" cleared a test-verified blocker
        self.events["E5"] = ev("E5", "2026-01-04T10:00:00", "git_commit")
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "stride-2 tests fail", "verification": "verified"}])
        log = self.apply("E5", [{"op": "INVALIDATE", "field": "current_blocker", "rationale": "commit says 14/14 pass"}])
        self.assertEqual(self.active("current_blocker")[0]["value"], "stride-2 tests fail")
        x = self.state["contradictions"]["X1"]
        self.assertEqual((x["status"], x["opened_by"]), ("open", "E5"))
        self.assertTrue(log.applied[0]["converted"])

    def test_report_cannot_overwrite_a_verified_result_but_artifact_can(self):
        self.apply("E1", [{"op": "ADD", "field": "status_items", "key": "timing", "value": "WNS -0.118 ns", "verification": "verified"}])
        self.apply("E2", [{"op": "UPDATE", "field": "status_items", "key": "timing", "value": "timing met"}])  # note
        self.assertEqual(self.active("status_items")[0]["value"], "WNS -0.118 ns")
        self.assertIn("X1", self.state["contradictions"])
        self.apply("E3", [{"op": "UPDATE", "field": "status_items", "key": "timing", "value": "WNS +0.061 ns",
                           "verification": "verified"}])  # sim_log artifact
        self.assertEqual(self.active("status_items")[0]["value"], "WNS +0.061 ns")
        self.assertEqual(self.state["contradictions"]["X1"]["status"], "resolved")  # moot: contested claim replaced

    def test_person_may_clear_a_verified_blocker_but_it_is_flagged(self):
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "radix-2 sim fails", "verification": "verified"}])
        log = self.apply("E2", [{"op": "INVALIDATE", "field": "current_blocker", "rationale": "design abandoned"}])
        self.assertEqual(self.active("current_blocker"), [])
        self.assertEqual(log.warnings[0]["type"], "verified_claim_ended_by_report")

    def test_reported_result_cannot_clear_a_verified_failing_blocker(self):
        # seen live (mac-unit E8/E9): a failing sim log, then "fixed, all 256 vectors pass" in chat
        self.events["E2"]["source"] = "chat"
        self.events["E2"]["text"] = "Sam: the v2 failures are fixed, all 256 vectors pass now."
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "tb_mac: 6/256 vectors fail", "verification": "verified"}])
        log = self.apply("E2", [{"op": "INVALIDATE", "field": "current_blocker", "rationale": "fixed per chat"}])
        self.assertEqual(self.active("current_blocker")[0]["value"], "tb_mac: 6/256 vectors fail")
        self.assertTrue(log.applied[0]["converted"])
        self.assertEqual(self.state["contradictions"]["X1"]["status"], "open")

    def test_reported_result_cannot_resolve_a_contradiction_with_verified_evidence(self):
        self.apply("E1", [{"op": "ADD", "field": "status_items", "key": "sim", "value": "tb passes", "verification": "verified"}])
        self.apply("E3", [{"op": "CONTRADICT", "field": "status_items", "key": "sim", "value": "tb now fails 6 vectors"}])
        self.events["E4"].update(occurred_at="2026-01-04T10:00:00", text="all vectors pass again, trust me")
        log = self.apply("E4", [{"op": "RESOLVE", "target_contradiction_id": "X1", "value": "fixed"}])
        self.assertEqual(self.state["contradictions"]["X1"]["status"], "open")
        self.assertIn("reported result", log.rejected[0]["reason"])
        self.apply("E3", [{"op": "RESOLVE", "target_contradiction_id": "X1", "value": "sim log settles it"}])  # artifact may
        self.assertEqual(self.state["contradictions"]["X1"]["status"], "resolved")

    def test_unknown_evidence_stripped_and_trigger_cited(self):
        log = self.apply("E3", [{"op": "ADD", "field": "goal", "value": "g", "evidence_ids": ["E99"]}])
        self.assertEqual(self.active("goal")[0]["evidence"], ["E3"])
        self.assertEqual(log.warnings[0]["ids"], ["E99"])

    def test_stale_evidence_cannot_supersede(self):
        self.apply("E3", [{"op": "ADD", "field": "current_blocker", "value": "timing", "evidence_ids": ["E3"]}])
        log = self.apply("E4", [{"op": "UPDATE", "field": "current_blocker", "value": "AXI fails", "evidence_ids": ["E4"]}])
        self.assertEqual(self.active("current_blocker")[0]["value"], "timing")
        self.assertIn("stale", log.rejected[0]["reason"])

    def test_invalidate_clears_blocker(self):
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "AXI fails", "evidence_ids": ["E1"]}])
        self.apply("E3", [{"op": "INVALIDATE", "field": "current_blocker", "evidence_ids": ["E3"], "rationale": "passes now"}])
        self.assertEqual(self.active("current_blocker"), [])
        self.assertEqual(self.state["claims"]["C1"]["status"], "invalidated")
        self.assertEqual(self.state["claims"]["C1"]["ended_by"], "E3")

    def test_contradiction_then_resolve(self):
        self.apply("E1", [{"op": "ADD", "field": "status_items", "key": "timing", "value": "WNS -0.1", "verification": "verified", "evidence_ids": ["E1"]}])
        self.apply("E2", [{"op": "CONTRADICT", "field": "status_items", "key": "timing", "value": "note says met", "evidence_ids": ["E2"]}])
        x = self.state["contradictions"]["X1"]
        self.assertEqual(x["status"], "open")
        self.assertEqual(x["event_ids"], ["E1", "E2"])
        self.assertTrue(self.state["claims"]["C1"]["contested"])
        self.apply("E3", [{"op": "RESOLVE", "target_contradiction_id": "X1", "value": "met per report", "evidence_ids": ["E3"]}])
        self.assertEqual(self.state["contradictions"]["X1"]["status"], "resolved")
        self.assertFalse(self.state["claims"]["C1"]["contested"])

    def test_list_duplicates_reinforce(self):
        self.apply("E1", [{"op": "ADD", "field": "attempts", "value": "Pipelined the multiplier", "evidence_ids": ["E1"]}])
        log = self.apply("E3", [{"op": "ADD", "field": "attempts", "value": "pipelined the multiplier.", "evidence_ids": ["E3"]}])
        self.assertEqual(len(self.active("attempts")), 1)
        self.assertEqual(self.active("attempts")[0]["evidence"], ["E1", "E3"])
        self.assertEqual(log.applied[0]["op"], "REINFORCE")

    def test_garbage_ops_rejected(self):
        log = self.apply("E1", [{"op": "DELETE"}, "nonsense", {"op": "ADD", "value": "x"}])
        self.assertEqual(len(log.rejected), 3)
        self.assertEqual(self.state["claims"], {})

    def test_field_slips_are_repaired(self):
        # seen live: a status subject used as the field name, and field "value" with a key
        log = self.apply("E1", [{"op": "ADD", "field": "timing", "value": "WNS -0.1", "verification": "verified"},
                                {"op": "ADD", "field": "value", "key": "hardware_test", "value": "works"}])
        keys = sorted(c["key"] for c in self.active("status_items"))
        self.assertEqual(keys, ["hardware_test", "timing"])
        self.assertEqual([w["type"] for w in log.warnings], ["field_repaired", "field_repaired"])
        # missing field on an UPDATE that names its target
        self.apply("E3", [{"op": "UPDATE", "target_claim_id": "C1", "value": "WNS +0.05", "verification": "verified"}])
        timing = [c for c in self.active("status_items") if c["key"] == "timing"][0]
        self.assertEqual(timing["value"], "WNS +0.05")

    def test_moot_contradiction_closes_when_claim_ends(self):
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "AXI fails", "verification": "verified"}])
        self.apply("E2", [{"op": "CONTRADICT", "field": "current_blocker", "value": "note says fixed"}])
        self.assertEqual(self.state["contradictions"]["X1"]["status"], "open")
        log = self.apply("E3", [{"op": "UPDATE", "field": "current_blocker", "value": "timing fails"}])
        x = self.state["contradictions"]["X1"]
        self.assertEqual((x["status"], x["auto"]), ("resolved", True))
        self.assertTrue(any(a.get("auto") for a in log.applied))

    def test_one_event_against_two_claims_is_one_contradiction(self):
        self.apply("E1", [{"op": "ADD", "field": "current_blocker", "value": "timing fails"},
                          {"op": "ADD", "field": "current_status", "value": "timing not met"}])
        self.apply("E2", [{"op": "CONTRADICT", "field": "current_blocker", "value": "note says met"},
                          {"op": "CONTRADICT", "field": "current_status", "value": "note says met"}])
        self.assertEqual(list(self.state["contradictions"]), ["X1"])
        self.assertEqual(self.state["contradictions"]["X1"]["claim_ids"], ["C1", "C2"])

    def test_decision_details_and_question_progress(self):
        self.apply("E2", [{"op": "ADD", "field": "decisions", "value": "use DSP48", "reason": "frees LUTs",
                           "tradeoff": "more DSPs"},
                          {"op": "ADD", "field": "open_questions", "value": "retime?", "progress": "Investigating"}])
        d = self.active("decisions")[0]
        q = self.active("open_questions")[0]
        self.assertEqual((d["reason"], d["tradeoff"], q["progress"]), ("frees LUTs", "more DSPs", "investigating"))

    def test_extract_json(self):
        self.assertEqual(extract_json('<think>{"no"}</think>```json\n{"a": {"b": "}"}}\n```'), {"a": {"b": "}"}})


class StoreTests(unittest.TestCase):
    def test_events_append_only(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "t.db"))
            store.append_event("p", "hello")
            with self.assertRaises(sqlite3.DatabaseError):
                store.conn.execute("UPDATE events SET text = 'changed'")
            with self.assertRaises(sqlite3.DatabaseError):
                store.conn.execute("DELETE FROM events")
            store.close()


class PipelineTests(unittest.TestCase):
    def test_scripted_scenario_passes_all_checks(self):
        """Validates the scenario checks and the pipeline with hand-written ops (not a model score)."""
        with open(os.path.join(ROOT, "demo", "fft_scenario.json"), encoding="utf-8") as fh:
            scenario = json.load(fh)
        llm = ScriptedLLM.from_file(os.path.join(ROOT, "demo", "scripted_ops.json"))
        r = run_scenario(scenario, llm)
        failed = [x for x in r["results"] if not x["passed"]]
        self.assertEqual(failed, [])
        self.assertEqual(r["counters"]["stale_ops_rejected"], 2)
        self.assertEqual(r["counters"]["verification_downgrades"], 1)
        self.assertEqual(r["counters"]["max_unsupported_verified"], 0)

    def test_rebuild_reproduces_state(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "t.db"))
            llm = ScriptedLLM.from_file(os.path.join(ROOT, "demo", "scripted_ops.json"))
            engine = StateEngine(store, llm)
            with open(os.path.join(ROOT, "demo", "fft_scenario.json"), encoding="utf-8") as fh:
                for e in json.load(fh)["events"]:
                    engine.ingest("fft-accel", e["text"], e["source"], None, e["occurred_at"])
            before = store.latest_state("fft-accel")
            engine.rebuild("fft-accel")
            self.assertEqual(store.latest_state("fft-accel"), before)
            store.close()


if __name__ == "__main__":
    unittest.main()

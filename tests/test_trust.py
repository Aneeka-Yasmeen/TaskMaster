import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

from statetrace import assistant, proposals
from statetrace.api import Api, ApiError
from statetrace.llm import AWAITING_REVIEW, REJECTED_BY_USER, LLMError, ModelUnavailable, OFFLINE_MARK
from statetrace.store import Store

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "yosys")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


class FakeLLM:
    """chat_json -> the next queued operations list; chat -> self.reply (catch-up JSON or text)."""
    name = "fake-nemotron"

    def __init__(self):
        self.ops = []
        self.reply = "{}"
        self.online = True
        self.calls = 0

    def chat_json(self, system, user):
        self.calls += 1
        if not self.online:
            raise ModelUnavailable(f"{OFFLINE_MARK} cannot reach fake")
        ops = self.ops.pop(0) if self.ops else [{"op": "NOOP", "rationale": "nothing"}]
        if isinstance(ops, Exception):
            raise ops
        return {"operations": ops}, json.dumps(ops)

    def chat(self, system, user, json_mode=False, max_tokens=0):
        self.calls += 1
        if not self.online:
            raise ModelUnavailable(f"{OFFLINE_MARK} cannot reach fake")
        return self.reply


def op(opname, field, value=None, ev="E1", verification="reported", **kw):
    d = {"op": opname, "field": field, "verification": verification, "confidence": "medium",
         "evidence_ids": [ev], "rationale": "test"}
    if value is not None:
        d["value"] = value
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "t.db")
        self.llm = FakeLLM()
        self.api = Api(self.db, llm=self.llm, mode="live")
        self.api.create_project("Alpha")
        # E1 note: goal + reported status; E2 sim log: verified result; E3 note: next step
        self.llm.ops = [
            [op("ADD", "goal", "MAC unit at 100 MHz"), op("ADD", "status_items", "sim passes (I think)", key="sim")],
            [op("UPDATE", "status_items", "sim: 64/64 vectors pass", ev="E2", verification="verified", key="sim",
                target_claim_id="C2"),
             op("ADD", "last_action", "Ran the testbench", ev="E2", verification="verified")],
            [op("ADD", "next_step", "Synthesize with Yosys and compare cell count", ev="E3")],
        ]
        self.api.add_event("alpha", "Goal: MAC at 100 MHz. Sim seems to pass.", "note")
        self.api.add_event("alpha", "tb_mac: 64/64 vectors PASS", "sim_log")
        self.api.add_event("alpha", "Next: run Yosys synth and compare cells.", "note")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def state(self, project="alpha"):
        s = Store(self.db)
        try:
            return s.latest_state(project)
        finally:
            s.close()


class CatchUpTests(Base):
    def run_catchup(self, reply, **kw):
        self.llm.reply = json.dumps(reply) if not isinstance(reply, str) else reply
        return self.api.catch_up("alpha", run=True, **kw)

    def test_support_comes_from_claims_not_from_the_model(self):
        sim = next(c for c in self.state()["claims"].values() if c["key"] == "sim" and c["status"] == "active")
        out = self.run_catchup({
            "headline": "Sim verified; synthesis next.",
            "established": [{"text": "Simulation passes", "claims": [sim["id"]], "verification": "reported"}],
            "next_action": {"text": "Run Yosys", "claims": ["C5"]},
        })
        self.assertEqual(out["source"], "nemotron")
        self.assertEqual(out["established"][0]["basis"], "verified")    # derived, model's label ignored
        self.assertEqual(out["established"][0]["evidence"], ["E2"])     # evidence attached by TaskMaster

    def test_unsupported_items_are_labelled_inference(self):
        out = self.run_catchup({"left_off": [{"text": "You were probably debugging timing", "claims": []}]})
        self.assertEqual(out["left_off"][0]["basis"], "inference")
        self.assertEqual(out["left_off"][0]["evidence"], [])

    def test_invented_and_superseded_claim_refs_are_dropped_and_reported(self):
        out = self.run_catchup({"left_off": [{"text": "Sim might pass", "claims": ["C2", "C99"]}]})
        item = out["left_off"][0]
        self.assertEqual(item["claims"], [])                 # C2 was superseded by the verified result
        self.assertEqual(item["basis"], "inference")
        notes = " ".join(out["validator_notes"])
        self.assertIn("C99 does not exist", notes)
        self.assertIn("C2 is superseded", notes)

    def test_unverified_items_cannot_sit_in_established(self):
        out = self.run_catchup({"established": [{"text": "Goal set", "claims": ["C1"]}]})  # goal is only reported
        self.assertEqual(out["established"], [])
        self.assertEqual(out["uncertain"][0]["basis"], "reported")

    def test_no_next_action_is_said_plainly(self):
        out = self.run_catchup({"next_action": None, "no_next_action_reason": ""})
        self.assertIsNone(out["next_action"])
        self.assertTrue(out["no_next_action_reason"])

    def test_malformed_output_falls_back_to_labelled_stored_state(self):
        out = self.run_catchup("I think you should probably keep going!")
        self.assertEqual(out["source"], "stored")
        self.assertIn("stored state", out["mode"])
        self.assertIn("model_error", out)
        self.assertIsNotNone(out["next_action"])             # deterministic, from the next_step claim
        self.assertEqual(out["next_action"]["evidence"], ["E3"])

    def test_offline_never_looks_like_a_model_answer(self):
        self.llm.online = False
        out = self.api.catch_up("alpha", run=True)
        self.assertEqual(out["source"], "stored")
        self.assertNotIn("Nemotron ·", out["mode"])

    def test_cached_per_version_and_get_never_calls_the_model(self):
        self.run_catchup({"headline": "x"})
        calls = self.llm.calls
        self.assertTrue(self.api.catch_up("alpha")["cached"])     # GET returns the saved one
        self.assertEqual(self.llm.calls, calls)
        self.llm.ops = [[op("ADD", "open_questions", "Is 100 MHz needed?", ev="E4")]]
        self.api.add_event("alpha", "Is 100 MHz really needed?", "note")
        fresh = self.api.catch_up("alpha")                         # new version: deterministic, no model call
        self.assertEqual(fresh["source"], "stored")
        self.assertEqual(self.llm.calls, calls + 1)               # only the engine call for E4

    def test_catch_up_does_not_change_state(self):
        v = self.state()["version"]
        self.run_catchup({"headline": "x", "next_action": {"text": "Delete everything", "claims": []}})
        self.assertEqual(self.state()["version"], v)

    def test_open_contradictions_are_surfaced(self):
        self.llm.ops = [[op("UPDATE", "status_items", "sim fails on overflow vector", ev="E4", key="sim",
                            target_claim_id="C3")]]
        self.api.add_event("alpha", "Bob says sim fails on the overflow vector", "chat")
        out = self.api.catch_up("alpha")
        self.assertTrue(out["contradictions"])                     # weaker evidence vs verified: contradiction


class GroundingTests(Base):
    """A displayed fact must be a claim's stored text; the model's sentence never carries a badge."""

    def claim(self, field, key=None):
        return next(c for c in self.state()["claims"].values()
                    if c["field"] == field and c["status"] == "active" and (key is None or c["key"] == key))

    def run_catchup(self, reply):
        self.llm.reply = json.dumps(reply)
        return self.api.catch_up("alpha", run=True, force=True)

    def assert_no_unsupported_badge(self, out):
        """Every item with a support badge shows exactly the stored text of the claims it references."""
        claims = self.state()["claims"]
        items = [i for k in ("left_off", "established", "blockers", "uncertain") for i in out[k]]
        items += [out["next_action"]] if out["next_action"] else []
        for i in items:
            if i["basis"] in ("verified", "reported", "contested", "inferred"):
                self.assertTrue(i["claims"], i)
                expected = " · ".join(assistant._claim_text(claims[c]) for c in i["claims"])
                self.assertEqual(i["text"], expected)
            else:
                self.assertIn(i["basis"], ("inference", "suggestion"))
                self.assertEqual(i["evidence"], [])

    def test_exaggerated_sentence_is_replaced_by_the_claim(self):
        sim = self.claim("status_items", "sim")
        out = self.run_catchup({"established": [{"text": "Simulation passes all 128 vectors and timing is closed",
                                                 "claims": [sim["id"]]}]})
        item = out["established"][0]
        self.assertEqual(item["basis"], "verified")
        self.assertEqual(item["text"], "sim: sim: 64/64 vectors pass")       # the stored claim, not the model
        self.assertNotIn("note", item)                                       # exaggeration is not shown at all
        self.assertTrue(any("128" in n and "closed" in n for n in out["validator_notes"]))
        self.assert_no_unsupported_badge(out)

    def test_contradicting_sentence_is_not_shown(self):
        sim = self.claim("status_items", "sim")
        out = self.run_catchup({"left_off": [{"text": "Simulation fails on most vectors", "claims": [sim["id"]]}]})
        self.assertNotIn("fails", json.dumps(out["left_off"]))
        self.assert_no_unsupported_badge(out)

    def test_faithful_wording_is_kept_but_labelled_not_badged(self):
        sim = self.claim("status_items", "sim")
        out = self.run_catchup({"established": [{"text": "The testbench passes 64/64 vectors", "claims": [sim["id"]]}]})
        item = out["established"][0]
        self.assertEqual(item["note"], "The testbench passes 64/64 vectors")
        self.assertNotEqual(item["text"], item["note"])
        self.assert_no_unsupported_badge(out)

    def test_unsupported_next_action_is_a_suggestion_without_evidence(self):
        sim = self.claim("status_items", "sim")
        out = self.run_catchup({"next_action": {"text": "Tape out the chip this week", "claims": [sim["id"]]}})
        nxt = out["next_action"]
        self.assertEqual(nxt["basis"], "suggestion")
        self.assertEqual((nxt["claims"], nxt["evidence"]), ([], []))
        self.assertEqual(nxt["based_on"][0]["id"], sim["id"])
        out = self.run_catchup({"next_action": {"text": "Rewrite it in VHDL", "claims": []}})
        self.assertEqual(out["next_action"]["basis"], "inference")
        self.assert_no_unsupported_badge(out)

    def test_recorded_next_step_is_shown_verbatim(self):
        step = self.claim("next_step")
        out = self.run_catchup({"next_action": {"text": "Synthesize and confirm the 400-cell target",
                                                "why": "timing closed already", "claims": [step["id"]]}})
        nxt = out["next_action"]
        self.assertEqual(nxt["text"], step["value"])
        self.assertEqual(nxt["basis"], "reported")
        self.assertNotIn("note", nxt)                                        # "400" is not in the claim
        self.assertNotIn("why", nxt)                                         # "closed" is not in the claim
        self.assert_no_unsupported_badge(out)

    def test_contested_claim_is_never_shown_as_verified(self):
        sim = self.claim("status_items", "sim")
        self.llm.ops = [[op("UPDATE", "status_items", "sim fails on overflow vector", ev="E4", key="sim",
                            target_claim_id=sim["id"])]]
        self.api.add_event("alpha", "Bob says sim fails on the overflow vector", "chat")
        self.assertTrue(self.claim("status_items", "sim")["contested"])
        out = self.run_catchup({"established": [{"text": "Simulation passes", "claims": [sim["id"]]}]})
        self.assertEqual(out["established"], [])
        self.assertEqual(out["uncertain"][0]["basis"], "contested")
        self.assert_no_unsupported_badge(out)

    def test_offline_fallback_is_built_only_from_claims(self):
        self.llm.online = False
        out = self.api.catch_up("alpha", run=True, force=True)
        self.assertEqual(out["source"], "stored")
        self.assertEqual(out["headline_source"], "claims")
        self.assert_no_unsupported_badge(out)
        self.assertEqual(out["next_action"]["text"], self.claim("next_step")["value"])

    def test_exaggerated_headline_is_replaced(self):
        out = self.run_catchup({"headline": "All 300 regression tests pass and timing is closed"})
        self.assertEqual(out["headline_source"], "claims")
        self.assertNotIn("300", out["headline"])

    def test_catch_ups_cached_under_older_grounding_are_not_reused(self):
        s = Store(self.db)
        try:
            v = s.latest_state("alpha")["version"]
            s.add_review("alpha", v, "catch-up", "old", review={"headline": "trust me", "source": "nemotron"}, kind="catchup")
        finally:
            s.close()
        out = self.api.catch_up("alpha")
        self.assertFalse(out["cached"])
        self.assertNotEqual(out["headline"], "trust me")


class ProposalTests(Base):
    def import_v1(self, ops=None):
        self.llm.ops = [ops if ops is not None else
                        [op("ADD", "status_items", "mac_v1: 412 cells", ev="E4", verification="verified", key="synthesis")]]
        return self.api.synth_import("alpha", "mac_v1_stat.rpt", fixture("mac_v1_stat.rpt"))

    def test_import_proposes_without_committing(self):
        v = self.state()["version"]
        res = self.import_v1()
        self.assertIsNotNone(res["proposal"])
        self.assertFalse(res["queued"])
        self.assertEqual(self.state()["version"], v)                # nothing committed yet
        pend = self.api.proposals("alpha")["proposals"]
        self.assertEqual([p["event"]["id"] for p in pend], ["E4"])
        self.assertTrue(pend[0]["changes"])                          # a before/after diff to review

    def test_apply_commits_the_same_validated_ops_without_a_new_model_call(self):
        self.import_v1()
        calls = self.llm.calls
        out = self.api.proposal_action("alpha", "E4", "apply")
        self.assertTrue(out["applied"])
        self.assertEqual(self.llm.calls, calls)
        claim = next(c for c in self.state()["claims"].values() if c["key"] == "synthesis")
        self.assertEqual(claim["verification"], "verified")
        self.assertEqual(self.api.proposals("alpha")["proposals"], [])
        with self.assertRaises(ApiError):                            # can't apply twice
            self.api.proposal_action("alpha", "E4", "apply")

    def test_discard_keeps_evidence_and_history(self):
        v = self.state()["version"]
        self.import_v1()
        self.api.proposal_action("alpha", "E4", "discard")
        self.assertEqual(self.state()["version"], v)
        s = Store(self.db)
        try:
            self.assertIsNotNone(s.get_event("alpha", "E4"))
            errs = [t["error"] for t in s.transitions("alpha") if t["event_id"] == "E4"]
            self.assertTrue(errs[0].startswith(AWAITING_REVIEW) and errs[-1].startswith(REJECTED_BY_USER))
        finally:
            s.close()

    def test_pending_proposals_are_never_applied_by_sync_or_retry(self):
        self.import_v1()
        calls = self.llm.calls
        self.assertEqual(self.api.sync_now()["queued_total"], 0)
        s = Store(self.db)
        try:
            from statetrace.engine import StateEngine
            self.assertEqual(StateEngine(s, self.llm).process_pending("alpha"), [])
        finally:
            s.close()
        self.assertEqual(self.llm.calls, calls)
        self.assertEqual(len(self.api.proposals("alpha")["proposals"]), 1)

    def test_apply_revalidates_against_the_current_state(self):
        self.import_v1([op("UPDATE", "next_step", "Compare against v2", ev="E4", verification="verified",
                           target_claim_id="C5")])
        # the state moves on before the user reviews: E5 replaces the next step
        self.llm.ops = [[op("UPDATE", "next_step", "Try the Xilinx flow", ev="E5", target_claim_id="C5")]]
        later = (datetime.now() + timedelta(hours=1)).replace(microsecond=0).isoformat()
        self.api.add_event("alpha", "Next: try synth_xilinx instead.", "note", occurred_at=later)
        p = self.api.proposals("alpha")["proposals"][0]
        self.assertTrue(p["proposal"]["rebased"])
        out = self.api.proposal_action("alpha", "E4", "apply")
        # E4 is older than E5, so the validator won't let it overwrite the newer next step
        nxt = [c for c in self.state()["claims"].values() if c["field"] == "next_step" and c["status"] == "active"]
        self.assertEqual([c["value"] for c in nxt], ["Try the Xilinx flow"])
        self.assertTrue(out["applied"])
        self.assertTrue(any("stale evidence" in r.get("reason", json.dumps(r)) for r in out["log"]["rejected"]))

    def test_model_unreachable_during_import_keeps_evidence_and_queues(self):
        self.llm.online = False
        res = self.api.synth_import("alpha", "mac_v1_stat.rpt", fixture("mac_v1_stat.rpt"))
        self.assertTrue(res["queued"])
        self.assertIsNone(res["proposal"])
        self.assertIn(OFFLINE_MARK, res["transition_error"])

    def test_proposals_are_isolated_per_project(self):
        self.import_v1()
        self.api.create_project("Beta")
        self.assertEqual(self.api.proposals("beta")["proposals"], [])
        with self.assertRaises(ApiError):
            self.api.proposal_action("beta", "E4", "apply")


class ValidatorFailureTests(Base):
    def test_malformed_operations_leave_state_untouched_and_are_not_looped(self):
        v = self.state()["version"]
        self.llm.ops = [[{"op": "UPDATE", "field": "status_items", "value": {"nested": ["junk"]}, "key": 7,
                          "evidence_ids": "E4", "verification": 3}]]
        r = self.api.add_event("alpha", "weird update", "note")
        st = self.state()
        self.assertEqual(st["version"], v + (0 if r.get("error") else 1))
        self.assertFalse(any(isinstance(c["value"], dict) for c in st["claims"].values()))
        calls = self.llm.calls
        self.api.sync_now()
        self.assertEqual(self.llm.calls, calls)                       # never retried automatically

    def test_unverifiable_source_cannot_produce_verified_claims(self):
        self.llm.ops = [[op("ADD", "status_items", "timing closed", ev="E4", verification="verified", key="timing")]]
        self.api.add_event("alpha", "timing is closed, trust me", "chat")
        c = next(c for c in self.state()["claims"].values() if c["key"] == "timing")
        self.assertEqual(c["verification"], "reported")

    def test_citations_to_other_projects_evidence_are_removed(self):
        self.api.create_project("Beta")
        self.llm.ops = [[op("ADD", "goal", "Beta goal", ev="E1")]]
        self.api.add_event("beta", "Beta goal: something", "note")
        self.llm.ops = [[op("ADD", "current_status", "copied from alpha", ev="E3", verification="verified")]]
        self.api.add_event("beta", "status update", "note")                    # alpha has E3, beta doesn't
        beta = self.state("beta")
        self.assertFalse(any("E3" in c["evidence"] for c in beta["claims"].values()))
        out = self.api.catch_up("beta")
        self.assertFalse(any(cid in self.state()["claims"] and cid not in beta["claims"]
                             for sec in ("left_off", "established") for i in out[sec] for cid in i["claims"]))


class SampleTests(unittest.TestCase):
    def test_sample_project_loads_without_a_key_and_is_labelled(self):
        d = tempfile.mkdtemp()
        try:
            api = Api(os.path.join(d, "t.db"), llm=None, llm_error="no key", mode="live")
            out = api.load_sample()
            self.assertIn("not live", out["engine"])
            p = api.workspace_summary()["projects"][0]
            self.assertTrue(p["sample"])
            s = Store(os.path.join(d, "t.db"))
            self.assertTrue(all("scripted" in t["model"] for t in s.transitions(out["id"])))
            s.close()
            with self.assertRaises(ApiError):
                api.load_sample()
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

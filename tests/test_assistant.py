"""Assistant layer, autonomy, offline queue + sync, priority, shutdown. Fake model clients only."""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timedelta

from statetrace import assistant, priority
from statetrace.api import Api
from statetrace.background import Background
from statetrace.llm import LLMError, ModelUnavailable, NebiusClient, OFFLINE_MARK, retryable
from statetrace.server import make_server
from statetrace.store import Store
from statetrace.summary import project_summary, workspace_summary


class FakeLLM:
    """Engine ops via chat_json; answers/reviews via chat. `online` toggles reachability."""
    name = "fake-nemotron"

    def __init__(self, answer="Blocked on timing [E1]. Next: retime the ROM [E1].", review=None):
        self.online = True
        self.answer_text = answer
        self.review_data = review or {
            "direction": "at_risk", "headline": "Timing still failing close to the deadline.",
            "progress": [{"text": "Sim passes", "evidence": ["E1"]}],
            "concerns": [{"text": "WNS negative", "evidence": ["E1", "E99"]}],
            "suggestions": [{"title": "Retime the ROM output", "why": "critical path", "kind": "weird", "evidence": ["E1"]}],
            "questions": ["Is 200 MHz required?"], "confidence": "medium"}
        self.calls = 0

    def _check(self):
        self.calls += 1
        if not self.online:
            raise ModelUnavailable(f"{OFFLINE_MARK} cannot reach fake: no network")

    def chat_json(self, system, user):
        self._check()
        return {"operations": [{"op": "ADD", "field": "last_action", "value": "did a thing"}]}, ""

    def chat(self, system, user, json_mode=False, max_tokens=0):
        self._check()
        return json.dumps(self.review_data) if json_mode else self.answer_text

    def ping(self, timeout=6):
        return self.online


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "t.db")
        self.llm = FakeLLM()
        self.api = Api(self.db, llm=self.llm, mode="live")
        self.api.create_project("Alpha")
        self.api.add_event("alpha", "timing fails at 200 MHz", "note")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class AnswerTests(Base):
    def test_nemotron_first_with_stored_state_kept_for_comparison(self):
        a = self.api.ask("alpha", "Where did I leave off?")
        self.assertEqual(a["source"], "nemotron")
        self.assertTrue(a["mode"].startswith("Nemotron"))
        self.assertIn("Blocked on timing", a["headline"])
        self.assertIn("text", a["stored"])                       # the stored-state answer is still available
        self.assertEqual([c["id"] for c in a["citations"]], ["E1"])

    def test_falls_back_to_stored_state_when_offline(self):
        self.llm.online = False
        a = self.api.ask("alpha", "Where did I leave off?")
        self.assertEqual(a["source"], "stored")
        self.assertIn("Nemotron unavailable", a["mode"])

    def test_fullwidth_citations_are_normalised(self):
        self.llm.answer_text = "Blocked on timing 【E1】."
        a = self.api.ask("alpha", "Where did I leave off?")
        self.assertIn("[E1]", a["text"])
        self.assertEqual([c["id"] for c in a["citations"]], ["E1"])

    def test_invented_citations_are_flagged(self):
        self.llm.answer_text = "Done per [E42]."
        a = self.api.ask("alpha", "What changed?")
        self.assertEqual(a["invented_citations"], ["E42"])
        self.assertIn("E42(?)", a["text"])


class ReviewTests(Base):
    def test_review_is_cleaned_cached_and_never_touches_state(self):
        version = self.api.project("alpha")["state"]["version"]
        r = self.api.review("alpha")
        rv = r["review"]
        self.assertEqual(rv["direction"], "at_risk")
        self.assertEqual(rv["concerns"][0]["evidence"], ["E1"])       # invented E99 stripped
        self.assertEqual(rv["suggestions"][0]["kind"], "next_step")  # unknown kind normalised
        self.assertFalse(r["cached"])
        calls = self.llm.calls
        self.assertTrue(self.api.review("alpha")["cached"])           # same version: no new model call
        self.assertEqual(self.llm.calls, calls)
        self.assertEqual(self.api.project("alpha")["state"]["version"], version)  # opinion, not state

    def test_review_offline_reports_and_keeps_last(self):
        self.api.review("alpha")
        self.api.add_event("alpha", "another note", "note")
        self.llm.online = False
        with self.assertRaises(Exception):
            self.api.review("alpha")
        lr = self.api.latest_review("alpha")
        self.assertIsNotNone(lr["review"])
        self.assertIn("offline", lr["last_error"])


class AutonomyTests(Base):
    def test_access_levels_and_scope(self):
        s = Store(self.db)
        self.assertEqual(assistant.access_prefs(s)["access"], "off")
        self.assertFalse(assistant.allowed(assistant.access_prefs(s), "alpha"))
        with self.assertRaises(ValueError):
            assistant.set_access(s, "everything")
        p = assistant.set_access(s, "selected", ["alpha", "ghost"])
        self.assertEqual(p["projects"], ["alpha"])
        self.assertTrue(assistant.allowed(p, "alpha"))
        s.close()

    def test_automatic_reviews_only_for_allowed_projects(self):
        self.api.create_project("Beta")
        bg = Background(self.api, threading.Lock())
        bg.request_review("alpha")
        bg.request_review("beta")
        bg.run_reviews()  # autonomy off: nothing
        s = Store(self.db)
        self.assertIsNone(s.latest_review("alpha"))
        assistant.set_access(s, "selected", ["alpha"])
        s.close()
        bg.request_review("alpha")
        bg.request_review("beta")
        bg.run_reviews()
        s = Store(self.db)
        self.assertIsNotNone(s.latest_review("alpha"))
        self.assertIsNone(s.latest_review("beta"))
        s.close()

    def test_autonomy_and_monitoring_stay_in_sync(self):
        self.api.set_assistant_settings("all")
        self.assertTrue(self.api.companion_settings()["prefs"]["monitoring"])
        self.api.set_companion_settings({"monitoring": False})
        self.assertEqual(self.api.assistant_settings()["assistant"]["access"], "off")


class OfflineTests(Base):
    def test_offline_update_is_queued_then_synced_in_order(self):
        self.llm.online = False
        r1 = self.api.add_event("alpha", "offline note 1", "note")
        r2 = self.api.add_event("alpha", "offline note 2", "note")
        self.assertTrue(r1["queued_offline"] and r2["queued_offline"])
        self.assertEqual(r2["queued_total"], 2)
        self.assertEqual(self.api.sync()["queued_total"], 2)
        self.assertEqual(self.api.sync_now()["queued_total"], 2)  # still offline: nothing applied
        self.llm.online = True
        out = self.api.sync_now()
        self.assertEqual(out["queued_total"], 0)
        self.assertEqual(out["last_synced"], ["alpha:E2", "alpha:E3"])

    def test_non_network_failures_are_not_retried_automatically(self):
        s = Store(self.db)
        ev = s.append_event("alpha", "bad output case", "note")
        s.save_transition("alpha", ev["id"], 1, 1, "fake", 0, None, [], [], [], error="no JSON object in model response")
        s.close()
        calls = self.llm.calls
        self.assertEqual(self.api.sync_now()["queued_total"], 0)  # not shown as "waiting to sync"
        self.assertEqual(self.llm.calls, calls)  # needs a manual retry, never an endless loop
        s = Store(self.db)
        self.assertEqual([e["id"] for e in s.pending_events("alpha")], [ev["id"]])  # but still not applied
        s.close()

    def test_retryable_classification(self):
        self.assertTrue(retryable(f"{OFFLINE_MARK} cannot reach"))
        self.assertTrue(retryable("cannot reach https://x"))
        self.assertTrue(retryable("HTTP 503 from chat/completions"))
        self.assertTrue(retryable("HTTP 401 from chat/completions"))
        self.assertFalse(retryable("no JSON object in model response"))

    def test_unreachable_service_fails_fast(self):
        c = NebiusClient(api_key="x", base_url="http://127.0.0.1:9/v1/")
        t0 = time.monotonic()
        with self.assertRaises(ModelUnavailable):
            c.chat_json("s", "u")
        self.assertLess(time.monotonic() - t0, 5)
        self.assertFalse(c.ping(timeout=2))


class PriorityTests(Base):
    def test_deadlines_and_manual_priority_order_projects(self):
        self.api.create_project("Beta")
        self.api.create_project("Empty")  # no evidence yet: must still be listed
        soon = (datetime.now() + timedelta(days=2)).replace(microsecond=0).isoformat()
        self.api.add_milestone("beta", "Tapeout", soon)
        ws = self.api.workspace_summary()
        names = [p["id"] for p in ws["projects"]]
        self.assertEqual(names[0], "beta")
        self.assertIn("empty", names)
        self.assertIn("Tapeout: due in", " ".join(ws["projects"][0]["priority"]["reasons"]))
        self.api.set_priority("alpha", "high")
        self.assertEqual(self.api.workspace_summary()["projects"][0]["id"], "beta")  # deadline in 2 days still wins
        self.api.set_priority("beta", "low")
        s = Store(self.db)
        sc = priority.score(s, project_summary(s, "alpha"))
        s.close()
        self.assertIn("you marked it High priority", sc["reasons"])


class ShutdownTests(unittest.TestCase):
    def test_quit_button_stops_the_server_cleanly(self):
        d = tempfile.mkdtemp()
        try:
            httpd, api = make_server(os.path.join(d, "t.db"), 0, api=Api(os.path.join(d, "t.db"), llm=None, mode="live"))
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            url = f"http://127.0.0.1:{httpd.server_address[1]}/api/shutdown"
            req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as r:
                self.assertTrue(json.loads(r.read())["stopping"])
            self.assertTrue(api.shutdown_event.wait(5))
            t.join(5)
            self.assertFalse(t.is_alive())
            httpd.server_close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

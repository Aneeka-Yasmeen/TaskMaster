import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime

from statetrace import monitoring, reminders
from statetrace.api import Api
from statetrace.companion import BackendError, Companion
from statetrace.engine import StateEngine
from statetrace.llm import LLMError
from statetrace.schema import empty_state
from statetrace.store import Store
from statetrace.validator import apply_operations
from statetrace.winapi import toast_xml

HAS_GIT = shutil.which("git") is not None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_repo(path):
    env = dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="d@x", GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="d@x")
    run = lambda *a: subprocess.run(["git", "-C", path, *a], check=True, capture_output=True, env=env)  # noqa: E731
    os.makedirs(path)
    run("init", "-q", "-b", "main")
    for i in range(2):
        with open(os.path.join(path, "f.txt"), "a") as fh:
            fh.write(f"{i}\n")
        run("add", "f.txt")
        run("commit", "-q", "-m", f"change {i}")
    return run


class FakeNotifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.shown = []

    def __call__(self, title, body, url):
        self.shown.append((title, body, url))
        return (True, "shown") if self.ok else (False, "Windows notifications are turned off for this app")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "t.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_defaults_are_off_and_settings_survive_a_restart(self):
        s = Store(self.db)
        p = monitoring.companion_prefs(s)
        self.assertEqual((p["monitoring"], p["notifications"], p["paused"], p["hotkey"]), (False, False, False, "ctrl+alt+t"))
        monitoring.set_companion_prefs(s, {"monitoring": True, "notifications": True, "interval_minutes": 30})
        s.close()
        s = Store(self.db)  # "restart"
        p = monitoring.companion_prefs(s)
        self.assertEqual((p["monitoring"], p["notifications"], p["interval_minutes"]), (True, True, 30))
        self.assertIsNotNone(p["enabled_at"])
        monitoring.set_companion_prefs(s, {"monitoring": False})
        self.assertFalse(monitoring.active(monitoring.companion_prefs(s)))
        with self.assertRaises(ValueError):
            monitoring.set_companion_prefs(s, {"monitoring": "yes"})
        with self.assertRaises(ValueError):
            monitoring.set_companion_prefs(s, {"interval_minutes": 1})
        s.close()

    def test_hotkey_setting_is_validated(self):
        from statetrace.winapi import parse_hotkey
        self.assertEqual(parse_hotkey("ctrl+alt+space"), (0x3, 0x20))
        self.assertEqual(parse_hotkey("Ctrl+Alt+T"), (0x3, ord("T")))
        for bad in ("space", "shift+a", "ctrl+alt+ü", "ctrl+banana+x"):
            with self.assertRaises(ValueError):
                parse_hotkey(bad)
        s = Store(self.db)
        self.assertEqual(monitoring.set_companion_prefs(s, {"hotkey": "Ctrl+Alt+T"})["hotkey"], "ctrl+alt+t")
        with self.assertRaises(ValueError):
            monitoring.set_companion_prefs(s, {"hotkey": "q"})
        s.close()

    def test_toast_text_is_escaped(self):
        x = toast_xml('a <b> & "c"', "body", 'http://127.0.0.1:8765/#/p/x?q="1"')
        self.assertIn("a &lt;b&gt; &amp;", x)
        self.assertNotIn('"1""', x)


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def tearDown(self):
        self.s.close()

    def _state(self, project, ops, eid="E1", source="sim_log", when="2026-10-09T10:00:00"):
        ev = self.s.append_event(project, "x", source, occurred_at=when)
        self._apply(project, ops, ev)

    def _apply(self, project, ops, ev):
        old = self.s.latest_state(project)
        st, log = apply_operations(old, ops, ev, self.s.events_by_id(project))
        self.s.save_state(st)
        self.s.save_transition(project, ev["id"], old["version"], st["version"], "test", 0, {}, log.applied,
                               log.rejected, log.warnings)

    def test_empty_project_reports_missing_state_without_inventing_it(self):
        self.s.set_project_name("empty", "Empty")
        b = monitoring.companion_brief(self.s, "empty")
        self.assertEqual((b["blocker"], b["next_step"], b["latest_change"], b["milestone"]), (None, None, None, None))
        self.assertEqual(b["project"]["events"], 0)

    def test_contested_stale_and_proposed_flags_and_isolation(self):
        self._state("p", [{"op": "ADD", "field": "current_blocker", "value": "AXI fails", "verification": "verified"},
                          {"op": "ADD", "field": "next_step", "value": "fix tready"}], when="2026-09-01T10:00:00")
        ev2 = self.s.append_event("p", "note", "note", occurred_at="2026-09-02T10:00:00")
        self._apply("p", [{"op": "CONTRADICT", "field": "current_blocker", "value": "note says fixed"}], ev2)
        self._state("q", [{"op": "ADD", "field": "current_blocker", "value": "Q secret blocker"}])
        b = monitoring.companion_brief(self.s, "p", datetime(2026, 10, 12))
        self.assertTrue(b["blocker"]["contested"])
        self.assertTrue(b["blocker"]["stale"])  # no evidence for 40 days
        self.assertEqual(b["next_step"]["commitment"], "proposed")
        self.assertEqual(b["latest_change"]["event"], "E2")
        self.assertNotIn("Q secret", str(b))
        m = self.s.add_milestone("p", "Ship", "2026-10-20T10:00", source_claim=b["next_step"]["id"])
        b = monitoring.companion_brief(self.s, "p", datetime(2026, 10, 12))
        self.assertEqual((b["next_step"]["commitment"], b["milestone"]["id"]), ("committed", m["id"]))


class FailingLLM:
    name = "failing"

    def chat_json(self, system, user):
        raise LLMError("HTTP 503 from chat/completions: Nebius outage")


class ApiFailureTests(unittest.TestCase):
    def test_model_outage_keeps_evidence_and_previous_state(self):
        d = tempfile.mkdtemp()
        try:
            db = os.path.join(d, "t.db")
            s = Store(db)
            ev = s.append_event("p", "goal", "note", occurred_at="2026-10-01T10:00:00")
            st, _ = apply_operations(empty_state("p"), [{"op": "ADD", "field": "goal", "value": "g"}], ev, {"E1": ev})
            s.save_state(st)
            s.close()
            api = Api(db, llm=FailingLLM(), mode="live")
            r = api.add_event("p", "tried something", "note")
            self.assertIsNotNone(r["transition"]["error"])
            s = Store(db)
            self.assertEqual(s.latest_state("p")["version"], 1)          # state untouched
            self.assertEqual(len(s.events("p")), 2)                      # evidence kept for retry
            self.assertEqual(monitoring.companion_brief(s, "p")["project"]["events"], 2)  # popup still works
            s.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(HAS_GIT, "git not installed")
class CompanionLoopTests(unittest.TestCase):
    """Runs a real in-process server; only the OS-facing parts are fakes."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "t.db")
        s = Store(self.db)
        s.append_event("p", "goal: build it", "note", occurred_at=datetime.now().replace(microsecond=0).isoformat())
        s.set_project_name("p", "Project P")
        s.set_project_name("q", "Project Q")
        s.close()
        self.repo = os.path.join(self.dir, "repo")
        self.git = make_repo(self.repo)
        self.notifier = FakeNotifier()
        self.opened = []
        self.windows = []
        self.c = Companion(self.db, free_port(), hotkey=False, popup=False, notifier=self.notifier,
                           opener=lambda url: self.opened.append(url) or "fake", log=lambda *a: None,
                           finder=lambda: list(self.windows), focuser=lambda h: self.opened.append(("focus", h)))
        self.c.ensure_backend()
        self.api = self.c.client

    def tearDown(self):
        self.c.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def prefs(self, **kw):
        self.api.post("settings/companion", kw)

    def store(self):
        return Store(self.db)

    def test_monitoring_off_by_default_does_no_background_work(self):
        self.api.post("sources/add", {"project": "p", "path": self.repo})
        r = self.c.tick()
        self.assertTrue(r["heartbeat"])
        self.assertEqual((r["scanned"], r["notified"], r["skipped"]), ([], [], "monitoring off"))
        s = self.store()
        self.assertEqual(s.import_items("p"), [])
        self.assertEqual(s.notices(), [])
        self.assertTrue(monitoring.companion_status(s)["alive"])
        s.close()

    def test_enabled_monitoring_stages_once_and_never_accepts(self):
        self.api.post("sources/add", {"project": "p", "path": self.repo, "auto_accept": True})
        self.prefs(monitoring=True)
        r = self.c.tick(now=1000.0)
        self.assertEqual(r["scanned"], [("p", 2)])
        s = self.store()
        self.assertEqual(len(s.import_items("p", "pending")), 2)
        self.assertEqual(len(s.events("p")), 1)  # auto-accept is ignored in the background
        self.assertEqual([n["kind"] for n in s.notices()], ["imports"])
        s.close()
        r = self.c.tick(now=1000.0 + 16 * 60)  # next scan due: nothing new, nothing duplicated
        self.assertEqual(r["scanned"], [("p", 0)])
        s = self.store()
        self.assertEqual(len(s.import_items("p")), 2)
        self.assertEqual(len(s.notices()), 1)
        s.close()

    def test_paused_removed_sources_and_pause_all_are_respected(self):
        src = self.api.post("sources/add", {"project": "p", "path": self.repo})
        self.prefs(monitoring=True, paused=True)
        self.assertEqual(self.c.tick(now=10.0)["skipped"], "monitoring paused")
        self.prefs(paused=False)
        self.api.post("sources/update", {"id": src["id"], "enabled": False})
        self.assertEqual(self.c.tick(now=10.0)["scanned"], [])
        self.api.post("sources/remove", {"id": src["id"]})
        self.c.last_scan = 0
        self.assertEqual(self.c.tick(now=20.0)["scanned"], [])
        s = self.store()
        self.assertEqual(s.import_items("p"), [])
        s.close()

    def test_notifications_once_respect_quiet_hours_and_failures(self):
        self.api.post("sources/add", {"project": "p", "path": self.repo})
        self.api.post("settings/notifications", {"quiet_start": "00:00", "quiet_end": "23:59"})  # always quiet
        self.prefs(monitoring=True, notifications=True)
        self.c.tick(now=1.0)
        self.assertEqual(self.notifier.shown, [])  # quiet hours: nothing pops up
        self.api.post("settings/notifications", {"quiet_start": "03:00", "quiet_end": "03:01"})
        self.notifier.ok = False
        self.c.tick(now=2.0)
        self.assertEqual(len(self.notifier.shown), 1)     # attempted, failed: stays undelivered
        self.assertIn("turned off", self.c.last_error)
        self.notifier.ok = True
        self.c.tick(now=3.0)
        self.c.tick(now=4.0)
        self.assertEqual(len(self.notifier.shown), 2)     # delivered exactly once after the failure
        title, body, url = self.notifier.shown[-1]
        self.assertIn("2 new commits waiting for review in Project P", body)
        self.assertNotIn("change 0", body)                # no commit messages in notifications
        self.assertTrue(url.endswith("#/p/p/inbox"))

    def test_notifications_need_monitoring_and_ignore_older_notices(self):
        s = self.store()
        s.add_notice("p", "stale", "stale:p:old", "Project P may be stale", "old")  # before opting in
        s.close()
        self.prefs(notifications=True)  # monitoring still off
        self.assertEqual(self.c.tick(now=1.0)["notified"], [])
        self.prefs(monitoring=True)
        self.c.tick(now=2.0)
        self.assertEqual(self.notifier.shown, [])

    def test_reminder_dedup_is_unchanged(self):
        self.prefs(monitoring=True, notifications=True)
        self.api.post("settings/notifications", {"quiet_start": "03:00", "quiet_end": "03:01"})
        soon = datetime.now().replace(microsecond=0).isoformat()
        self.api.post("milestones/add", {"project": "p", "title": "Demo", "due_at": soon, "reminders": [60]})
        for t in (1.0, 2.0, 3.0):
            self.c.tick(now=t)
        self.assertEqual(len([x for x in self.notifier.shown if "Demo" in x[1]]), 1)
        s = self.store()
        self.assertEqual(len(reminders.generate_notices(s)), 0)
        s.close()

    def test_closing_the_ui_keeps_the_backend_and_no_duplicate_servers(self):
        self.assertEqual(self.c.open_popup(), "opened (fake)")
        self.assertEqual(self.c.open_popup(), "launching")    # repeated press before the window appears
        self.windows.append(42)
        self.assertEqual(self.c.open_popup(), "focused")      # repeated press focuses, never stacks
        self.windows.clear()                                   # user closes the popup
        self.assertEqual(self.api.get("meta")["product"], "TaskMaster")  # server unaffected
        other = Companion(self.db, self.c.port, hotkey=False, popup=False, log=lambda *a: None)
        other.ensure_backend()
        self.assertEqual(other.backend, "connected")          # reuses, does not start a second server
        self.assertIsNone(other.httpd)

    def test_port_used_by_something_else_is_refused(self):
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen()
            c = Companion(self.db, blocker.getsockname()[1], hotkey=False, popup=False, log=lambda *a: None)
            with self.assertRaises(BackendError):
                c.ensure_backend()

    def test_backend_down_is_reported_not_crashing(self):
        self.c.stop()
        r = self.c.tick()
        self.assertIn("not reachable", r["skipped"])


if __name__ == "__main__":
    unittest.main()

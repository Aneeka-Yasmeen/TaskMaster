import os
import shutil
import subprocess
import tempfile
import unittest

from statetrace import ingest
from statetrace.engine import StateEngine
from statetrace.llm import LLMError, ScriptedLLM
from statetrace.store import Store

HAS_GIT = shutil.which("git") is not None


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="dev@example.com",
               GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="dev@example.com")
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def commit(repo, name, message, date):
    with open(os.path.join(repo, name), "a", encoding="utf-8") as fh:
        fh.write(message + "\n")
    git(repo, "add", name)
    env_date = ["-c", "commit.gpgsign=false"]
    subprocess.run(["git", "-C", repo, *env_date, "commit", "-q", "-m", message, "--date", date], check=True,
                   capture_output=True, env=dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="d@x",
                                                 GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="d@x",
                                                 GIT_COMMITTER_DATE=date))


class FailingLLM:
    name = "failing"

    def chat_json(self, system, user):
        raise LLMError("HTTP 503 from chat/completions: unavailable")


class NoopLLM(ScriptedLLM):
    def __init__(self):
        super().__init__({})


@unittest.skipUnless(HAS_GIT, "git not installed")
class GitIngestTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.repo = os.path.join(self.dir, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, "a.v", "add PE array", "2026-10-01T10:00:00+05:30")
        commit(self.repo, "b.v", "fix col counter wrap\n\nstride 2 off-by-one", "2026-10-02T11:00:00+05:30")
        self.store = Store(os.path.join(self.dir, "t.db"))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_scan_stages_without_touching_state_and_dedupes(self):
        src = ingest.add_source(self.store, "p", "git", {"path": self.repo})
        self.assertEqual(src["config"]["branch"], "main")
        r = ingest.scan_source(self.store, src)
        self.assertEqual(r["new"], 2)
        self.assertEqual(self.store.events("p"), [])  # nothing affects evidence/state yet
        self.assertEqual(ingest.scan_source(self.store, src)["new"], 0)  # repeated scan: no duplicates
        commit(self.repo, "c.v", "pipeline the MAC", "2026-10-03T09:00:00+05:30")
        self.assertEqual(ingest.scan_source(self.store, src)["new"], 1)
        items = self.store.import_items("p", "pending")
        self.assertEqual([i["title"] for i in items], ["add PE array", "fix col counter wrap", "pipeline the MAC"])
        self.assertIn("stride 2 off-by-one", items[1]["payload"]["text"])
        self.assertEqual(items[0]["occurred_at"][:10], "2026-10-01")

    def test_accept_appends_git_evidence_and_skip_is_reversible(self):
        src = ingest.add_source(self.store, "p", "git", {"path": self.repo})
        ingest.scan_source(self.store, src)
        first, second = self.store.import_items("p", "pending")
        res = ingest.accept(self.store, StateEngine(self.store, NoopLLM()), "p", [first["id"]])
        ev = self.store.get_event("p", res[0]["event"])
        self.assertEqual((ev["source"], ev["ref"]), ("git_commit", first["payload"]["ref"]))
        self.assertEqual(self.store.get_item(first["id"])["status"], "accepted")
        self.assertEqual(ingest.skip(self.store, "p", [second["id"]]), 1)
        self.assertEqual(ingest.skip(self.store, "p", [second["id"]], restore=True), 1)
        self.assertEqual(self.store.get_item(second["id"])["status"], "pending")

    def test_failed_transition_keeps_evidence_and_can_be_retried(self):
        src = ingest.add_source(self.store, "p", "git", {"path": self.repo})
        ingest.scan_source(self.store, src)
        item = self.store.import_items("p", "pending")[0]
        ingest.accept(self.store, StateEngine(self.store, FailingLLM()), "p", [item["id"]])
        failed = self.store.get_item(item["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(len(self.store.events("p")), 1)  # evidence kept
        ingest.retry(self.store, StateEngine(self.store, NoopLLM()), "p", [item["id"]])
        self.assertEqual(self.store.get_item(item["id"])["status"], "accepted")
        self.assertEqual(len(self.store.events("p")), 1)  # retry does not duplicate evidence

    def test_commit_already_recorded_by_hand_is_not_staged_again(self):
        src = ingest.add_source(self.store, "p", "git", {"path": self.repo})
        short = subprocess.run(["git", "-C", self.repo, "rev-parse", "--short", "HEAD"], capture_output=True,
                               text=True).stdout.strip()
        self.store.append_event("p", "fixed it", "git_commit", ref=short)
        self.assertEqual(ingest.scan_source(self.store, src)["new"], 1)

    def test_paused_source_does_not_scan_and_projects_are_isolated(self):
        src = ingest.add_source(self.store, "p", "git", {"path": self.repo})
        self.store.update_source(src["id"], enabled=False)
        self.assertTrue(ingest.scan_source(self.store, self.store.get_source(src["id"]))["skipped_paused"])
        other = ingest.add_source(self.store, "q", "git", {"path": self.repo})
        ingest.scan_source(self.store, other)
        self.assertEqual(self.store.import_items("p"), [])
        item = self.store.import_items("q")[0]
        self.assertEqual(ingest.accept(self.store, StateEngine(self.store, NoopLLM()), "p", [item["id"]]), [])

    def test_bad_folder_is_rejected_with_a_readable_error(self):
        with self.assertRaises(ingest.IngestError):
            ingest.add_source(self.store, "p", "git", {"path": self.dir})


if __name__ == "__main__":
    unittest.main()

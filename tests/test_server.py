"""HTTP-level tests: cross-site protection, read-only mode, project isolation, new routes."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from statetrace.api import Api
from statetrace.server import make_server
from statetrace.store import Store


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.db = os.path.join(cls.dir, "t.db")
        s = Store(cls.db)
        s.append_event("p", "goal: build it", "note", occurred_at="2026-10-01T10:00:00")
        s.append_event("q", "other project", "note", occurred_at="2026-10-01T10:00:00")
        s.close()
        cls.servers = []
        cls.rw = cls._start(Api(cls.db, llm=None, mode="live"))          # local writes allowed, no model
        cls.ro = cls._start(Api(cls.db, llm=None, mode="read_only"))

    @classmethod
    def _start(cls, api):
        httpd, _ = make_server(cls.db, 0, api=api)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        cls.servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        for h in cls.servers:
            h.shutdown()
            h.server_close()

    def req(self, base, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(base + path, data=data, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_cross_site_post_is_refused(self):
        body = {"project": "p", "title": "x"}
        self.assertEqual(self.req(self.rw, "/api/milestones/add", body, {"Origin": "https://evil.example"})[0], 403)
        # a "simple" cross-site form post (text/plain) must not be processed either
        r = urllib.request.Request(self.rw + "/api/milestones/add", data=json.dumps(body).encode(),
                                   headers={"Content-Type": "text/plain"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 415)
        self.assertEqual(self.req(self.rw, "/api/meta", headers={"Host": "attacker.example:80"})[0], 403)

    def test_same_origin_milestone_flow_and_isolation(self):
        host = self.rw.split("//")[1]
        status, m = self.req(self.rw, "/api/milestones/add",
                             {"project": "p", "title": "Tapeout", "due_at": "2030-01-01T17:00"}, {"Origin": self.rw})
        self.assertEqual(status, 200, m)
        _, lst = self.req(self.rw, "/api/milestones?project=p")
        self.assertEqual([x["title"] for x in lst["milestones"]], ["Tapeout"])
        _, other = self.req(self.rw, "/api/milestones?project=q")
        self.assertEqual(other["milestones"], [])
        status, done = self.req(self.rw, "/api/milestones/update", {"id": m["id"], "status": "done"})
        self.assertEqual((status, done["status"]), (200, "done"))
        self.assertIsNotNone(done["closed_at"])
        self.assertTrue(host)

    def test_model_writes_need_the_engine_but_local_writes_do_not(self):
        status, err = self.req(self.rw, "/api/events", {"project": "p", "text": "hello"})
        self.assertEqual(status, 503)
        self.assertIn("NEBIUS_API_KEY", err["error"])

    def test_read_only_refuses_every_write(self):
        for path, body in [("/api/milestones/add", {"project": "p", "title": "x"}),
                           ("/api/sources/add", {"project": "p", "path": "."}),
                           ("/api/settings/notifications", {"enabled": False}),
                           ("/api/events", {"project": "p", "text": "x"})]:
            self.assertEqual(self.req(self.ro, path, body)[0], 403, path)
        self.assertEqual(self.req(self.ro, "/api/project?project=p")[0], 200)

    def test_bad_input_gives_readable_errors_not_tracebacks(self):
        status, err = self.req(self.rw, "/api/milestones/add", {"project": "p", "title": "x", "due_at": "next tuesday"})
        self.assertEqual(status, 400)
        self.assertIn("could not be read", err["error"])
        status, err = self.req(self.rw, "/api/project?project=nope")
        self.assertEqual(status, 404)
        status, err = self.req(self.rw, "/api/settings/notifications", {"quiet_start": "99:00"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()

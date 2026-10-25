"""HTTP server: serves the TaskMaster frontend and the JSON API (stdlib only)."""

import json
import mimetypes
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .api import ApiError, make_api
from .background import Background

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def serve(db_path, port=8765, offline=False, read_only=False, host="127.0.0.1"):
    httpd, api = make_server(db_path, port, offline, read_only, host)
    print("Stop it with Ctrl+C here, the Quit button in Settings, or `python -m statetrace stop`.")
    meta = api.meta()
    engine = "read-only" if api.mode == "read_only" else (meta["model"] or f"not connected ({meta['model_error']})")
    print(f"TaskMaster: http://{host}:{port}  (workspace: {meta['workspace']}, mode: {api.mode}, engine: {engine})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def make_server(db_path, port=8765, offline=False, read_only=False, host="127.0.0.1", api=None):
    api = api or make_api(db_path, offline=offline, read_only=read_only)
    write_lock = threading.Lock()

    get_routes = {
        "/api/meta": lambda q: api.meta(),
        "/api/workspace": lambda q: api.workspace_summary(q.get("now")),
        "/api/project": lambda q: api.project(q.get("project"), q.get("now")),
        "/api/state": lambda q: api.state(q.get("project"), q.get("version", "0")),
        "/api/events": lambda q: api.events(q.get("project")),
        "/api/evidence": lambda q: api.evidence(q.get("project")),
        "/api/transition": lambda q: api.transition(q.get("project"), q.get("event")),
        "/api/why": lambda q: api.why(q.get("project"), q.get("q")),
        "/api/activity": lambda q: api.activity(),
        "/api/sources": lambda q: api.sources(q.get("project")),
        "/api/milestones": lambda q: api.milestones(q.get("project")),
        "/api/notices": lambda q: api.notices(),
        "/api/settings/notifications": lambda q: api.notification_prefs(),
        "/api/settings/companion": lambda q: api.companion_settings(),
        "/api/companion/brief": lambda q: api.companion_brief(q.get("project")),
        "/api/companion/deliverable": lambda q: api.companion_deliverable(),
        "/api/review": lambda q: api.latest_review(q.get("project")),
        "/api/catchup": lambda q: api.catch_up(q.get("project")),
        "/api/proposals": lambda q: api.proposals(q.get("project")),
        "/api/settings/assistant": lambda q: api.assistant_settings(),
        "/api/sync": lambda q: api.sync(),
        "/api/synth": lambda q: api.synth_overview(q.get("project")),
        "/api/synth/excerpt": lambda q: api.synth_excerpt(q.get("project"), q.get("run")),
    }

    def locked(fn):
        def run(body):
            with write_lock:
                return fn(body)
        return run

    post_routes = {
        "/api/ask": lambda b: api.ask(b.get("project"), b.get("question"), b.get("now")),
        "/api/projects": locked(lambda b: api.create_project(b.get("name"))),
        "/api/sample": locked(lambda b: api.load_sample()),
        "/api/events": locked(lambda b: api.add_event(b.get("project"), b.get("text"), b.get("source", "note"),
                                                      b.get("occurred_at"), b.get("ref"), b.get("event_type"))),
        "/api/retry": locked(lambda b: api.retry(b.get("project"))),
        "/api/sources/add": locked(lambda b: api.add_source(b.get("project"), b.get("path"), b.get("branch"),
                                                             b.get("wsl", False), b.get("auto_accept", False))),
        "/api/sources/update": locked(lambda b: api.update_source(b.get("id"), b.get("enabled"), b.get("auto_accept"))),
        "/api/sources/remove": locked(lambda b: api.remove_source(b.get("id"))),
        "/api/imports/accept": locked(lambda b: api.accept_imports(b.get("project"), b.get("ids"))),
        "/api/imports/retry": locked(lambda b: api.retry_imports(b.get("project"), b.get("ids"))),
        "/api/imports/skip": locked(lambda b: api.skip_imports(b.get("project"), b.get("ids"), b.get("restore", False))),
        "/api/milestones/add": locked(lambda b: api.add_milestone(b.get("project"), b.get("title"), b.get("due_at"),
                                                                   b.get("reminders"), b.get("notes"), b.get("source_claim"))),
        "/api/milestones/update": locked(lambda b: api.update_milestone(
            b.get("id"), **{k: b[k] for k in ("title", "due_at", "status", "notes", "reminders", "confirmed") if k in b})),
        "/api/milestones/delete": locked(lambda b: api.delete_milestone(b.get("id"))),
        "/api/notices/dismiss": locked(lambda b: api.dismiss_notice(b.get("id"), b.get("delivered_only", False))),
        "/api/settings/notifications": locked(lambda b: api.set_notification_prefs(b)),
        "/api/settings/companion": locked(lambda b: api.set_companion_settings(b)),
        "/api/companion/heartbeat": lambda b: api.companion_heartbeat(b),
        "/api/companion/delivered": locked(lambda b: api.companion_delivered(b.get("ids"))),
        "/api/companion/test-notification": locked(lambda b: api.companion_test_notification()),
        "/api/sources/scan": locked(lambda b: api.scan(b.get("project"), b.get("id"), bool(b.get("background")))),
        "/api/open": lambda b: open_dashboard(b.get("path")),
        "/api/review": lambda b: api.review(b.get("project"), b.get("force", False)),
        "/api/catchup": lambda b: api.catch_up(b.get("project"), run=True, force=b.get("force", False)),
        "/api/settings/assistant": locked(lambda b: api.set_assistant_settings(b.get("access"), b.get("projects"))),
        "/api/projects/priority": locked(lambda b: api.set_priority(b.get("project"), b.get("priority"))),
        "/api/sync": locked(lambda b: api.sync_now()),
        "/api/shutdown": lambda b: api.shutdown(),
        "/api/synth/import": locked(lambda b: api.synth_import(b.get("project"), b.get("filename"), b.get("content"),
                                                               b.get("review", True))),
        "/api/proposals/apply": locked(lambda b: api.proposal_action(b.get("project"), b.get("event"), "apply")),
        "/api/proposals/discard": locked(lambda b: api.proposal_action(b.get("project"), b.get("event"), "discard",
                                                                       b.get("reason", ""))),
        "/api/synth/compare": locked(lambda b: api.synth_compare(b.get("project"), b.get("run"), b.get("baseline"))),
        "/api/synth/explain": lambda b: api.synth_explain(b.get("project"), b.get("analysis")),
        "/api/synth/constraints": locked(lambda b: api.synth_constraints(b.get("project"), b.get("constraints"))),
    }

    def open_dashboard(path):
        """Open a dashboard route in the default browser (used by the compact companion window)."""
        path = str(path or "/")
        if host not in LOOPBACK:
            raise ApiError("Opening the dashboard is only available on a local server.", 403)
        if not re.fullmatch(r"/[A-Za-z0-9_/-]*(\?[A-Za-z0-9_=&%.-]*)?", path):
            raise ApiError("Not a TaskMaster dashboard path.")
        webbrowser.open(f"http://127.0.0.1:{httpd.server_address[1]}/#{path}")
        return {"opened": path}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            """Block DNS rebinding: when bound to loopback, only loopback Host headers are served."""
            if host not in LOOPBACK:
                return True
            h = (self.headers.get("Host") or "").lower()
            name = h[1:].split("]")[0] if h.startswith("[") else h.split(":")[0]
            return name in LOOPBACK

        def _origin_ok(self):
            """Block cross-site requests: a browser always sends Origin on cross-origin POSTs."""
            origin = self.headers.get("Origin")
            return origin is None or urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

        def _dispatch(self, fn, arg):
            try:
                return self._send(200, fn(arg))
            except ApiError as e:
                return self._send(e.status, {"error": str(e), **e.extra})
            except Exception as e:  # never leak a stack trace to the browser
                print(f"internal error on {self.path}: {e!r}")
                return self._send(500, {"error": "Something went wrong on the TaskMaster server. "
                                                 "Your evidence log is unchanged."})

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "Unexpected Host header."})
            url = urlparse(self.path)
            if url.path in get_routes:
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                return self._dispatch(get_routes[url.path], q)
            path = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            full = os.path.normpath(os.path.join(STATIC, path))
            if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
                full = os.path.join(STATIC, "index.html")  # client-side routes
            with open(full, "rb") as fh:
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, fh.read(), ctype)

        def do_POST(self):
            url = urlparse(self.path)
            if url.path not in post_routes:
                return self._send(404, {"error": "not found"})
            # Cross-site protection: JSON content type forces a CORS preflight (which this server
            # never approves), the Origin check rejects other sites, the Host check stops rebinding.
            if not self._host_ok() or not self._origin_ok():
                return self._send(403, {"error": "Requests from other sites are not allowed."})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._send(415, {"error": "Send JSON (Content-Type: application/json)."})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 3_000_000:
                    return self._send(413, {"error": "That request is too large (limit 3 MB). Export only the report section you need."})
                body = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "The request was not valid JSON."})
            return self._dispatch(post_routes[url.path], body)

    httpd = ThreadingHTTPServer((host, port), Handler)
    api.shutdown_event = threading.Event()
    bg = Background(api, write_lock)
    api.on_new_state = bg.request_review

    def _shutdown():
        def stop():
            bg.stop()
            httpd.shutdown()
            api.shutdown_event.set()
        threading.Thread(target=stop, name="taskmaster-shutdown", daemon=True).start()

    api.on_shutdown = _shutdown
    if api.mode == "live" and api.llm is not None:
        bg.start()
    return httpd, api

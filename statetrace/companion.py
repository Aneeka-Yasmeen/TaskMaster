import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import winapi

TICK_SECONDS = 30


class BackendError(RuntimeError):
    pass


class Client:
    """Minimal JSON client for the local API (sends JSON, as the server requires for writes)."""

    def __init__(self, base, timeout=30):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _call(self, method, path, body=None, params=None):
        url = f"{self.base}/api/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("error")
            except ValueError:
                msg = None
            raise BackendError(msg or f"HTTP {e.code} from {path}") from None
        except (urllib.error.URLError, OSError) as e:
            raise BackendError(f"TaskMaster server not reachable at {self.base} ({e})") from None

    def get(self, path, **params):
        return self._call("GET", path, params=params or None)

    def post(self, path, body):
        return self._call("POST", path, body=body)


def probe(base, timeout=1.5):
    """Return the server's meta if a TaskMaster server answers at `base`, else None."""
    try:
        meta = Client(base, timeout).get("meta")
    except BackendError:
        return None
    return meta if meta.get("product") == "TaskMaster" else None


def port_free(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def default_profile_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "TaskMaster", "companion-browser-profile")


class Companion:
    def __init__(self, db_path, port=8765, offline=False, hotkey=True, popup=True, hotkey_combo=None,
                 notifier=winapi.show_toast, opener=None, log=print, finder=None, focuser=None):
        self.db_path = db_path
        self.port = port
        self.offline = offline
        self.want_hotkey = hotkey
        self.hotkey_combo = hotkey_combo  # None: use the saved setting (default ctrl+alt+t)
        self.want_popup = popup
        self.base = f"http://127.0.0.1:{port}"
        self.client = Client(self.base)
        self.notifier = notifier
        self.opener = opener or (lambda url: winapi.open_app_window(url, default_profile_dir()))
        self.finder = finder or winapi.find_windows
        self.focuser = focuser or winapi.focus_window
        self.log = log
        self.httpd = None
        self.backend = None
        self.hotkey = None
        self.started_at = datetime.now().replace(microsecond=0).isoformat()
        self.last_scan = 0.0
        self.last_scan_at = None
        self.last_error = None
        self._last_launch = 0.0
        self._lock = threading.Lock()

    # backend ---------------------------------------------------------------------------------
    def ensure_backend(self):
        """Connect to a running server, or host one in this process. Never starts a duplicate."""
        meta = probe(self.base)
        if meta:
            self.backend = "connected"
            self.log(f"[companion] using the TaskMaster server already running at {self.base} "
                     f"(workspace: {meta.get('workspace')})")
            if self.db_path and meta.get("workspace") != os.path.splitext(os.path.basename(self.db_path))[0]:
                self.log(f"[companion] note: that server uses workspace '{meta.get('workspace')}', not {self.db_path}")
            return meta
        if not port_free(self.port):
            raise BackendError(f"Port {self.port} is in use by something that isn't TaskMaster. "
                               f"Stop it or start the companion with --port.")
        from .server import make_server
        self.httpd, api = make_server(self.db_path, self.port, offline=self.offline)
        self.hosted_api = api
        threading.Thread(target=self.httpd.serve_forever, name="taskmaster-server", daemon=True).start()
        self.backend = "hosted"
        meta = probe(self.base, timeout=5)
        if not meta:
            raise BackendError("The TaskMaster server did not start.")
        self.log(f"[companion] started the TaskMaster server at {self.base} (workspace: {meta.get('workspace')}, "
                 f"mode: {meta.get('mode')}); it stops when the companion stops")
        return meta

    # popup ----------------------------------------------------------------------------------
    def open_popup(self):
        """Focus the existing companion window, or open one. Repeated presses never stack windows."""
        with self._lock:
            wins = self.finder()
            if wins:
                self.focuser(wins[0])
                return "focused"
            if time.monotonic() - self._last_launch < 5:
                return "launching"  # a window is already on its way; don't open a second one
            self._last_launch = time.monotonic()
            how = self.opener(f"{self.base}/companion.html")
            threading.Thread(target=self._focus_when_ready, name="taskmaster-focus", daemon=True).start()
            return f"opened ({how})"

    def _focus_when_ready(self, timeout=8.0):
        """A freshly launched window may open behind the active app; bring it forward once it exists."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            wins = self.finder()
            if wins:
                self.focuser(wins[0])
                return True
            time.sleep(0.25)
        return False

    def _on_hotkey(self):
        r = self.open_popup()
        self.log(f"[companion] {self.hotkey.label if self.hotkey else 'hotkey'}: {r}")

    # monitoring -------------------------------------------------------------------------------
    def status(self):
        hk = ("disabled" if not self.want_hotkey else "registered" if self.hotkey and self.hotkey.registered
              else "failed" if self.hotkey and self.hotkey.error else "starting")
        return {"pid": os.getpid(), "hotkey": hk, "hotkey_label": self.hotkey.label if self.hotkey else None,
                "hotkey_error": self.hotkey.error if self.hotkey else None,
                "backend": self.backend, "started_at": self.started_at, "last_scan_at": self.last_scan_at,
                "last_error": self.last_error, "version": 1}

    def tick(self, now=None):
        """One monitor step. Returns what it did (used by tests). Does nothing in the background
        unless monitoring is on and not paused."""
        now = now if now is not None else time.monotonic()
        done = {"heartbeat": False, "scanned": [], "notified": [], "skipped": None}
        try:
            prefs = self.client.post("companion/heartbeat", self.status())["prefs"]
            done["heartbeat"] = True
        except BackendError as e:
            self.last_error = str(e)
            done["skipped"] = f"backend: {e}"
            return done
        if not prefs["monitoring"] or prefs["paused"]:
            done["skipped"] = "monitoring off" if not prefs["monitoring"] else "monitoring paused"
            return done
        self.last_error = None
        try:
            if now - self.last_scan >= prefs["interval_minutes"] * 60 or not self.last_scan:
                access = self.client.get("settings/assistant")["assistant"]
                for p in self.client.get("workspace")["projects"]:
                    if not (access["access"] == "all" or (access["access"] == "selected" and p["id"] in access["projects"])):
                        continue  # Autonomy setting: only allowed projects are watched
                    srcs = self.client.get("sources", project=p["id"])["sources"]
                    if any(s["enabled"] for s in srcs):  # paused/removed sources are never scanned
                        r = self.client.post("sources/scan", {"project": p["id"], "background": True})
                        done["scanned"].append((p["id"], sum(x.get("new", 0) for x in r["scans"])))
                self.last_scan = now
                self.last_scan_at = datetime.now().replace(microsecond=0).isoformat()
            self.client.get("notices")  # the server applies its existing reminder/stale rules + dedupe
            if prefs["notifications"]:
                shown = []
                for n in self.client.get("companion/deliverable")["notices"]:
                    ok, detail = self.notifier(n["title"], n["body"], f"{self.base}/#{n['path']}")
                    if ok:
                        shown.append(n["id"])
                    else:
                        self.last_error = f"notification not shown: {detail}"
                        break  # don't retry the rest this tick; they stay undelivered
                if shown:
                    self.client.post("companion/delivered", {"ids": shown})
                done["notified"] = shown
        except BackendError as e:
            self.last_error = str(e)
            done["skipped"] = f"backend: {e}"
        return done

    # lifecycle --------------------------------------------------------------------------------
    def start_hotkey(self):
        if not self.want_hotkey:
            self.log("[companion] global hotkey disabled (--no-hotkey)")
            return
        combo = self.hotkey_combo
        if combo is None:
            try:
                prefs = self.client.get("settings/companion")["prefs"]
            except BackendError:
                prefs = {}
            if prefs.get("hotkey_enabled") is False:
                self.want_hotkey = False
                self.log("[companion] global hotkey disabled in Settings")
                return
            combo = prefs.get("hotkey") or "ctrl+alt+t"
        try:
            self.hotkey = winapi.HotkeyListener(self._on_hotkey, combo)
        except ValueError as e:
            self.log(f"[companion] hotkey {combo!r} is not valid ({e}); no hotkey registered")
            return
        self.hotkey.start()
        self.hotkey.ready.wait(5)
        if self.hotkey.registered:
            self.log(f"[companion] {self.hotkey.label} opens TaskMaster")
        else:
            self.log(f"[companion] hotkey NOT registered: {self.hotkey.error}. Pressing it does nothing in "
                     f"TaskMaster. Pick another with --hotkey (e.g. --hotkey ctrl+alt+k); running "
                     f"`python -m statetrace companion` again also opens the window.")

    def stop(self):
        if self.hotkey:
            self.hotkey.stop()
        if self.httpd:
            if not self.quit_requested():
                self.httpd.shutdown()
            self.httpd.server_close()
            self.log("[companion] stopped the TaskMaster server it was hosting (your data is unchanged)")

    def run(self, max_ticks=None):
        self.ensure_backend()
        self.start_hotkey()
        if self.want_popup:
            self.log(f"[companion] {self.open_popup()}")
        self.log("[companion] running. Close the compact window any time; press Ctrl+C here to quit the companion.")
        ticks, misses = 0, 0
        try:
            while max_ticks is None or ticks < max_ticks:
                r = self.tick()
                if r["scanned"] or r["notified"]:
                    self.log(f"[companion] scanned {r['scanned']}, notified {len(r['notified'])}")
                misses = misses + 1 if (r["skipped"] or "").startswith("backend") else 0
                if self.backend == "connected" and misses >= 2:
                    self.log("[companion] the TaskMaster server it was using has stopped; quitting")
                    break
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                # short sleeps keep Ctrl+C and the Quit button responsive
                for _ in range(TICK_SECONDS):
                    if self.quit_requested():
                        raise KeyboardInterrupt
                    time.sleep(1)
        except KeyboardInterrupt:
            self.log("[companion] quitting")
        finally:
            self.stop()

    def quit_requested(self):
        ev = getattr(getattr(self, "hosted_api", None), "shutdown_event", None)
        return bool(ev and ev.is_set())


def main(db_path, port=8765, offline=False, hotkey=True, popup=True, hotkey_combo=None):
    lock = winapi.SingleInstance()
    if lock.already_running:
        # A companion is already running: just bring its window up and exit.
        c = Companion(db_path, port, offline, hotkey=False, popup=True, log=print)
        if not probe(c.base):
            print(f"[companion] another companion is running but its server at {c.base} is not reachable.")
            return 1
        print(f"[companion] already running; {c.open_popup()}")
        return 0
    try:
        Companion(db_path, port, offline, hotkey=hotkey, popup=popup, hotkey_combo=hotkey_combo).run()
    except BackendError as e:
        print(f"[companion] {e}")
        return 1
    finally:
        lock.release()
    return 0

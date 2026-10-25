"""Server-side background worker (runs only in live mode, inside the TaskMaster server process).

1. Offline sync: updates saved while Nemotron was unreachable are applied, oldest first, through
   the normal engine + validator once Nebius answers again (checked every minute while anything
   is queued). These are the user's own submitted updates, so this runs regardless of autonomy.
2. Automatic reviews: after the state changes, Nemotron reviews the project *only if* the
   Autonomy setting allows that project. Reviews are opinions; they never change the state.
"""

import threading
import time

from . import assistant
from .llm import LLMError
from .store import Store

SYNC_EVERY = 60


class Background(threading.Thread):
    def __init__(self, api, write_lock):
        super().__init__(name="taskmaster-background", daemon=True)
        self.api = api
        self.lock = write_lock
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.reviews = {}  # project -> trigger
        self.last_sync = 0.0
        self.log = []

    def request_review(self, project, trigger="after update"):
        self.reviews[project] = trigger
        self.wake.set()

    def stop(self):
        self.stopping.set()
        self.wake.set()

    def _note(self, msg):
        self.log = (self.log + [f"{time.strftime('%H:%M:%S')} {msg}"])[-20:]

    def run_reviews(self):
        while self.reviews and not self.stopping.is_set():
            project, trigger = self.reviews.popitem()
            store = Store(self.api.db_path)
            try:
                if not assistant.allowed(assistant.access_prefs(store), project):
                    continue
                try:
                    assistant.review(store, project, self.api.llm, trigger=trigger)
                    self._note(f"reviewed {project} ({trigger})")
                except LLMError as e:
                    self._note(f"review of {project} failed: {str(e)[:80]}")
            finally:
                store.close()

    def run_sync(self):
        store = Store(self.api.db_path)
        try:
            queued = any(store.retryable_pending(p) for p in store.projects())
        finally:
            store.close()
        if not queued:
            return
        with self.lock:
            r = self.api.sync_now()
        if r.get("last_synced"):
            self._note(f"synced {len(r['last_synced'])} queued update(s)")

    def run(self):
        while not self.stopping.is_set():
            self.wake.wait(timeout=10)
            self.wake.clear()
            if self.stopping.is_set():
                break
            try:
                self.run_reviews()
                if time.monotonic() - self.last_sync >= SYNC_EVERY:
                    self.last_sync = time.monotonic()
                    self.run_sync()
            except Exception as e:  # never let the worker die silently; record and continue
                self._note(f"background error: {e!r}")
                print(f"[taskmaster] background error: {e!r}", flush=True)

import os

from . import assistant, ingest, monitoring, proposals, reminders, synthesis
from . import view as V
from .ask import QUICK_QUESTIONS, answer
from .engine import StateEngine
from .llm import LLMError, NebiusClient, retryable
from .schema import ALL_SOURCES, VERIFIABLE_SOURCES
from .store import Store, now_ts
from .summary import STALE_DAYS, HEALTH_RULES, evidence_index, project_summary, transition_detail, workspace_summary


class ApiError(Exception):
    def __init__(self, message, status=400, extra=None):
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


def slugify(name):
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:48] or "project"


class Api:
    def __init__(self, db_path, llm=None, llm_error=None, mode="live", workspace=None):
        self.db_path = db_path
        self.llm = llm
        self.llm_error = llm_error
        self.mode = mode  # live | offline | read_only | snapshot
        self.workspace = workspace or os.path.splitext(os.path.basename(db_path))[0]
        self.on_new_state = None   # set by the server: queue an automatic review when autonomy allows
        self.on_shutdown = None    # set by the server: stop cleanly
        self.sync_status = {"online": None, "last_check": None, "last_synced": [], "running": False}

    def _store(self):
        return Store(self.db_path)

    def _require_project(self, store, project):
        if not project:
            raise ApiError("No project selected.")
        if project not in store.projects():
            raise ApiError(f"There is no project called {project!r} in this workspace.", 404)

    # reads ---------------------------------------------------------------------------------
    def meta(self):
        return {
            "product": "TaskMaster",
            "mode": self.mode,
            "workspace": self.workspace,
            "is_demo": "demo" in self.workspace.lower(),
            "can_write": self.mode in ("live", "offline") and self.llm is not None,
            "model": getattr(self.llm, "name", None),
            "model_error": self.llm_error,
            "base_url": getattr(self.llm, "base_url", None),
            "sources": ALL_SOURCES,
            "verifiable_sources": sorted(VERIFIABLE_SOURCES),
            "quick_questions": QUICK_QUESTIONS,
            "stale_days": STALE_DAYS,
            "rules": HEALTH_RULES,
            "assistant": self.mode == "live" and self.llm is not None,
        }

    def workspace_summary(self, now=None):
        store = self._store()
        try:
            return workspace_summary(store, now)
        finally:
            store.close()

    def project(self, project, now=None):
        store = self._store()
        try:
            self._require_project(store, project)
            state = store.latest_state(project)
            view = V.build_view(state)
            from datetime import datetime
            when = datetime.fromisoformat(now) if now else None
            return {"summary": project_summary(store, project, now), "state": state, "view": view,
                    "milestones": reminders.milestones_with_status(store, project, when),
                    "pending_imports": len(store.import_items(project, "pending")),
                    "failed_imports": len(store.import_items(project, "failed"))}
        finally:
            store.close()

    def state(self, project, version):
        store = self._store()
        try:
            self._require_project(store, project)
            state = store.state_at(project, int(version))
            if state is None:
                raise ApiError(f"Version {version} does not exist.", 404)
            return {"state": state, "view": V.build_view(state)}
        finally:
            store.close()

    def events(self, project):
        store = self._store()
        try:
            self._require_project(store, project)
            return {"events": store.events(project), "transitions": store.transitions(project)}
        finally:
            store.close()

    def evidence(self, project):
        store = self._store()
        try:
            self._require_project(store, project)
            return {"evidence": evidence_index(store, project)}
        finally:
            store.close()

    def transition(self, project, event_id):
        store = self._store()
        try:
            self._require_project(store, project)
            detail = transition_detail(store, project, event_id)
            if detail is None:
                raise ApiError(f"Evidence {event_id} does not exist.", 404)
            return detail
        finally:
            store.close()

    def why(self, project, query):
        store = self._store()
        try:
            self._require_project(store, project)
            return {"text": V.explain(store.latest_state(project), store.events_by_id(project), query or "")}
        finally:
            store.close()

    def activity(self, limit=80):
        store = self._store()
        try:
            rows = []
            for p in store.projects():
                name = store.project_name(p)
                trans = {t["event_id"]: t for t in store.transitions(p)}
                for e in store.events(p):
                    t = trans.get(e["id"])
                    applied = [a for a in (t["applied"] if t else []) if a["op"] != "NOOP"]
                    rows.append({**e, "project_name": name, "changes": len(applied),
                                 "ops": sorted({a["op"] for a in applied}),
                                 "rejected": len(t["rejected"]) if t else 0,
                                 "error": t["error"] if t else None})
            rows.sort(key=lambda r: r["recorded_at"] + r["occurred_at"], reverse=True)
            return {"activity": rows[:limit]}
        finally:
            store.close()

    def ask(self, project, question, now=None):
        if not (question or "").strip():
            raise ApiError("Ask a question about the project.")
        store = self._store()
        try:
            self._require_project(store, project)
            if self.mode == "live" and self.llm is not None:
                return assistant.answer(store, project, question, self.llm, now=now)  # Nemotron first
            out = answer(store, project, question, llm=None, now=now)
            out["source"] = "stored"
            return out
        finally:
            store.close()

    # writes --------------------------------------------------------------------------------
    def _check_writable(self):
        if self.mode in ("read_only", "snapshot"):
            raise ApiError("This is a read-only demo. Run TaskMaster locally to record updates.", 403)
        if self.llm is None:
            raise ApiError("The state engine is not connected: " + (self.llm_error or "no model configured")
                           + ". Add NEBIUS_API_KEY to .env and restart.", 503)

    def create_project(self, name):
        self._check_local_write()
        name = (name or "").strip()
        if not name:
            raise ApiError("Give the project a name.")
        store = self._store()
        try:
            pid = slugify(name)
            store.set_project_name(pid, name)
            return {"id": pid, "name": name}
        finally:
            store.close()

    def load_sample(self):
        """Load the FFT sample project with hand-written scripted operations (no API key needed).
        It is labelled as sample data, and its transitions name the scripted engine, not a model."""
        self._check_local_write()
        import json as _json
        from .llm import ScriptedLLM
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "demo", "fft_scenario.json"), encoding="utf-8") as fh:
            sc = _json.load(fh)
        store = self._store()
        try:
            pid = sc["project"]
            if store.events(pid):
                raise ApiError("The sample project is already in this workspace.", 409)
            store.set_project_name(pid, sc.get("name", pid))
            store.set_project_sample(pid, True)
            engine = StateEngine(store, ScriptedLLM.from_file(os.path.join(root, "demo", "scripted_ops.json")))
            for ev in sc["events"]:
                engine.ingest(pid, ev["text"], ev["source"], ev.get("event_type"), ev["occurred_at"], ev.get("ref"))
            return {"id": pid, "name": store.project_name(pid), "events": len(sc["events"]),
                    "engine": "scripted (recorded operations, not live Nemotron)"}
        finally:
            store.close()

    def add_event(self, project, text, source="note", occurred_at=None, ref=None, event_type=None):
        self._check_writable()
        if not (text or "").strip():
            raise ApiError("Write the update first: one line is enough.")
        if source not in ALL_SOURCES:
            raise ApiError(f"Unknown evidence source {source!r}.")
        store = self._store()
        try:
            if project not in store.projects():
                raise ApiError("Create the project first.", 404)
            try:
                r = StateEngine(store, self.llm).ingest(project, text, source, event_type or None,
                                                        occurred_at or None, ref or None)
            except ValueError as e:
                raise ApiError(f"That timestamp could not be read ({e}).")
            detail = transition_detail(store, project, r.event["id"])
            detail["summary"] = project_summary(store, project)
            detail["queued_offline"] = bool(r.error and retryable(r.error))
            detail["queued_total"] = len(store.retryable_pending(project))
            if not r.error and self.on_new_state:
                self.on_new_state(project, "after update")
            return detail
        finally:
            store.close()

    def retry(self, project):
        self._check_writable()
        store = self._store()
        try:
            self._require_project(store, project)
            results = StateEngine(store, self.llm).process_pending(project)
            return {"processed": [r.event["id"] for r in results],
                    "failed": [r.event["id"] for r in results if r.error]}
        finally:
            store.close()

    # assistant (Nemotron reviews), autonomy, priority, sync, shutdown ---------------------------
    def latest_review(self, project):
        def run(store):
            self._require_project(store, project)
            r = store.latest_review(project)
            last_error = store.latest_review(project, successful=False)
            return {"review": r, "current_version": store.latest_state(project)["version"],
                    "last_error": last_error["error"] if last_error and last_error.get("error") and
                    (not r or last_error["id"] > r["id"]) else None}
        return self._with(run)

    def catch_up(self, project, run=False, force=False):
        """GET: the cached Nemotron catch-up for the current version, else the deterministic one (fast).
        POST (run=True): ask Nemotron now; falls back to the deterministic one, clearly labelled."""
        live = self.mode == "live" and self.llm is not None
        if run:
            self._check_writable()

        def run_(store):
            self._require_project(store, project)
            out = assistant.catch_up(store, project, self.llm if live else None, force=bool(force), use_model=bool(run) and live)
            out["nemotron_available"] = live
            return out
        return self._with(run_)

    def review(self, project, force=False):
        self._check_writable()

        def run(store):
            self._require_project(store, project)
            try:
                return assistant.review(store, project, self.llm, trigger="manual", force=bool(force))
            except LLMError as e:
                raise ApiError(f"Nemotron couldn't review right now ({str(e)[:160]}). "
                               "Your last review is still shown.", 503)
        return self._with(run)

    def assistant_settings(self):
        return self._with(lambda store: {"assistant": assistant.access_prefs(store),
                                         "priority_rules": __import__("statetrace.priority", fromlist=["RULES"]).RULES})

    def set_assistant_settings(self, access=None, projects=None):
        self._check_local_write()

        def run(store):
            try:
                p = assistant.set_access(store, access, projects)
            except ValueError as e:
                raise ApiError(str(e))
            # background monitoring follows autonomy: off means the companion does nothing in the background
            monitoring.set_companion_prefs(store, {"monitoring": p["access"] != "off"})
            return {"assistant": p, "companion": monitoring.companion_prefs(store)}
        return self._with(run)

    def set_priority(self, project, priority):
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            try:
                store.set_project_priority(project, priority)
            except ValueError as e:
                raise ApiError(str(e))
            return {"project": project, "priority": priority}
        return self._with(run)

    def sync(self):
        def run(store):
            queued = {p: len(store.retryable_pending(p)) for p in store.projects()}
            return {**self.sync_status, "queued": {k: v for k, v in queued.items() if v},
                    "queued_total": sum(queued.values()),
                    "model": getattr(self.llm, "name", None), "assistant": self.mode == "live" and self.llm is not None}
        return self._with(run)

    def sync_now(self):
        """Apply updates that were saved while Nemotron was unreachable (oldest first)."""
        self._check_writable()
        from datetime import datetime
        if self.sync_status.get("running"):
            return self.sync()
        self.sync_status["running"] = True
        try:
            online = bool(getattr(self.llm, "ping", lambda: True)())
            self.sync_status.update(online=online, last_check=datetime.now().replace(microsecond=0).isoformat())
            done = []
            if online:
                store = self._store()
                try:
                    for p in store.projects():
                        engine, applied = StateEngine(store, self.llm), False
                        for e in store.retryable_pending(p):  # oldest first; others need the user
                            r = engine.process(p, e)
                            if r.error and retryable(r.error):
                                break  # still unreachable: keep order, try again later
                            if not r.error:
                                done.append(f"{p}:{e['id']}")
                                applied = True
                        if applied and self.on_new_state:
                            self.on_new_state(p, "after sync")
                finally:
                    store.close()
            self.sync_status["last_synced"] = done
        finally:
            self.sync_status["running"] = False
        return self.sync()

    # Yosys synthesis skill ----------------------------------------------------------------------
    def _synth(self, fn):
        def run(store):
            try:
                return fn(store)
            except synthesis.SynthesisError as e:
                raise ApiError(str(e), 400, {"diagnostics": e.diagnostics})
        return self._with(run)

    def synth_overview(self, project):
        def run(store):
            self._require_project(store, project)
            return synthesis.overview(store, project)
        return self._synth(run)

    def synth_import(self, project, filename, content, review=True):
        self._check_local_write()
        if not isinstance(content, str):
            raise ApiError("Send the report as text.")
        data = content.encode("utf-8")

        def run(store):
            self._require_project(store, project)
            llm = self.llm if self.mode in ("live", "offline") else None
            out = synthesis.import_report(store, project, filename, data, llm, review=bool(review))
            if not out["duplicate"] and not out["transition_error"] and not out["proposal"] and self.on_new_state:
                self.on_new_state(project, "after synthesis import")
            return out
        return self._synth(run)

    # review-before-commit -------------------------------------------------------------------
    def proposals(self, project):
        def run(store):
            self._require_project(store, project)
            return {"proposals": proposals.pending(store, project)}
        return self._with(run)

    def proposal_action(self, project, event_id, action, reason=""):
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            try:
                if action == "apply":
                    out = proposals.apply(store, project, event_id)
                    if out["applied"] and self.on_new_state:
                        self.on_new_state(project, "after applying a reviewed change")
                    return out
                return proposals.discard(store, project, event_id, reason)
            except proposals.ProposalError as e:
                raise ApiError(str(e), 409)
        return self._with(run)

    def synth_compare(self, project, run_id, baseline_id):
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            try:
                return synthesis.compare_runs(store, project, int(run_id), int(baseline_id))
            except (TypeError, ValueError) as e:
                if isinstance(e, synthesis.SynthesisError):
                    raise
                raise ApiError("Choose a run and a baseline.")
        return self._synth(run)

    def synth_explain(self, project, analysis_id):
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            llm = self.llm if self.mode == "live" else None
            return synthesis.explain(store, project, int(analysis_id), llm)
        return self._synth(run)

    def synth_constraints(self, project, values):
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            return {"constraints": synthesis.set_constraints(store, project, values)}
        return self._synth(run)

    def synth_excerpt(self, project, run_id):
        def run(store):
            self._require_project(store, project)
            return synthesis.excerpt(store, project, run_id)
        return self._synth(run)

    def shutdown(self):
        if self.mode not in ("live", "offline", "read_only"):
            raise ApiError("Not available here.", 403)
        if not self.on_shutdown:
            raise ApiError("This server can't be stopped from the browser; close its console window.", 409)
        self.on_shutdown()
        return {"stopping": True}

    def _check_local_write(self):
        """Writes that need no model (milestones, sources, settings): blocked only when read-only."""
        if self.mode in ("read_only", "snapshot"):
            raise ApiError("This is a read-only instance. Run TaskMaster locally to change it.", 403)

    def _with(self, fn):
        store = self._store()
        try:
            return fn(store)
        except ingest.IngestError as e:
            raise ApiError(str(e))
        finally:
            store.close()

    # sources & imports ------------------------------------------------------------------------
    def sources(self, project):
        def run(store):
            self._require_project(store, project)
            items = store.import_items(project)
            counts = {s: sum(1 for i in items if i["status"] == s) for s in ("pending", "accepted", "skipped", "failed")}
            return {"sources": store.sources(project), "items": items, "counts": counts,
                    "can_accept": self.llm is not None and self.mode in ("live", "offline")}
        return self._with(run)

    def add_source(self, project, path, branch=None, wsl=False, auto_accept=False):
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            return ingest.add_source(store, project, "git", {"path": path, "branch": branch, "wsl": wsl},
                                     auto_accept=bool(auto_accept))
        return self._with(run)

    def update_source(self, source_id, enabled=None, auto_accept=None):
        self._check_local_write()

        def run(store):
            if not store.get_source(int(source_id)):
                raise ApiError("That source no longer exists.", 404)
            fields = {k: bool(v) for k, v in (("enabled", enabled), ("auto_accept", auto_accept)) if v is not None}
            return store.update_source(int(source_id), **fields)
        return self._with(run)

    def remove_source(self, source_id):
        self._check_local_write()
        return self._with(lambda store: store.remove_source(int(source_id)) or {"removed": int(source_id)})

    def scan(self, project, source_id=None, background=False):
        """`background` scans (companion monitor) only stage: never auto-accept, and notify once."""
        self._check_local_write()

        def run(store):
            self._require_project(store, project)
            engine = StateEngine(store, self.llm) if self.llm is not None and not background else None
            out = []
            for s in store.sources(project):
                if source_id is None or s["id"] == int(source_id):
                    try:
                        out.append(ingest.scan_source(store, s, engine, notify=background))
                    except ingest.IngestError as e:
                        out.append({"source": s["id"], "new": 0, "error": str(e)})
            return {"scans": out}
        return self._with(run)

    def accept_imports(self, project, ids):
        self._check_writable()
        return self._with(lambda store: {"results": ingest.accept(store, StateEngine(store, self.llm), project,
                                                                  [int(i) for i in ids or []])})

    def retry_imports(self, project, ids):
        self._check_writable()
        return self._with(lambda store: {"results": ingest.retry(store, StateEngine(store, self.llm), project,
                                                                 [int(i) for i in ids or []])})

    def skip_imports(self, project, ids, restore=False):
        self._check_local_write()
        return self._with(lambda store: {"changed": ingest.skip(store, project, [int(i) for i in ids or []], restore)})

    # milestones, notices, notification settings -------------------------------------------------
    def milestones(self, project=None, now=None):
        from datetime import datetime
        when = datetime.fromisoformat(now) if now else None
        return self._with(lambda store: {"milestones": reminders.milestones_with_status(store, project, when),
                                         "rules": reminders.RISK_RULES})

    def add_milestone(self, project, title, due_at=None, reminders_=None, notes=None, source_claim=None):
        self._check_local_write()
        title = (title or "").strip()
        if not title:
            raise ApiError("Give the milestone a title.")

        def run(store):
            self._require_project(store, project)
            try:
                return store.add_milestone(project, title[:200], due_at or None, reminders_ or [], notes, "user", True,
                                           source_claim)
            except ValueError as e:
                raise ApiError(f"That date could not be read ({e}).")
        return self._with(run)

    def update_milestone(self, mid, **fields):
        self._check_local_write()

        def run(store):
            if not store.get_milestone(int(mid)):
                raise ApiError("That milestone no longer exists.", 404)
            if fields.get("status") in ("done", "dropped"):
                fields["closed_at"] = now_ts()
            elif fields.get("status") == "open":
                fields["closed_at"] = None
            if fields.get("status") not in (None, "open", "done", "dropped"):
                raise ApiError("Status must be open, done or dropped.")
            try:
                return store.update_milestone(int(mid), **fields)
            except ValueError as e:
                raise ApiError(f"That date could not be read ({e}).")
        return self._with(run)

    def delete_milestone(self, mid):
        self._check_local_write()
        return self._with(lambda store: store.delete_milestone(int(mid)) or {"deleted": int(mid)})

    def notices(self):
        def run(store):
            if self.mode not in ("read_only", "snapshot"):
                reminders.generate_notices(store)
            return reminders.notices_for_delivery(store)
        return self._with(run)

    def dismiss_notice(self, notice_id, delivered_only=False):
        self._check_local_write()
        return self._with(lambda store: store.mark_notice(int(notice_id), delivered=True, dismissed=not delivered_only)
                          or {"ok": True})

    # desktop companion ------------------------------------------------------------------------
    def companion_settings(self):
        return self._with(lambda store: {"prefs": monitoring.companion_prefs(store),
                                         "status": monitoring.companion_status(store),
                                         "reminders": reminders.prefs(store),
                                         "assistant": assistant.access_prefs(store)})

    def set_companion_settings(self, update):
        self._check_local_write()

        def run(store):
            try:
                prefs = monitoring.set_companion_prefs(store, update or {})
            except (ValueError, TypeError) as e:
                raise ApiError(f"Those companion settings are not valid ({e}).")
            # one source of truth: background monitoring on/off mirrors Autonomy (off <-> on for all)
            if "monitoring" in (update or {}):
                cur = assistant.access_prefs(store)["access"]
                if update["monitoring"] and cur == "off":
                    assistant.set_access(store, "all")
                elif not update["monitoring"]:
                    assistant.set_access(store, "off")
            return {"prefs": prefs, "status": monitoring.companion_status(store),
                    "assistant": assistant.access_prefs(store)}
        return self._with(run)

    def companion_heartbeat(self, status):
        self._check_local_write()
        return self._with(lambda store: {"status": monitoring.record_status(store, status),
                                         "prefs": monitoring.companion_prefs(store)})

    def companion_brief(self, project):
        def run(store):
            self._require_project(store, project)
            return monitoring.companion_brief(store, project)
        return self._with(run)

    def companion_deliverable(self):
        return self._with(lambda store: monitoring.deliverable(store))

    def companion_delivered(self, ids):
        self._check_local_write()

        def run(store):
            tests = {n["id"] for n in store.notices() if n["kind"] == "test"}
            for i in ids or []:
                store.mark_notice(int(i), delivered=True, dismissed=int(i) in tests)
            return {"ok": True}
        return self._with(run)

    def companion_test_notification(self):
        self._check_local_write()
        return self._with(lambda store: {"created": store.add_notice(
            "-", "test", f"test:{now_ts()}", "Test notification", "requested from Settings")})

    def notification_prefs(self):
        return self._with(lambda store: reminders.prefs(store))

    def set_notification_prefs(self, update):
        self._check_local_write()

        def run(store):
            try:
                return reminders.set_prefs(store, update or {})
            except (ValueError, TypeError) as e:
                raise ApiError(f"Those notification settings are not valid ({e}).")
        return self._with(run)


def make_api(db_path, offline=False, read_only=False, workspace=None):
    from .llm import LLMError, ScriptedLLM
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if offline:
        llm = ScriptedLLM.from_file(os.path.join(root, "demo", "scripted_ops.json"))
        return Api(db_path, llm, None, "read_only" if read_only else "offline", workspace)
    if read_only:
        return Api(db_path, None, None, "read_only", workspace)
    try:
        return Api(db_path, NebiusClient(), None, "live", workspace)
    except LLMError as e:
        return Api(db_path, None, str(e), "live", workspace)

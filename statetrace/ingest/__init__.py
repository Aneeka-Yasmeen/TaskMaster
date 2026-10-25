"""Automatic evidence sources.

Workflow: a source is *scanned* into staged import items (no effect on project state); the
user reviews them and *accepts* (appended as evidence and run through the state engine) or
*skips* them. Failed state updates keep their evidence and can be retried. A source may opt
into auto-accept; it is off by default.

Each source kind implements `validate(config) -> config` and `scan(config, known_ids) -> items`,
where an item is {external_id, occurred_at, title, text, source, ref, meta}. Adding GitHub, CI or
test-report sources means adding a module with those two functions to KINDS.
"""

from ..engine import StateEngine
from ..store import now_ts
from . import git

KINDS = {"git": git}


class IngestError(RuntimeError):
    pass


def add_source(store, project, kind, config, auto_accept=False):
    if kind not in KINDS:
        raise IngestError(f"Unknown source kind {kind!r}.")
    try:
        config = KINDS[kind].validate(config)
    except git.GitError as e:
        raise IngestError(str(e))
    for s in store.sources(project):
        if s["kind"] == kind and s["config"].get("path") == config.get("path") and s["config"].get("branch") == config.get("branch"):
            raise IngestError("This repository and branch is already a source for this project.")
    return store.add_source(project, kind, config, auto_accept)


def scan_source(store, source, engine=None, notify=False):
    """Stage new items. Dedupes per source and against evidence already in the project (same ref).
    `notify` (used by background monitoring) records one deduplicated notice per batch of new items."""
    if not source["enabled"]:
        return {"source": source["id"], "new": 0, "skipped_paused": True}
    mod = KINDS[source["kind"]]
    try:
        items = mod.scan(source["config"], store.known_external_ids(source["id"]))
    except git.GitError as e:
        store.update_source(source["id"], last_scan_at=now_ts(), last_error=str(e))
        raise IngestError(str(e))
    refs = {e["ref"] for e in store.events(source["project"]) if e.get("ref")}
    new = []
    for item in items:
        if item.get("ref") in refs:
            continue  # already recorded as evidence (e.g. typed in by hand)
        if store.stage_item(source, item):
            new.append(item["external_id"])
    store.update_source(source["id"], last_scan_at=now_ts(), last_error=None)
    if notify and new:
        n = len(store.import_items(source["project"], "pending"))
        store.add_notice(source["project"], "imports", f"imports:{source['id']}:{new[-1]}",
                         f"{n} new commit{'s' if n != 1 else ''} waiting for review",
                         f"background scan of source {source['id']} staged {len(new)} commit(s)", {"source": source["id"]})
    accepted = []
    if source["auto_accept"] and new and engine is not None:
        ids = [i["id"] for i in store.import_items(source["project"], "pending") if i["external_id"] in set(new)]
        accepted = accept(store, engine, source["project"], ids)
    return {"source": source["id"], "new": len(new), "auto_accepted": accepted}


def accept(store, engine: StateEngine, project, item_ids):
    """Append each item as evidence (oldest first) and run the state transition."""
    items = [store.get_item(i) for i in item_ids]
    items = sorted([i for i in items if i and i["project"] == project and i["status"] == "pending"],
                   key=lambda i: (i["occurred_at"], i["id"]))
    results = []
    for item in items:
        p = item["payload"]
        result = engine.ingest(project, p["text"], p.get("source", "note"), "import", item["occurred_at"], p.get("ref"))
        if result.error:
            store.set_item(item["id"], "failed", result.event["id"], result.error)
        else:
            store.set_item(item["id"], "accepted", result.event["id"])
        results.append({"item": item["id"], "event": result.event["id"], "error": result.error})
    return results


def retry(store, engine, project, item_ids):
    """Re-run the state transition for failed items (their evidence already exists)."""
    results = []
    for item in (store.get_item(i) for i in item_ids):
        if not item or item["project"] != project or item["status"] != "failed" or not item["event_id"]:
            continue
        event = store.get_event(project, item["event_id"])
        r = engine.process(project, event)
        store.set_item(item["id"], "failed" if r.error else "accepted", error=r.error)
        results.append({"item": item["id"], "event": event["id"], "error": r.error})
    return results


def skip(store, project, item_ids, restore=False):
    n = 0
    for item in (store.get_item(i) for i in item_ids):
        if item and item["project"] == project and item["status"] == ("skipped" if restore else "pending"):
            store.set_item(item["id"], "pending" if restore else "skipped")
            n += 1
    return n

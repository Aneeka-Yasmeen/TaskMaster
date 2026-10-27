import json
import os
import shutil
from datetime import datetime

from .api import Api
from .ask import QUICK_QUESTIONS

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))


def export_snapshot(db_path, out_dir, workspace=None):
    now = datetime.now().replace(microsecond=0).isoformat()
    api = Api(db_path, llm=None, mode="snapshot", workspace=workspace)
    if os.path.isdir(out_dir):  # clear contents (the folder itself may be open in a shell/server)
        for name in os.listdir(out_dir):
            path = os.path.join(out_dir, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    shutil.copytree(STATIC, out_dir, dirs_exist_ok=True)
    for local_only in ("companion.html", os.path.join("js", "companion.js")):  # needs the local server
        path = os.path.join(out_dir, local_only)
        if os.path.exists(path):
            os.remove(path)
    data = os.path.join(out_dir, "data")
    meta = api.meta()
    meta["snapshot_at"] = now
    _write(os.path.join(data, "meta.json"), meta)
    ws = api.workspace_summary(now)
    _write(os.path.join(data, "workspace.json"), ws)
    _write(os.path.join(data, "activity.json"), api.activity(limit=200))
    files = 3
    for p in ws["projects"]:
        pid = p["id"]
        base = os.path.join(data, "p", pid)
        proj = api.project(pid, now)
        _write(os.path.join(base, "project.json"), proj)
        ev = api.events(pid)
        _write(os.path.join(base, "events.json"), ev)
        _write(os.path.join(base, "evidence.json"), api.evidence(pid))
        for v in range(0, proj["state"]["version"] + 1):
            _write(os.path.join(base, "state", f"{v}.json"), api.state(pid, v))
        for e in ev["events"]:
            _write(os.path.join(base, "transition", f"{e['id']}.json"), api.transition(pid, e["id"]))
        answers = {q: api.ask(pid, q, now) for q in QUICK_QUESTIONS}
        _write(os.path.join(base, "ask.json"), answers)
        why = {cid: api.why(pid, cid)["text"] for cid in proj["state"]["claims"]}
        _write(os.path.join(base, "why.json"), why)
        # a saved Nemotron catch-up for this version if one exists (labelled with its time), else the stored one
        _write(os.path.join(base, "catchup.json"), api.catch_up(pid))
        files += 8 + proj["state"]["version"] + len(ev["events"])
    with open(os.path.join(out_dir, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace("<!--TM_MODE-->", '<script>window.TM_SNAPSHOT = "data";</script>')
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    return {"out": out_dir, "projects": len(ws["projects"]), "files": files, "snapshot_at": now}

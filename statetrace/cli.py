"""Command line interface: python -m statetrace <command> ..."""

import argparse
import json
import os
import sys
import time

from . import view as V
from .ask import QUICK_QUESTIONS, answer
from .engine import StateEngine
from .llm import LLMError, NebiusClient, ScriptedLLM, load_dotenv
from .schema import ALL_SOURCES
from .store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "demo", "fft_scenario.json")
SCRIPT = os.path.join(ROOT, "demo", "scripted_ops.json")


def make_llm(offline=False):
    if offline:
        return ScriptedLLM.from_file(SCRIPT)
    return NebiusClient()


def _llm_or_none():
    try:
        return NebiusClient()
    except LLMError:
        return None


def cmd_add(args, store):
    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            body = fh.read()[:6000]
        text = f"{text}\n--- {os.path.basename(args.file)} ---\n{body}" if text else body
    llm = make_llm(args.offline)
    engine = StateEngine(store, llm)
    t0 = time.perf_counter()
    r = engine.ingest(args.project, text, args.source, args.type, args.at, args.ref or args.file)
    print(f"{r.event['id']} recorded ({r.event['source']}, {r.event['occurred_at']}) -> state v{r.state['version']}"
          f" in {int((time.perf_counter() - t0) * 1000)} ms")
    print("\n".join(r.summary_lines()))


def cmd_state(args, store):
    state = store.latest_state(args.project)
    if args.json:
        print(json.dumps(V.build_view(state), indent=1))
    else:
        print(V.where_am_i(V.build_view(state), now=args.now))


def cmd_ask(args, store):
    r = answer(store, args.project, args.question, llm=_llm_or_none(), now=args.now)
    print(f"({r['mode']})\n{r['text']}")


def cmd_why(args, store):
    print(V.explain(store.latest_state(args.project), store.events_by_id(args.project), args.target))


def cmd_history(args, store):
    trans = {}
    for t in store.transitions(args.project):
        trans[t["event_id"]] = t
    for e in store.events(args.project):
        print(f"{e['id']:>4} {e['occurred_at']} [{e['source']}] {e['text'][:110]}")
        t = trans.get(e["id"])
        if not t:
            print("       (not processed)")
        elif t["error"]:
            print(f"       ! {t['error'][:120]}")
        else:
            for a in t["applied"]:
                if a["op"] != "NOOP":
                    print(f"       {a['op']:<10} {a.get('claim') or a.get('contradiction')}"
                          f" {a.get('field') or ''} {(a.get('value') or a.get('description') or a.get('resolution') or a.get('reason') or '')[:70]}")
            for x in t["rejected"]:
                print(f"       REJECTED   {x['reason'][:100]}")


def cmd_diff(args, store):
    a = store.state_at(args.project, args.v1)
    b = store.state_at(args.project, args.v2)
    if a is None or b is None:
        sys.exit("unknown version")
    for c in V.diff_states(a, b):
        ident = c.get("claim") or c.get("contradiction")
        print(f"{c['kind']:<22} {ident:<5} {c.get('field') or ''}{'[' + c['key'] + ']' if c.get('key') else ''}"
              f" {c['value'][:90]}")


def cmd_rebuild(args, store):
    engine = StateEngine(store, make_llm(args.offline))
    for r in engine.rebuild(args.project):
        print(f"{r.event['id']} -> v{r.state['version']}")
        print("\n".join(r.summary_lines()))


def cmd_pending(args, store):
    engine = StateEngine(store, make_llm(args.offline))
    for r in engine.process_pending(args.project):
        print(f"{r.event['id']} -> v{r.state['version']}")
        print("\n".join(r.summary_lines()))


def cmd_demo(args, store):
    with open(SCENARIO, encoding="utf-8") as fh:
        scenario = json.load(fh)
    project = scenario["project"]
    if store.events(project):
        sys.exit(f"project {project!r} already has events in {store.path}; use another --db")
    llm = make_llm(args.offline)
    print(f"Engine: {llm.name}\n")
    engine = StateEngine(store, llm)
    for ev in scenario["events"]:
        r = engine.ingest(project, ev["text"], ev["source"], ev.get("event_type"), ev["occurred_at"], ev.get("ref"))
        print(f"{r.event['id']} {ev['occurred_at']} [{ev['source']}] {ev['text'][:100]}")
        print("\n".join(r.summary_lines()))
        print()
    now = scenario["checkpoints"][-1].get("now")
    for q in QUICK_QUESTIONS:
        print(f"\n>>> {q}")
        print(answer(store, project, q, now=now)["text"])


def cmd_eval(args, _store):
    from .evaluation import run_eval
    modes = ["engine"] + (["baseline"] if args.baseline else [])
    llm = make_llm(args.offline)
    if args.offline and args.baseline:
        sys.exit("the baseline needs a live model")
    runs, md, js = run_eval(args.scenario, llm, modes, args.runs, args.out)
    for r in runs:
        s = r["scores"]
        print(f"{r['mode']:<9} " + "  ".join(f"{k}={v['passed']}/{v['total']}" for k, v in s.items())
              + f"  unsupported_verified={r['counters']['max_unsupported_verified']}"
              + f"  mean_latency={r['latency_ms']['mean']}ms")
    print(f"\nreport: {md}\nraw:    {js}")


def cmd_models(args, _store):
    for m in NebiusClient().list_models():
        print(m)


def cmd_serve(args, _store):
    from .server import serve
    serve(args.db, args.port, offline=args.offline, read_only=args.read_only, host=args.host)


def cmd_sample(args, store):
    if args.project not in store.projects():
        sys.exit(f"no project {args.project!r} in {store.path}")
    store.set_project_sample(args.project, not args.off)
    print(f"{args.project}: {'real data' if args.off else 'labelled as sample data'}")


def cmd_name(args, store):
    store.set_project_name(args.project, args.name)
    print(f"{args.project} -> {args.name!r}")


def _shift(events, ends_ago_minutes):
    """Move a scenario so its last event lands `ends_ago_minutes` before now (keeps spacing)."""
    from datetime import datetime, timedelta
    last = max(datetime.fromisoformat(e["occurred_at"]) for e in events)
    target = datetime.now().replace(second=0, microsecond=0) - timedelta(minutes=ends_ago_minutes)
    delta = target - last
    return [dict(e, occurred_at=(datetime.fromisoformat(e["occurred_at"]) + delta).isoformat()) for e in events]


def cmd_seed(args, store):
    """Build the demo workspace: the FFT scenario plus demo/workspace/*.json, all run through the engine."""
    import glob
    scenarios = []
    with open(SCENARIO, encoding="utf-8") as fh:
        fft = json.load(fh)
    scenarios.append({"project": fft["project"], "name": fft.get("name", fft["project"]),
                      "events": fft["events"], "scripted": True})
    for path in sorted(glob.glob(os.path.join(ROOT, "demo", "workspace", "*.json"))):
        with open(path, encoding="utf-8") as fh:
            sc = json.load(fh)
        sc["events"] = _shift(sc["events"], sc.get("ends_ago_minutes", 60))
        scenarios.append(sc)
    llm = make_llm(args.offline)
    engine = StateEngine(store, llm)
    print(f"Engine: {llm.name}  ->  {store.path}\n")
    for sc in scenarios:
        if args.offline and not sc.get("scripted"):
            print(f"skip {sc['project']}: offline mode only has scripted operations for the FFT scenario")
            continue
        if store.events(sc["project"]):
            print(f"skip {sc['project']}: already has evidence in this database")
            continue
        store.set_project_name(sc["project"], sc["name"])
        store.set_project_sample(sc["project"], True)  # demo scenarios are synthetic; the UI says so
        print(f"== {sc['name']} ({len(sc['events'])} events)")
        for ev in sc["events"]:
            if ev.get("synth_report"):  # a real Yosys report from demo/yosys, imported like the UI does
                from . import synthesis
                with open(os.path.join(ROOT, "demo", "yosys", ev["synth_report"]), "rb") as fh:
                    out = synthesis.import_report(store, sc["project"], ev["synth_report"], fh.read(), llm,
                                                  occurred_at=ev["occurred_at"])
                err = out["transition_error"]
                print(f"  {out['event']['id']:>4} {ev['occurred_at'][:16]} [synthesis_report] {ev['synth_report']}"
                      + (f" error: {err[:80]}" if err else " imported"))
                continue
            r = engine.ingest(sc["project"], ev["text"], ev.get("source", "note"), ev.get("event_type"),
                              ev["occurred_at"], ev.get("ref"))
            n_ops = sum(1 for a in r.log["applied"] if a["op"] != "NOOP")
            status = f"error: {r.error[:80]}" if r.error else f"{n_ops} changes, {len(r.log['rejected'])} rejected"
            print(f"  {r.event['id']:>4} {ev['occurred_at'][:16]} [{ev.get('source', 'note')}] {status}"
                  f" ({r.latency_ms} ms)")
    print("\nDone. Start the dashboard with:  python -m statetrace --db", store.path, "serve")


def cmd_git_add(args, store):
    from . import ingest
    try:
        s = ingest.add_source(store, args.project, "git", {"path": args.path, "branch": args.branch, "wsl": args.wsl},
                              auto_accept=args.auto)
    except ingest.IngestError as e:
        sys.exit(f"cannot add source: {e}")
    print(f"source {s['id']}: {s['config']['path']} @ {s['config']['branch']}{' (WSL git)' if s['config']['wsl'] else ''}"
          f"{' auto-accept' if s['auto_accept'] else ''}")


def cmd_scan(args, store):
    from . import ingest
    engine = None
    for s in store.sources(args.project):
        if args.source and s["id"] != args.source:
            continue
        if s["auto_accept"] and engine is None:
            engine = StateEngine(store, make_llm(args.offline))
        try:
            r = ingest.scan_source(store, s, engine)
        except ingest.IngestError as e:
            print(f"source {s['id']}: error: {e}")
            continue
        print(f"source {s['id']}: {'paused' if r.get('skipped_paused') else str(r['new']) + ' new'}"
              + (f", {len(r['auto_accepted'])} auto-accepted" if r.get("auto_accepted") else ""))
    print("Review with:  python -m statetrace -p", args.project, "imports")


def cmd_imports(args, store):
    for i in store.import_items(args.project, args.status):
        extra = f" -> {i['event_id']}" if i["event_id"] else ""
        err = f"  ! {i['error'][:80]}" if i["error"] else ""
        print(f"{i['id']:>4} {i['status']:<8} {i['occurred_at'][:16]} {i['payload'].get('ref', '')} {i['title'][:70]}{extra}{err}")


def _ids(store, project, spec, status):
    if spec == ["all"]:
        return [i["id"] for i in store.import_items(project, status)]
    return [int(x) for x in spec]


def cmd_accept(args, store):
    from . import ingest
    engine = StateEngine(store, make_llm(args.offline))
    for r in ingest.accept(store, engine, args.project, _ids(store, args.project, args.ids, "pending")):
        print(f"item {r['item']} -> {r['event']}" + (f"  state update failed (evidence kept): {r['error'][:80]}" if r["error"] else ""))


def cmd_skip(args, store):
    from . import ingest
    print(ingest.skip(store, args.project, _ids(store, args.project, args.ids, "pending"), restore=False), "skipped")


def cmd_retry_imports(args, store):
    from . import ingest
    engine = StateEngine(store, make_llm(args.offline))
    for r in ingest.retry(store, engine, args.project, _ids(store, args.project, args.ids, "failed")):
        print(f"item {r['item']} ({r['event']}): {'ok' if not r['error'] else 'failed again: ' + r['error'][:80]}")


def cmd_milestone(args, store):
    from . import reminders
    if args.title:
        m = store.add_milestone(args.project, args.title, args.due, [int(x) for x in args.remind] if args.remind else [])
        print(f"milestone {m['id']}: {m['title']} due {m['due_at'] or '-'}")
    for m in reminders.milestones_with_status(store, args.project):
        flag = " AT RISK: " + "; ".join(m["reasons"]) if m["at_risk"] else ""
        print(f"{m['id']:>4} {m['state']:<11} {(m['due_at'] or '-')[:16]:<16} {m['title']}{flag}")


def cmd_companion(args, store):
    from .companion import main as companion_main
    store.close()  # the companion talks to the server over HTTP; it holds no DB connection itself
    sys.exit(companion_main(args.db, port=args.port, offline=args.offline, hotkey=not args.no_hotkey,
                            popup=not args.no_popup, hotkey_combo=args.hotkey))


def cmd_stop(args, store):
    """Stop a running TaskMaster (server and the companion hosting it) cleanly."""
    from .companion import BackendError, Client, probe
    store.close()
    base = f"http://127.0.0.1:{args.port}"
    if not probe(base):
        print(f"No TaskMaster is running on port {args.port}.")
        return
    try:
        Client(base).post("shutdown", {})
        print("TaskMaster is stopping. Your data is saved.")
    except BackendError as e:
        sys.exit(f"Could not stop it: {e}")


def _synth_llm(args):
    try:
        return make_llm(args.offline)
    except LLMError as e:
        print(f"(model not connected: {e}; the report is stored and applied when it is)")
        return None


def cmd_synth_import(args, store):
    from . import synthesis
    with open(args.file, "rb") as fh:
        data = fh.read(3_000_000)
    store.ensure_project(args.project)
    try:
        r = synthesis.import_report(store, args.project, os.path.basename(args.file), data, _synth_llm(args))
    except synthesis.SynthesisError as e:
        print(f"Could not import: {e}")
        for k, v in e.diagnostics.items():
            print(f"  {k}: {v}")
        sys.exit(2)
    run, p = r["run"], r["run"]["parsed"]
    if r["duplicate"]:
        print(f"Already imported as run #{run['id']} ({run['event_id']}); identical content (sha256 {run['sha256'][:12]}).")
        return
    print(f"Run #{run['id']} -> evidence {run['event_id']} ({p['format']}, {p['scope']}, sha256 {run['sha256'][:12]})")
    for k, v in p["metrics"].items():
        print(f"  {k}: {v}")
    for k, v in (p.get("derived") or {}).items():
        if v:
            print(f"  {k} (derived from cell names): {v}")
    for w in p["warnings"]:
        print(f"  note: {w}")
    if r["transition_error"]:
        print(f"  state update queued: {r['transition_error'][:100]}")


def cmd_synth_runs(args, store):
    from . import synthesis
    for r in synthesis.overview(store, args.project)["runs"]:
        m = r["metrics"] or {}
        print(f"#{r['id']:<3} {r['event_id']:<5} {r['imported_at'][:16]} {r['filename']:<32} cells={m.get('cells', '-')}"
              f" ff={(r['derived'] or {}).get('flip_flops', '-')} {r['library'] or ''}")


def cmd_synth_compare(args, store):
    from . import synthesis
    try:
        a = synthesis.compare_runs(store, args.project, args.run, args.baseline)
    except synthesis.SynthesisError as e:
        sys.exit(str(e))
    c = a["comparison"]
    print(f"Comparison #{a['id']}: run #{a['run_id']} vs baseline #{a['baseline_id']}")
    for r in c["metrics"]:
        pct = f"{r['pct']:+.2f}%" if r["pct"] is not None else (r["note"] or "n/a")
        print(f"  {r['label']:<42} {r['baseline']!s:>8} -> {r['current']!s:<8} {('%+g' % r['abs']) if r['abs'] is not None else 'n/a':>8}  {pct}")
    for t in [x for x in c["cell_types"] if x["status"] != "same"][:15]:
        print(f"  cell {t['type']:<30} {t['baseline']!s:>6} -> {t['current']!s:<6} {t['status']}")
    for x in a["checks"] or []:
        print(f"  constraint {x['label']} <= {x['limit']}: {x['status']}" + (f" ({x['note']})" if x["note"] else ""))
    for l in c["limitations"]:
        print(f"  limitation: {l}")
    print(f"Explain with Nemotron:  python -m statetrace -p {args.project} synth-explain {a['id']}")


def cmd_synth_explain(args, store):
    from . import synthesis
    a = synthesis.explain(store, args.project, args.analysis, _synth_llm(args))
    if a["error"]:
        print(f"Nemotron explanation unavailable: {a['error']}\n(the deterministic comparison is kept)")
        return
    x = a["analysis"]
    print(f"Nemotron ({a['model']}, {a['latency_ms']} ms) - model interpretation, not evidence\n{x['summary']}")
    for o in x["observations"]:
        print(f"  observed: {o['text']} {o['evidence']}")
    for h in x["hypotheses"]:
        print(f"  hypothesis ({h['confidence']}): {h['text']} {h['evidence']}")
    for n in x["evidence_needed"]:
        print(f"  evidence needed: {n}")
    if x["next_experiment"]:
        n = x["next_experiment"]
        print(f"  NEXT EXPERIMENT: {n['title']} - {n['how']} (expect: {n['expected_signal']}) {n['evidence']}")
    if x["invented_citations"]:
        print(f"  [validator] removed citations to non-existent evidence: {x['invented_citations']}")


def cmd_export(args, _store):
    from .export import export_snapshot
    r = export_snapshot(args.db, args.out, args.workspace)
    print(f"Exported {r['projects']} projects ({r['files']} files) to {r['out']}  (snapshot {r['snapshot_at']})")
    print("Deploy that folder to any static host, e.g.:  npx vercel deploy", r["out"], "--prod")


def main(argv=None):
    load_dotenv(os.path.join(os.getcwd(), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    p = argparse.ArgumentParser(prog="statetrace", description="Evidence-backed project state engine")
    p.add_argument("--db", default=os.environ.get("STATETRACE_DB", "statetrace.db"))
    p.add_argument("-p", "--project", default=os.environ.get("STATETRACE_PROJECT", "fft-accel"))
    p.add_argument("--offline", action="store_true",
                   help="use hand-written scripted operations instead of the model (demo/tests only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="record one piece of evidence and update the state")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("-s", "--source", default="note", choices=ALL_SOURCES)
    s.add_argument("-t", "--type", default=None, help="free-form event type (decision, attempt, ...)")
    s.add_argument("--at", default=None, help="when it happened (ISO time); default now")
    s.add_argument("--ref", default=None, help="reference id (commit hash, report file, ...)")
    s.add_argument("-f", "--file", default=None, help="attach a log/report file as the evidence body")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("state", help="show the current state")
    s.add_argument("--json", action="store_true")
    s.add_argument("--now", default=None)
    s.set_defaults(fn=cmd_state)

    s = sub.add_parser("ask", help="ask a question (Where am I? What is blocking me? ...)")
    s.add_argument("question")
    s.add_argument("--now", default=None)
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("why", help="show the evidence chain for a claim id, field, or topic")
    s.add_argument("target")
    s.set_defaults(fn=cmd_why)

    sub.add_parser("history", help="evidence log with the transition each item caused").set_defaults(fn=cmd_history)

    s = sub.add_parser("diff", help="what changed between two state versions")
    s.add_argument("v1", type=int)
    s.add_argument("v2", type=int)
    s.set_defaults(fn=cmd_diff)

    sub.add_parser("rebuild", help="replay the event log into a fresh state").set_defaults(fn=cmd_rebuild)
    sub.add_parser("pending", help="process events whose transition failed").set_defaults(fn=cmd_pending)
    sub.add_parser("demo", help="load the FFT accelerator scenario").set_defaults(fn=cmd_demo)

    s = sub.add_parser("eval", help="run the evaluation scenario")
    s.add_argument("--scenario", default=SCENARIO)
    s.add_argument("--baseline", action="store_true", help="also run the rewrite-the-state baseline")
    s.add_argument("--runs", type=int, default=1)
    s.add_argument("--out", default="eval_results")
    s.set_defaults(fn=cmd_eval)

    sub.add_parser("models", help="list models available on Nebius Token Factory").set_defaults(fn=cmd_models)

    s = sub.add_parser("serve", help="start the web dashboard")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--read-only", action="store_true", help="disable updates and model calls (public demos)")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("name", help="set a project's display name")
    s.add_argument("name")
    s.set_defaults(fn=cmd_name)

    s = sub.add_parser("sample", help="label a project as sample/synthetic data (or --off for real data)")
    s.add_argument("--off", action="store_true")
    s.set_defaults(fn=cmd_sample)

    sub.add_parser("seed", help="build the 4-project demo workspace through the engine").set_defaults(fn=cmd_seed)

    s = sub.add_parser("git-add", help="add a local git repository as an evidence source for the project")
    s.add_argument("path")
    s.add_argument("--branch", default=None)
    s.add_argument("--wsl", action="store_true", help="read the repo with WSL's git (for repos inside WSL2)")
    s.add_argument("--auto", action="store_true", help="auto-accept new commits (off by default)")
    s.set_defaults(fn=cmd_git_add)
    s = sub.add_parser("scan", help="stage new commits from the project's sources (does not change the state)")
    s.add_argument("--source", type=int, default=None)
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("imports", help="list staged imports")
    s.add_argument("--status", choices=["pending", "accepted", "skipped", "failed"], default=None)
    s.set_defaults(fn=cmd_imports)
    for name, fn, help_ in (("accept", cmd_accept, "accept staged imports as evidence (runs the engine)"),
                            ("skip", cmd_skip, "skip staged imports"),
                            ("retry-imports", cmd_retry_imports, "retry imports whose state update failed")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("ids", nargs="+", help="item ids, or 'all'")
        s.set_defaults(fn=fn)
    s = sub.add_parser("milestone", help="list milestones, or add one with a title")
    s.add_argument("title", nargs="?")
    s.add_argument("--due", default=None, help="ISO date/time, e.g. 2026-11-01T17:00")
    s.add_argument("--remind", nargs="*", help="minutes before due, e.g. 1440 120")
    s.set_defaults(fn=cmd_milestone)

    s = sub.add_parser("companion", help="Windows desktop companion: Ctrl+Alt+T popup, opt-in monitoring/notifications")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-hotkey", action="store_true", help="don't register a global hotkey")
    s.add_argument("--hotkey", default=None, help="override the saved hotkey for this run, e.g. ctrl+alt+t")
    s.add_argument("--no-popup", action="store_true", help="don't open the compact window at start")
    s.set_defaults(fn=cmd_companion)

    s = sub.add_parser("synth-import", help="import a Yosys `stat` report (text or JSON) as evidence")
    s.add_argument("file")
    s.set_defaults(fn=cmd_synth_import)
    sub.add_parser("synth-runs", help="list imported synthesis runs").set_defaults(fn=cmd_synth_runs)
    s = sub.add_parser("synth-compare", help="compare a run with a baseline run (deterministic)")
    s.add_argument("run", type=int)
    s.add_argument("baseline", type=int)
    s.set_defaults(fn=cmd_synth_compare)
    s = sub.add_parser("synth-explain", help="ask Nemotron to explain a comparison")
    s.add_argument("analysis", type=int)
    s.set_defaults(fn=cmd_synth_explain)

    s = sub.add_parser("stop", help="stop a running TaskMaster (server + companion) cleanly")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_stop)

    s = sub.add_parser("export-static", help="export a read-only static snapshot (for Vercel etc.)")
    s.add_argument("--out", default="site")
    s.add_argument("--workspace", default=None, help="label shown in the UI")
    s.set_defaults(fn=cmd_export)

    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    store = Store(args.db)
    try:
        args.fn(args, store)
    except LLMError as e:
        sys.exit(f"model error: {e}")
    finally:
        store.close()


if __name__ == "__main__":
    main()

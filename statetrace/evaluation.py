"""Scenario-based evaluation.

Feeds a scripted sequence of evidence through an engine and, at checkpoints, scores the
reconstructed state against known ground truth. Categories:

  accuracy       does the state say what is actually true?
  attribution    does the claim cite the right evidence?
  contradiction  are conflicts surfaced (and later resolved)?
  staleness      are obsolete beliefs gone from the current state?
  hallucination  is anything marked verified without supporting artifacts?
  recovery       does "Where am I?" after a long gap contain the key facts?

Plus global counters: unsupported "verified" claims, invented citations, stale ops rejected,
latency per update.
"""

import json
import os
import statistics
import tempfile
import time
from datetime import datetime

from . import view as V
from .baseline import BaselineEngine
from .engine import StateEngine
from .schema import VERIFIABLE_SOURCES
from .store import Store

CATEGORIES = ("accuracy", "attribution", "contradiction", "staleness", "hallucination", "recovery")


def _text(c):
    return f"{c.get('key') or ''} {c['value']}".lower().replace("_", " ")


def _has(text, words):
    return any(w.lower() in text for w in words)


def _match(claims, words):
    return [c for c in claims if _has(_text(c), words)] if words else list(claims)


def run_check(check, view, now):
    """Return (passed, detail, vacuous). A pass is vacuous when it held only because no relevant
    claim existed (e.g. "no obsolete blocker" when the model recorded no blocker at all)."""
    t = check["type"]
    f = view["fields"]
    if t in ("field", "item", "anywhere"):
        if t == "field":
            claims = _match(f.get(check["field"], []), check.get("match"))
        elif t == "item":
            claims = _match(f["status_items"], check["match"])
        else:
            claims = [c for cs in f.values() for c in cs]
        ok, detail = _eval_claims(check, claims)
        return ok, detail, ok and not claims
    if t in ("item_not_verified", "field_not_verified"):
        claims = (_match(f["status_items"], check["match"]) if t == "item_not_verified"
                  else f.get(check["field"], []))
        bad = [c for c in claims if c.get("verification") == "verified"
               and _has(_text(c), check["words"]) and not _has(_text(c), check.get("exclude", []))]
        return (not bad, f"unsupported verified: {[c['value'] for c in bad]}" if bad else "ok", not claims)
    if t == "contradiction":
        hits = [x for x in view["contradictions"] if check["involves"] in x.get("event_ids", [])]
        ok = any(str(x.get("status", "")).lower() == check["status"] for x in hits)
        return ok, f"found {[(x['id'], x.get('status')) for x in hits]}", False
    if t == "answer":
        text = V.where_am_i(view, now=now).lower()
        missing = [g for g in check["groups"] if not _has(text, g)]
        return (not missing, f"missing {missing}" if missing else "ok", False)
    raise ValueError(f"unknown check type {t}")


def _eval_claims(check, claims):
    if "none" in check:
        bad = [c["value"] for c in claims if _has(_text(c), check["none"])]
        if bad:
            return False, f"obsolete content still current: {bad}"
        if "any" not in check and "evidence" not in check:
            return True, "ok"
    candidates = claims
    if "any" in check:
        candidates = [c for c in candidates if _has(_text(c), check["any"])]
    if "verification" in check:
        candidates = [c for c in candidates if c.get("verification") == check["verification"]]
    if "evidence" in check:
        candidates = [c for c in candidates if check["evidence"] in (c.get("evidence") or [])]
    if candidates:
        return True, "ok"
    seen = [(c["value"][:80], c.get("verification"), c.get("evidence")) for c in claims]
    return False, f"no matching claim; have {seen}"


def _unsupported_verified(view, events):
    out = []
    for cs in view["fields"].values():
        for c in cs:
            if c.get("verification") == "verified" and not any(
                    events.get(e, {}).get("source") in VERIFIABLE_SOURCES for e in c.get("evidence") or []):
                out.append(c["value"])
    return out


def _invalid_citations(view, events):
    bad = 0
    total = 0
    for cs in view["fields"].values():
        for c in cs:
            total += 1
            if not c.get("evidence") or any(e not in events for e in c["evidence"]):
                bad += 1
    return bad, total


def run_scenario(scenario, llm, mode="engine", db_path=None):
    """mode: 'engine' (controlled transitions + validator) or 'baseline' (full rewrite)."""
    project = scenario["project"]
    tmp = None
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = tmp.name
    store = Store(db_path)
    engine = StateEngine(store, llm) if mode == "engine" else None
    baseline = BaselineEngine(llm, project) if mode == "baseline" else None
    checkpoints = {cp["after"]: cp for cp in scenario["checkpoints"]}
    results, latencies, errors, trace = [], [], [], []
    final_where = ""
    counters = {"stale_ops_rejected": 0, "verification_downgrades": 0, "invented_citations_removed": 0,
                "ops_rejected": 0, "max_unsupported_verified": 0, "max_invalid_citations": 0}
    for ev in scenario["events"]:
        event = store.append_event(project, ev["text"], ev.get("source", "note"), ev.get("event_type"),
                                   ev["occurred_at"], ev.get("ref"))
        assert event["id"] == ev["id"], f"scenario ids must be sequential ({event['id']} vs {ev['id']})"
        if engine:
            r = engine.process(project, event)
            latencies.append(r.latency_ms)
            if r.error:
                errors.append(f"{event['id']}: {r.error}")
            trace.append({"event": event["id"], "latency_ms": r.latency_ms, "error": r.error,
                          "applied": [a["op"] for a in r.log["applied"]],
                          "rejected": [x["reason"] for x in r.log["rejected"]],
                          "warnings": [w["type"] for w in r.log["warnings"]]})
            counters["ops_rejected"] += len(r.log["rejected"])
            counters["stale_ops_rejected"] += sum(1 for x in r.log["rejected"] if "stale" in x["reason"])
            for w in r.log["warnings"]:
                if w["type"] == "verification_downgraded":
                    counters["verification_downgrades"] += 1
                if w["type"] == "unknown_evidence_removed":
                    counters["invented_citations_removed"] += len(w["ids"])
            view = V.build_view(store.latest_state(project))
        else:
            err = baseline.process(event)
            latencies.append(baseline.latencies[-1])
            if err:
                errors.append(f"{event['id']}: {err}")
            trace.append({"event": event["id"], "latency_ms": baseline.latencies[-1], "error": err})
            view = baseline.view()
        events = store.events_by_id(project)
        unsupported = _unsupported_verified(view, events)
        counters["max_unsupported_verified"] = max(counters["max_unsupported_verified"], len(unsupported))
        bad_cites, _ = _invalid_citations(view, events)
        counters["max_invalid_citations"] = max(counters["max_invalid_citations"], bad_cites)
        cp = checkpoints.get(event["id"])
        if cp:
            now = cp.get("now") or event["occurred_at"]
            for check in cp["checks"]:
                ok, detail, vacuous = run_check(check, view, now)
                results.append({"after": cp["after"], "label": cp["label"], "category": check["category"],
                                "type": check["type"], "check": check, "passed": ok, "vacuous": vacuous,
                                "detail": detail})
            if cp is scenario["checkpoints"][-1]:
                final_where = V.where_am_i(view, now=now)
    final_view = view
    bad_cites, total_claims = _invalid_citations(final_view, store.events_by_id(project))
    store.close()
    if tmp:
        os.unlink(tmp.name)
    return {
        "mode": mode,
        "model": llm.name,
        "results": results,
        "scores": score(results),
        "counters": counters,
        "final_active_claims": total_claims,
        "final_claims_without_valid_citation": bad_cites,
        "latency_ms": {"mean": int(statistics.mean(latencies)) if latencies else 0,
                       "median": int(statistics.median(latencies)) if latencies else 0,
                       "p95": int(sorted(latencies)[int(0.95 * (len(latencies) - 1))]) if latencies else 0,
                       "max": max(latencies) if latencies else 0},
        "errors": errors,
        "trace": trace,
        "final_where_am_i": final_where,
    }


def score(results):
    out = {}
    for cat in CATEGORIES:
        rs = [r for r in results if r["category"] == cat]
        if rs:
            out[cat] = {"passed": sum(r["passed"] for r in rs), "total": len(rs)}
    passed = sum(r["passed"] for r in results)
    out["overall"] = {"passed": passed, "total": len(results)}
    return out


def to_markdown(runs, scenario):
    lines = [f"# Evaluation: {scenario['project']}", "",
             f"Run {datetime.now().replace(microsecond=0).isoformat()}. {scenario['description']}", ""]
    header = "| category | " + " | ".join(f"{r['mode']} #{i + 1}" for i, r in enumerate(runs)) + " |"
    lines += [header, "|" + "---|" * (len(runs) + 1)]
    for cat in CATEGORIES + ("overall",):
        cells = []
        for r in runs:
            s = r["scores"].get(cat)
            cells.append(f"{s['passed']}/{s['total']}" if s else "-")
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    lines += ["", "| counter | " + " | ".join(r["mode"] for r in runs) + " |", "|" + "---|" * (len(runs) + 1)]
    for key in ("max_unsupported_verified", "max_invalid_citations", "stale_ops_rejected",
                "verification_downgrades", "invented_citations_removed", "ops_rejected"):
        lines.append(f"| {key} | " + " | ".join(str(r["counters"][key]) for r in runs) + " |")
    for k in ("median", "mean", "p95", "max"):
        lines.append(f"| {k} latency per update (ms) | "
                     + " | ".join(str(r["latency_ms"].get(k, "-")) for r in runs) + " |")
    lines.append("| model-call errors | " + " | ".join(str(len(r["errors"])) for r in runs) + " |")
    lines.append("| vacuous passes (nothing recorded) | "
                 + " | ".join(str(sum(1 for x in r["results"] if x.get("vacuous"))) for r in runs) + " |")
    lines += ["", "## Per checkpoint", "",
              "| checkpoint | " + " | ".join(f"{r['mode']} #{i + 1}" for i, r in enumerate(runs)) + " |",
              "|" + "---|" * (len(runs) + 1)]
    for cp in scenario["checkpoints"]:
        cells = []
        for r in runs:
            rs = [x for x in r["results"] if x["after"] == cp["after"]]
            cells.append(f"{sum(x['passed'] for x in rs)}/{len(rs)}")
        lines.append(f"| {cp['after']} {cp['label']} | " + " | ".join(cells) + " |")
    lines += ["", "Notes: for the engine, `max_unsupported_verified` is 0 by construction (the validator",
              "downgrades such claims), so it measures the validator, not the model. Checks match keywords",
              "against claim text; a vacuous pass means no relevant claim existed at all.", "",
              "Models: " + ", ".join(sorted({r["model"] for r in runs})), ""]
    for i, r in enumerate(runs):
        lines += [f"## {r['mode']} #{i + 1} — failed checks", ""]
        failed = [x for x in r["results"] if not x["passed"]]
        if not failed:
            lines.append("none")
        for x in failed:
            lines.append(f"- after {x['after']} ({x['label']}) [{x['category']}/{x['type']}]: {x['detail'][:400]}")
        if r["errors"]:
            lines += ["", "Errors: " + "; ".join(r["errors"])]
        lines += ["", "Final \"Where am I?\":", "", "```", r["final_where_am_i"], "```", ""]
    return "\n".join(lines)


def run_eval(scenario_path, llm, modes=("engine",), runs=1, out_dir="eval_results"):
    with open(scenario_path, encoding="utf-8") as fh:
        scenario = json.load(fh)
    all_runs = []
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = os.path.join(out_dir, f"eval-{stamp}.json")
    md_path = os.path.join(out_dir, f"eval-{stamp}.md")
    for mode in modes:
        for i in range(runs):
            t0 = time.time()
            r = run_scenario(scenario, llm, mode)
            r["wall_s"] = round(time.time() - t0, 1)
            all_runs.append(r)
            s = r["scores"]["overall"]
            print(f"{mode} run {i + 1}/{runs}: {s['passed']}/{s['total']} in {r['wall_s']} s,"
                  f" {len(r['errors'])} errors", flush=True)
            # save after every run so an interruption keeps the completed runs
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(all_runs, fh, indent=1)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(to_markdown(all_runs, scenario))
    return all_runs, md_path, json_path

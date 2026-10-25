"""Yosys synthesis workflow: import -> compare -> explain.

TaskMaster (deterministic code) does the parsing, arithmetic, constraint checks and provenance;
Nemotron (via the existing Nebius client) only interprets, and its interpretation is stored as an
opinion next to the comparison. It never becomes a claim or evidence.

  import_report  : bounded, hashed, parsed; recorded as an append-only `synthesis_report` evidence
                   event (so the engine/validator treat it like any artifact) + a synth_runs index row.
                   Identical content in the same project is not imported twice.
  compare_runs   : deterministic deltas, new/disappeared cell types, limitations, constraint checks.
  explain        : Nemotron explains the most significant changes, labels hypotheses with
                   uncertainty, lists missing evidence and proposes one next experiment. Citations are
                   validated against the project's evidence log. On failure nothing is invented.
"""

import json
import os
import re
import time

from .engine import StateEngine
from .llm import LLMError, extract_json
from .prompts import render_event, render_state_for_prompt
from .skills import yosys as Y

EXCERPT_CHARS = 20_000


class SynthesisError(ValueError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def safe_filename(name):
    base = os.path.basename(str(name or "report").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip() or "report"
    return base[:120]


def _excerpt(data):
    text = data.decode("utf-8", errors="replace")
    i = text.find("===")
    return (text[i:] if i >= 0 else text)[:EXCERPT_CHARS]


def import_report(store, project, filename, data: bytes, llm=None, review=False, occurred_at=None):
    """Returns {"run", "duplicate", "event", "queued", "transition_error", "proposal"}. Raises SynthesisError.
    review=True: the state change is proposed and validated but NOT committed until the user applies it."""
    filename = safe_filename(filename)
    if not data:
        raise SynthesisError("The file is empty.")
    sha = Y.sha256(data)
    existing = store.synth_run_by_hash(project, sha)
    if existing:
        return {"run": existing, "duplicate": True, "event": store.get_event(project, existing["event_id"]),
                "queued": False, "transition_error": None}
    try:
        parsed = Y.parse(data, filename)
    except Y.ReportError as e:
        raise SynthesisError(str(e), e.diagnostics)
    text = Y.evidence_text(parsed, sha, filename)
    error = None
    proposal = None
    if llm is not None and review:
        from . import proposals
        event = store.append_event(project, text, "synthesis_report", "synthesis", occurred_at, filename)
        proposal = proposals.propose(store, llm, project, event)
        error = proposal.get("error") if "proposal" not in proposal else None
    elif llm is not None:
        r = StateEngine(store, llm).ingest(project, text, "synthesis_report", "synthesis", occurred_at, filename)
        event, error = r.event, r.error
    else:  # no model configured: keep the evidence; it is applied when a model is available
        event = store.append_event(project, text, "synthesis_report", "synthesis", occurred_at, filename)
        error = "no model connected"
    run = store.add_synth_run(project, event["id"], filename, sha, parsed["format"], parsed, _excerpt(data))
    return {"run": run, "duplicate": False, "event": event, "queued": bool(error), "transition_error": error,
            "proposal": proposal if proposal and "proposal" in proposal else None}


def constraints(store, project):
    return store.get_setting(f"synth_constraints:{project}", {}) or {}


def set_constraints(store, project, values):
    clean = {}
    for k, v in (values or {}).items():
        if k not in Y.CONSTRAINT_KEYS:
            raise SynthesisError(f"Unknown constraint {k!r}.")
        if v in (None, ""):
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise SynthesisError(f"{k} must be a number.")
        if n < 0:
            raise SynthesisError(f"{k} must not be negative.")
        clean[k] = int(n) if n.is_integer() else n
    store.set_setting(f"synth_constraints:{project}", clean)
    return clean


def compare_runs(store, project, run_id, baseline_id):
    cur, base = store.get_synth_run(int(run_id)), store.get_synth_run(int(baseline_id))
    if not cur or not base or cur["project"] != project or base["project"] != project:
        raise SynthesisError("Both runs must belong to this project.")
    if cur["id"] == base["id"]:
        raise SynthesisError("Choose a different run as the baseline.")
    comparison = Y.compare(base["parsed"], cur["parsed"])
    cons = constraints(store, project)
    checks = Y.check_constraints(cur["parsed"], cons)
    return store.add_synth_analysis(project, cur["id"], base["id"], comparison, cons, checks)


# Nemotron explanation --------------------------------------------------------------------------------
EXPLAIN_SYSTEM = """You are an experienced digital-design engineer reviewing two Yosys synthesis runs for a
colleague. TaskMaster has already parsed the reports and computed every number. Do NOT recompute or alter
numbers; quote them from the COMPARISON exactly.

Distinguish strictly:
- observations: what the measured numbers show (cite the report evidence ids);
- hypotheses: plausible causes, each with confidence low/medium/high, stated as possibilities, not facts;
- evidence_needed: what additional data would confirm or refute the hypotheses;
- next_experiment: ONE concrete, cheap experiment.

Never claim timing, power or physical-area changes from cell counts. Never call a run "better" just
because it has fewer cells. Cite only evidence ids (E...) from the EVIDENCE list, e.g. [E9].

Return ONLY JSON:
{"summary": "...",
 "observations": [{"text": "...", "evidence": ["E9","E10"]}],
 "hypotheses": [{"text": "...", "confidence": "low|medium|high", "evidence": ["E10"]}],
 "evidence_needed": ["..."],
 "next_experiment": {"title": "...", "how": "...", "expected_signal": "...", "evidence": ["E10"]}}"""


def _comparison_text(analysis, base, cur):
    c = analysis["comparison"]
    lines = [f"BASELINE run #{base['id']} = evidence {base['event_id']} ({base['filename']}); "
             f"CURRENT run #{cur['id']} = evidence {cur['event_id']} ({cur['filename']})", "", "METRICS (baseline -> current, delta, %):"]
    for r in c["metrics"]:
        pct = f"{r['pct']:+.2f}%" if r["pct"] is not None else (r["note"] or "n/a")
        d = f"{r['abs']:+}" if r["abs"] is not None else "n/a"
        lines.append(f"- {r['label']}{' [derived from cell names]' if r['derived'] else ''}: {r['baseline']} -> {r['current']} ({d}, {pct})")
    lines.append("CELL TYPES (largest changes first):")
    for t in [x for x in c["cell_types"] if x["status"] != "same"][:25]:
        lines.append(f"- {t['type']}: {t['baseline']} -> {t['current']} ({t['status']})")
    if c["new_types"] or c["gone_types"]:
        lines.append(f"New cell types: {', '.join(c['new_types']) or 'none'}; disappeared: {', '.join(c['gone_types']) or 'none'}")
    lines.append("LIMITATIONS: " + " | ".join(c["limitations"]))
    if analysis["checks"]:
        lines.append("CONSTRAINT CHECKS: " + "; ".join(
            f"{x['label']} <= {x['limit']}: {x['status']}" + (f" ({x['note']})" if x["note"] else "") for x in analysis["checks"]))
    return "\n".join(lines)


def _clean(items, events, keys, limit):
    out, invented = [], []
    for it in (items or [])[:limit]:
        if isinstance(it, str):
            it = {keys[0]: it}
        if not isinstance(it, dict) or not str(it.get(keys[0], "")).strip():
            continue
        ev = [str(e) for e in (it.get("evidence") or [])]
        invented += [e for e in ev if e not in events]
        row = {k: str(it.get(k, "")).strip()[:400] for k in keys}
        row["evidence"] = [e for e in ev if e in events]
        out.append(row)
    return out, invented


def explain(store, project, analysis_id, llm):
    a = store.get_synth_analysis(int(analysis_id))
    if not a or a["project"] != project:
        raise SynthesisError("That comparison doesn't belong to this project.")
    if llm is None or not hasattr(llm, "chat"):
        a = store.set_synth_explanation(a["id"], error="Nemotron is not connected")
        return a
    base, cur = store.get_synth_run(a["baseline_id"]), store.get_synth_run(a["run_id"])
    events = store.events_by_id(project)
    state = store.latest_state(project)
    ctx = "\n".join([
        f"PROJECT: {store.project_name(project)}", "", "VALIDATED PROJECT STATE", render_state_for_prompt(state), "",
        "COMPARISON (computed by TaskMaster)", _comparison_text(a, base, cur), "",
        "EVIDENCE (cite these ids)", *[render_event(e, full=False) for e in list(events.values())[-25:]],
    ])
    t0 = time.perf_counter()
    try:
        raw = llm.chat(EXPLAIN_SYSTEM, ctx + "\n\nReturn the JSON.", json_mode=True, max_tokens=6000)  # room for reasoning tokens
        data = extract_json(raw)
    except LLMError as e:
        return store.set_synth_explanation(a["id"], model=getattr(llm, "name", None), error=str(e)[:300],
                                           latency_ms=int((time.perf_counter() - t0) * 1000))
    obs, inv1 = _clean(data.get("observations"), events, ("text",), 5)
    hyp, inv2 = _clean(data.get("hypotheses"), events, ("text", "confidence"), 4)
    for h in hyp:
        if h["confidence"].lower() not in ("low", "medium", "high"):
            h["confidence"] = "low"
        h["confidence"] = h["confidence"].lower()
    nx = data.get("next_experiment") if isinstance(data.get("next_experiment"), dict) else {}
    nxt, inv3 = _clean([nx], events, ("title", "how", "expected_signal"), 1)
    analysis = {
        "summary": str(data.get("summary", "")).strip()[:500],
        "observations": obs,
        "hypotheses": hyp,
        "evidence_needed": [str(x).strip()[:300] for x in (data.get("evidence_needed") or [])[:4] if str(x).strip()],
        "next_experiment": nxt[0] if nxt else None,
        "invented_citations": sorted(set(inv1 + inv2 + inv3)),
        "kind": "model interpretation (not evidence, not verified)",
    }
    cited = {e for sec in (obs, hyp, nxt) for row in sec for e in row["evidence"]}
    analysis["cites_reports"] = sorted(cited & {base["event_id"], cur["event_id"]})
    return store.set_synth_explanation(a["id"], analysis=analysis, model=getattr(llm, "name", None),
                                       latency_ms=int((time.perf_counter() - t0) * 1000))


def overview(store, project):
    """Runs (newest first, without the large excerpt) and recent comparisons for the UI."""
    runs = store.synth_runs(project)
    events = store.events_by_id(project)
    out = []
    for r in reversed(runs):
        p = r["parsed"]
        out.append({"id": r["id"], "event_id": r["event_id"], "filename": r["filename"], "sha256": r["sha256"],
                    "format": r["format"], "imported_at": r["imported_at"], "scope": p.get("scope"), "top": p.get("top"),
                    "library": p.get("library"), "metrics": p.get("metrics"), "derived": p.get("derived"),
                    "cell_types": p.get("cell_types"), "warnings": p.get("warnings"), "modules": p.get("modules"),
                    "processed": events.get(r["event_id"]) is not None})
    return {"runs": out, "analyses": list(reversed(store.synth_analyses(project)))[:20],
            "constraints": constraints(store, project), "constraint_keys": {k: v[1] for k, v in Y.CONSTRAINT_KEYS.items()},
            "classification_rules": Y.CLASS_RULES}


def excerpt(store, project, run_id):
    r = store.get_synth_run(int(run_id))
    if not r or r["project"] != project:
        raise SynthesisError("That run doesn't belong to this project.")
    return {"excerpt": r["excerpt"], "filename": r["filename"], "sha256": r["sha256"]}


def dumps(x):
    return json.loads(json.dumps(x))

// Synthesis runs (Yosys): import -> review metrics -> choose baseline -> compare -> Nemotron -> next experiment.
// Numbers come from TaskMaster's deterministic code; Nemotron only interprets them.
import { api } from "../api.js";
import { diffView, heldBack } from "../components.js";
import { ctx, invalidate, loadWorkspace, projectBundle } from "../ctx.js";
import { ago, evChip, evChips, fmtFull, html, icon, mount, toast } from "../ui.js";

const LABELS = { cells: "Total cells", wires: "Wires", wire_bits: "Wire bits", public_wires: "Public wires",
  public_wire_bits: "Public wire bits", memories: "Memories", memory_bits: "Memory bits", processes: "Processes",
  chip_area: "Chip area (liberty estimate)", transistors: "Estimated transistors" };
const DERIVED = { flip_flops: "Flip-flops", latches: "Latches", luts: "LUTs", dsp: "DSP / multiplier primitives", memory_primitives: "Memory primitives" };
const fmtN = (v) => (v === null || v === undefined ? "—" : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)) : v);
const fmtD = (v) => (v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + fmtN(v));

function metricsTable(run) {
  const m = run.metrics || {}, d = run.derived || {};
  const derived = Object.entries(d).filter(([, v]) => v);
  return html`<table class="table compact-table"><tbody>
    ${Object.keys(LABELS).filter((k) => k in m).map((k) => html`<tr><td>${LABELS[k]}</td><td class="num">${fmtN(m[k])}</td><td class="small muted">measured</td></tr>`)}
    ${derived.map(([k, v]) => html`<tr><td>${DERIVED[k]}</td><td class="num">${fmtN(v)}</td><td class="small muted" title="Counted from cell-type names by a fixed rule">derived from cell names</td></tr>`)}
  </tbody></table>
  ${!Object.keys(m).length ? html`<p class="small" style="color:var(--warm)">No design totals in this report.</p>` : ""}`;
}

function runDetail(run, events, opts = {}) {
  const types = Object.entries(run.cell_types || {}).sort((a, b) => b[1] - a[1]);
  return html`<div class="synth-run">
    <div class="row small" style="gap:8px">
      <b class="mono">#${run.id}</b><span class="mono">${run.filename}</span>${evChip(run.event_id, events)}
      <span class="badge b-ok" title="An imported artifact: its measurements are verified evidence">${icon("shield")}artifact</span>
      <span class="muted">${run.format} · ${run.scope || "per-module only"}${run.top ? ` · top ${run.top}` : ""} · ${run.library || "no cell breakdown"}</span>
      <span class="muted mono" title="${run.sha256}">sha256 ${run.sha256.slice(0, 12)}…</span>
      <span class="muted">imported ${ago(run.imported_at)}</span>
    </div>
    <div class="grid-2" style="margin-top:10px;align-items:start">
      <div>${metricsTable(run)}</div>
      <div>${types.length ? html`<table class="table compact-table"><thead><tr><th>Cell type</th><th class="num">Count</th></tr></thead><tbody>
        ${types.slice(0, opts.allTypes ? 500 : 10).map(([t, n]) => html`<tr><td class="mono small">${t}</td><td class="num">${fmtN(n)}</td></tr>`)}</tbody></table>
        ${types.length > 10 && !opts.allTypes ? html`<div class="small muted">+ ${types.length - 10} more cell types</div>` : ""}`
        : html`<p class="small muted">No cell-type breakdown in this report.</p>`}</div>
    </div>
    ${run.warnings?.length ? html`<div class="held" style="margin-top:8px">${run.warnings.map((w) => html`<div>• ${w}</div>`)}</div>` : ""}
  </div>`;
}

function comparisonView(a, runs) {
  const c = a.comparison, byId = Object.fromEntries(runs.map((r) => [r.id, r]));
  const changed = c.cell_types.filter((t) => t.status !== "same");
  return html`<div class="stack">
    <div class="small muted">Run <b>#${a.run_id}</b> (${byId[a.run_id]?.filename || "?"}) vs baseline <b>#${a.baseline_id}</b> (${byId[a.baseline_id]?.filename || "?"}) · computed by TaskMaster ${ago(a.created_at)}</div>
    <div class="table-wrap"><table class="table compact-table"><thead><tr><th>Metric</th><th class="num">Baseline</th><th class="num">Current</th><th class="num">Change</th><th class="num">%</th></tr></thead><tbody>
      ${c.metrics.map((r) => html`<tr><td>${r.label}</td>
        <td class="num">${fmtN(r.baseline)}</td><td class="num">${fmtN(r.current)}</td><td class="num">${fmtD(r.abs)}</td>
        <td class="num">${r.pct !== null && r.pct !== undefined ? (r.pct > 0 ? "+" : "") + r.pct.toFixed(2) + "%" : html`<span class="small muted">${r.note || "—"}</span>`}</td></tr>`)}
    </tbody></table></div>
    ${changed.length ? html`<details ${changed.length <= 12 ? "open" : ""}><summary class="small muted">Cell types that changed (${changed.length})${c.new_types.length ? ` · new: ${c.new_types.join(", ")}` : ""}${c.gone_types.length ? ` · gone: ${c.gone_types.join(", ")}` : ""}</summary>
      <table class="table compact-table"><tbody>${changed.slice(0, 40).map((t) => html`<tr><td class="mono small">${t.type}</td>
        <td class="num">${fmtN(t.baseline)}</td><td class="num">${fmtN(t.current)}</td><td class="num">${fmtD(t.abs)}</td>
        <td>${t.status === "new" ? html`<span class="badge b-accent">new</span>` : t.status === "gone" ? html`<span class="badge b-muted">gone</span>` : ""}</td></tr>`)}</tbody></table></details>` : html`<p class="small muted">No cell-type changes.</p>`}
    ${(a.checks || []).length ? html`<div class="stack" style="gap:4px">${a.checks.map((x) => html`<div class="row small">
      <span class="badge ${x.status === "violated" ? "b-danger" : x.status === "ok" ? "b-ok" : "b-muted"}">${x.status === "violated" ? "limit exceeded" : x.status === "ok" ? "within limit" : "can't check"}</span>
      <span>${x.label} ≤ ${fmtN(x.limit)}${x.value !== null ? ` (measured ${fmtN(x.value)})` : ""}</span>${x.note ? html`<span class="muted">${x.note}</span>` : ""}</div>`)}</div>` : ""}
    <div class="banner info" style="margin:0"><span class="ic">${icon("eye")}</span><div class="body small">
      <b>Limits of this comparison</b>${c.limitations.map((l) => html`<div>• ${l}</div>`)}</div></div>
  </div>`;
}

function explanationView(a, events, project) {
  if (!a.analysis && !a.error) return "";
  if (a.error) {
    return html`<div class="error-card"><b>Nemotron explanation unavailable.</b>
      <span class="small">${a.error.slice(0, 200)}. The comparison above is unaffected; try again when Nebius is reachable.</span></div>`;
  }
  const x = a.analysis;
  const confBadge = (c) => html`<span class="badge ${c === "high" ? "b-accent" : c === "medium" ? "b-warm" : "b-muted"}">${c} confidence</span>`;
  return html`<section class="review" aria-label="Nemotron's explanation">
    <div class="review-head"><span class="ai-mark" aria-hidden="true">${icon("zap")}</span><h2 class="review-title">Nemotron's explanation</h2>
      <span class="badge b-violet" title="Model output: not evidence and never marked verified">interpretation, not evidence</span></div>
    ${x.summary ? html`<div class="review-headline">${x.summary}</div>` : ""}
    ${x.observations.length ? html`<div class="review-k">What the measurements show</div><ul class="review-list good">${x.observations.map((o) => html`<li>${o.text} ${evChips(o.evidence, events, { short: true })}</li>`)}</ul>` : ""}
    ${x.hypotheses.length ? html`<div class="review-k">Possible causes (hypotheses, not facts)</div><ul class="review-list">${x.hypotheses.map((h) => html`<li>${confBadge(h.confidence)} ${h.text} ${evChips(h.evidence, events, { short: true })}</li>`)}</ul>` : ""}
    ${x.evidence_needed.length ? html`<div class="review-k">Evidence that would settle it</div><ul class="review-list">${x.evidence_needed.map((n) => html`<li>${n}</li>`)}</ul>` : ""}
    ${x.next_experiment ? html`<div class="review-k">Suggested next experiment</div>
      <div class="suggestion"><div class="sg-title">${x.next_experiment.title}</div>
        ${x.next_experiment.how ? html`<div class="sg-why"><b>How:</b> ${x.next_experiment.how}</div>` : ""}
        ${x.next_experiment.expected_signal ? html`<div class="sg-why"><b>What to look for:</b> ${x.next_experiment.expected_signal}</div>` : ""}
        ${ctx.canEdit ? html`<div class="row" style="gap:6px">
          ${ctx.canWrite ? html`<button class="btn sm" data-compose="${project}" data-prefill="Next experiment (suggested by Nemotron, accepted by me): ${x.next_experiment.title}. ${x.next_experiment.how || ""}">${icon("plus", "sm")}Accept as update</button>` : ""}
          <button class="btn sm ghost" data-add-milestone="${project}" data-ms-title="${x.next_experiment.title}">${icon("clock", "sm")}Make milestone</button></div>` : ""}
      </div>` : ""}
    <div class="review-foot">${icon("shield", "sm")} ${a.model} · ${a.latency_ms ? (a.latency_ms / 1000).toFixed(1) + " s" : ""} · cites ${x.cites_reports?.length ? x.cites_reports.join(", ") : "no report evidence"}
      ${x.invented_citations?.length ? html` · <span style="color:var(--warm)">removed citations to non-existent evidence: ${x.invented_citations.join(", ")}</span>` : ""}
      · nothing here changes the project until you accept it.</div>
  </section>`;
}

// Review-before-commit: the proposed state change from an imported report, re-validated against the
// current state. Nothing changes until the user applies it; discarding keeps the evidence.
export function proposalCard(p, events, project) {
  const pr = p.proposal, t = p.transition;
  const real = (t.applied || []).filter((a) => a.op !== "NOOP");
  return html`<section class="proposal" aria-label="Proposed change from ${p.event.id}">
    <div class="row" style="gap:8px">
      <span class="badge b-warm">${icon("eye")}Waiting for your review</span>
      <b>Proposed state change from <span class="mono">${p.event.id}</span></b>${p.event.ref ? html`<span class="mono muted small">${p.event.ref}</span>` : ""}
      <span class="small muted">proposed by ${pr.model}${pr.latency_ms ? ` in ${(pr.latency_ms / 1000).toFixed(1)} s` : ""}; checked by the validator</span></div>
    ${pr.rebased ? html`<div class="small" style="color:var(--warm)">${icon("history", "sm")} The state moved from v${pr.proposed_at_version} to v${pr.current_version} since this was proposed; the diff below is re-validated against the current state.</div>` : ""}
    ${pr.error ? html`<div class="error-card"><b>The validator can't apply this proposal.</b><span class="small">${pr.error}</span></div>`
      : real.length ? diffView(p, events, { onlyChanged: true }) : html`<p class="small muted">The proposal makes no change to the current state.</p>`}
    ${heldBack(t)}
    ${ctx.canEdit ? html`<div class="row" style="gap:8px;margin-top:8px">
      <button class="btn primary" data-proposal-apply="${p.event.id}" ${pr.error ? "disabled" : ""}>${icon("check", "sm")}Apply to project state</button>
      <button class="btn ghost" data-proposal-discard="${p.event.id}">${icon("x", "sm")}Discard proposal</button>
      <span class="small muted">Discarding keeps the report as evidence; only the proposed change is declined. Both are recorded in history.</span></div>` : ""}
  </section>`;
}

export function bindProposals(project, after) {
  document.querySelectorAll("[data-proposal-apply],[data-proposal-discard]").forEach((el) => el.onclick = async () => {
    const apply = !!el.dataset.proposalApply, eid = el.dataset.proposalApply || el.dataset.proposalDiscard;
    el.closest(".proposal")?.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      if (apply) {
        const res = await api.applyProposal(project, eid);
        toast(res.applied ? `Applied ${eid}: state is now v${res.version}` : `Not applied: ${res.error}`, res.applied ? "" : "err");
      } else {
        await api.discardProposal(project, eid);
        toast(`Discarded the proposed change from ${eid}. The evidence is kept.`);
      }
      invalidate(project);
      await loadWorkspace(true).catch(() => {});
    } catch (err) { toast(err.message, "err"); }
    after();
  });
}

export async function renderSynthesis(r) {
  const project = r.project;
  const [b, data, props] = await Promise.all([projectBundle(project), api.synth(project), api.proposals(project).catch(() => ({ proposals: [] }))]);
  r.setCrumbs([{ label: "Projects", href: "#/projects" }, { label: b.summary.name, href: `#/p/${project}` }, { label: "Synthesis" }]);
  const events = b.events;
  const runs = data.runs;
  let analysis = data.analyses[0] || null;
  let lastImport = null;

  const refreshBundle = async () => { invalidate(project); const nb = await projectBundle(project); Object.assign(events, nb.events); };
  const draw = () => {
    mount(document.getElementById("synth-compare-out"), analysis ? html`${comparisonView(analysis, runs)}
      <div class="row" style="margin-top:10px">${ctx.canWrite ? html`<button class="btn accent" id="synth-explain">${icon("zap", "sm")}${analysis.analysis ? "Ask Nemotron again" : "Explain with Nemotron"}</button>` : html`<span class="small muted">Explanations need the Nemotron connection.</span>`}</div>
      <div id="synth-explain-out" style="margin-top:12px">${explanationView(analysis, events, project)}</div>` : html`<p class="small muted">Choose a run and a baseline, then Compare.</p>`);
    const ex = document.getElementById("synth-explain");
    if (ex) ex.onclick = async () => {
      ex.disabled = true;
      mount(document.getElementById("synth-explain-out"), html`<div class="loading-note"><span class="spinner"></span>Nemotron is reading the comparison and the project evidence…</div>`);
      try { analysis = await api.synthExplain(project, analysis.id); } catch (err) { toast(err.message, "err"); }
      draw();
    };
  };

  r.after = () => {
    bindProposals(project, () => ctx.rerender());
    const file = document.getElementById("synth-file");
    const go = document.getElementById("synth-import");
    if (go) go.onclick = async () => {
      const f = file.files[0];
      if (!f) { toast("Choose a Yosys report file first.", "err"); file.focus(); return; }
      if (f.size > 2_000_000) { toast("That file is over 2 MB. Export just the `stat` output.", "err"); return; }
      go.disabled = true;
      const out = document.getElementById("synth-import-out");
      const t0 = Date.now();
      mount(out, html`<div class="loading-note" role="status"><span class="spinner"></span>Parsing ${f.name}, recording it as evidence and asking Nemotron to propose the state change… <b class="mono" id="imp-elapsed">0 s</b></div>`);
      const timer = setInterval(() => { const el = document.getElementById("imp-elapsed"); if (!el) return clearInterval(timer); el.textContent = `${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
      try {
        const text = await f.text();
        const res = await api.synthImport(project, f.name, text);
        lastImport = res;
        await refreshBundle();
        await loadWorkspace(true).catch(() => {});
        clearInterval(timer);
        toast(res.duplicate ? "Already imported: identical content, nothing duplicated."
          : res.proposal ? `Imported as run #${res.run.id} (${res.run.event_id}). Review the proposed state change below.`
          : res.transition_error ? `Imported as ${res.run.event_id}; the state wasn't updated (${res.transition_error.slice(0, 80)}). The evidence is kept.`
          : `Imported as run #${res.run.id} (${res.run.event_id})`, res.transition_error ? "err" : "");
        ctx.rerender();
      } catch (err) {
        clearInterval(timer);
        mount(out, html`<div class="error-card"><b>Couldn't import ${f.name}.</b><span class="small">${err.message}</span>
          ${err.diagnostics?.first_lines ? html`<details><summary class="small">What the file starts with</summary><pre class="evidence">${err.diagnostics.first_lines.join("\n")}</pre></details>` : ""}</div>`);
        go.disabled = false;
      }
    };
    const cmp = document.getElementById("synth-compare");
    if (cmp) cmp.onclick = async () => {
      const cur = +document.getElementById("synth-cur").value, base = +document.getElementById("synth-base").value;
      if (!cur || !base) { toast("Choose a run and a baseline.", "err"); return; }
      try { analysis = await api.synthCompare(project, cur, base); draw(); }
      catch (err) { toast(err.message, "err"); }
    };
    const cons = document.getElementById("synth-cons");
    if (cons) cons.onsubmit = async (e) => {
      e.preventDefault();
      const vals = Object.fromEntries([...cons.querySelectorAll("input")].map((i) => [i.name, i.value.trim()]));
      try { await api.synthConstraints(project, vals); toast("Constraints saved. They apply to the next comparison."); }
      catch (err) { toast(err.message, "err"); }
    };
    document.querySelectorAll("[data-load-analysis]").forEach((el) => el.onclick = () => {
      analysis = data.analyses.find((x) => x.id === +el.dataset.loadAnalysis); draw();
      document.getElementById("step-compare").scrollIntoView({ behavior: "smooth" });
    });
    draw();
  };

  if (data.snapshot) return html`<div class="page-head"><div><h1>Synthesis runs</h1><div class="sub">Not available in the read-only snapshot.</div></div></div>`;
  const latest = runs[0];
  return html`
    <div class="page-head"><div><h1>Synthesis runs</h1>
      <div class="sub">Import Yosys <span class="mono">stat</span> reports, compare runs, and ask Nemotron what changed and what to try next.
        TaskMaster does all parsing and arithmetic; Nemotron only interprets.</div></div></div>

    <section class="set-card" aria-labelledby="s1"><h2 class="set-title" id="s1"><span class="step">1</span> Import a synthesis report</h2>
      ${ctx.canEdit ? html`<div class="row">
        <input type="file" id="synth-file" accept=".rpt,.txt,.log,.json,.stat" aria-label="Yosys report file">
        <button class="btn primary" id="synth-import">${icon("plus", "sm")}Import report</button></div>
        <p class="small muted" style="margin:0">Yosys text <span class="mono">stat</span> output (e.g. <span class="mono">tee -o report.rpt stat</span>) or <span class="mono">stat -json</span>. Up to 2 MB.
          The file is hashed, parsed as data, and recorded as <b>verified evidence</b> (an artifact). Importing the same file again creates nothing new.</p>`
        : html`<p class="small muted">This instance is read-only.</p>`}
      <div id="synth-import-out"></div>
      ${props.proposals.length ? html`<div class="stack" id="proposals">${props.proposals.map((p) => proposalCard(p, events, project))}</div>` : ""}
    </section>

    <section class="set-card" aria-labelledby="s2"><h2 class="set-title" id="s2"><span class="step">2</span> Review extracted metrics</h2>
      ${latest ? runDetail(latest, events) : html`<p class="small muted">No runs yet. Import a report above.</p>`}
      ${runs.length > 1 ? html`<details><summary class="small muted">Earlier runs (${runs.length - 1})</summary>${runs.slice(1).map((x) => runDetail(x, events))}</details>` : ""}
    </section>

    <section class="set-card" id="step-compare" aria-labelledby="s3"><h2 class="set-title" id="s3"><span class="step">3</span> Choose a baseline and compare</h2>
      ${runs.length >= 2 ? html`<div class="row">
          <label class="field">Run<select id="synth-cur">${runs.map((x) => html`<option value="${x.id}">#${x.id} · ${x.filename} · ${fmtFull(x.imported_at)}</option>`)}</select></label>
          <label class="field">Baseline<select id="synth-base">${runs.map((x, i) => html`<option value="${x.id}" ${i === 1 ? "selected" : ""}>#${x.id} · ${x.filename} · ${fmtFull(x.imported_at)}</option>`)}</select></label>
          <button class="btn accent" id="synth-compare" style="align-self:end">Compare</button></div>`
        : html`<p class="small muted">Import at least two runs to compare them.</p>`}
      <details ${Object.keys(data.constraints).length ? "open" : ""}><summary class="small muted">Optional limits (flagged only when the report measures them)</summary>
        <form class="row" id="synth-cons" style="margin-top:8px">${Object.entries(data.constraint_keys).map(([k, label]) => html`<label class="field">${label} ≤
          <input type="text" name="${k}" value="${data.constraints[k] ?? ""}" size="8" inputmode="decimal" ${ctx.canEdit ? "" : "disabled"}></label>`)}
          ${ctx.canEdit ? html`<button class="btn sm" type="submit" style="align-self:end">Save limits</button>` : ""}</form></details>
      <div id="synth-compare-out" style="margin-top:12px"></div>
    </section>

    ${data.analyses.length > 1 ? html`<section class="set-card"><h2 class="set-title">Earlier comparisons</h2><div class="panel">
      ${data.analyses.map((x) => html`<button class="item clickable" style="text-align:left;width:100%;border:0;background:none;color:inherit;font:inherit" data-load-analysis="${x.id}">
        <span class="row small"><b>#${x.run_id} vs #${x.baseline_id}</b><span class="muted">${ago(x.created_at)}</span>
        ${x.analysis ? html`<span class="badge b-accent">${icon("zap")}explained</span>` : x.error ? html`<span class="badge b-muted">explanation unavailable</span>` : ""}</span></button>`)}</div></section>` : ""}

    <p class="small muted">Flip-flop, LUT, DSP and memory counts are derived from cell-type names by fixed rules and labelled as derived.
      Cell counts are not timing, power or physical area; TaskMaster draws no conclusions about those from them.</p>`;
}

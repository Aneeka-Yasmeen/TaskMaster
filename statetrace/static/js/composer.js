// "Add update": the central interaction. One line in, a reconstructed state + diff out.
import { api } from "./api.js";
import { diffView, heldBack, humanError } from "./components.js";
import { ctx, invalidate, loadWorkspace, projectBundle, setCurrentProject } from "./ctx.js";
import { closeSheet, html, icon, mount, openSheet, srcLabel, toast } from "./ui.js";

const ARTIFACTS = ["sim_log", "test_output", "synthesis_report", "implementation_report", "timing_report", "experiment_log", "git_commit", "ci", "report"];
const PEOPLE = ["note", "chat", "meeting", "email", "issue"];
const STAGES = ["Reading evidence", "Comparing with the previous state", "Checking for contradictions", "Updating project state"];

let state = null;

export async function openComposer({ project, prefill = "" } = {}) {
  if (!ctx.canWrite) { toast("Updates need the live engine. This workspace is read-only.", "err"); return; }
  const ws = await loadWorkspace().catch(() => ({ projects: [] }));
  state = { project: project || ws.projects[0]?.id || "__new", kind: "note", source: "note", more: false };
  openSheet(form(ws, prefill));
  bind();
}

const form = (ws, prefill) => html`
  <div class="sheet-head">
    <span class="logo" aria-hidden="true" style="width:20px;height:20px"></span>
    <h2 id="sheet-title">Add update</h2>
    <span class="small muted hide-mobile">TaskMaster will reconstruct the project state from it</span>
    <button class="icon-btn x" data-action="close-sheet" aria-label="Close">${icon("x")}</button>
  </div>
  <form class="sheet-body" id="composer" autocomplete="off">
    <div class="row" style="gap:10px">
      <label class="field" style="flex:1;min-width:200px">Project
        <select id="c-project">
          ${ws.projects.map((p) => html`<option value="${p.id}" ${p.id === state.project ? "selected" : ""}>${p.name}</option>`)}
          <option value="__new" ${state.project === "__new" ? "selected" : ""}>+ New project…</option>
        </select>
      </label>
      <label class="field" id="c-newname-wrap" style="flex:1;min-width:200px" ${state.project === "__new" ? "" : "hidden"}>New project name
        <input type="text" id="c-newname" placeholder="e.g. VEGA Accelerator">
      </label>
    </div>
    <label class="field">What happened?
      <textarea id="c-text" class="composer-input" rows="3" autofocus
        placeholder="Tried pipelining the CRC. Timing improved from 180 to 196 MHz but LUT usage went up 18%.">${prefill}</textarea>
    </label>
    <div class="row" style="justify-content:space-between">
      <div class="row">
        <div class="seg" role="group" aria-label="Kind of evidence">
          <button type="button" data-kind="note" aria-pressed="true">${icon("note", "sm")} Note</button>
          <button type="button" data-kind="artifact" aria-pressed="false">${icon("report", "sm")} Artifact</button>
        </div>
        <select id="c-source" aria-label="Evidence type" hidden></select>
      </div>
      <button type="button" class="btn ghost sm" id="c-more" aria-expanded="false">More options</button>
    </div>
    <p class="small muted" id="c-hint" style="margin:0">A note can only make claims <b style="color:var(--warm)">reported</b>. Paste a log, report or commit as an artifact to make them <b style="color:var(--ok)">verified</b>.</p>
    <div class="row" id="c-more-box" hidden style="gap:10px">
      <label class="field" style="flex:1;min-width:180px">When it happened <input type="datetime-local" id="c-at" step="60"></label>
      <label class="field" style="flex:1;min-width:180px">Reference <input type="text" id="c-ref" placeholder="commit, report file, exp id…"></label>
    </div>
  </form>
  <div class="sheet-foot">
    <span class="small muted hide-mobile"><span class="kbd">Ctrl</span> + <span class="kbd">Enter</span></span>
    <div class="right">
      <button class="btn ghost" data-action="close-sheet">Cancel</button>
      <button class="btn primary" id="c-submit">${icon("zap")}Update project</button>
    </div>
  </div>`;

function bind() {
  const $ = (id) => document.getElementById(id);
  const src = $("c-source");
  src.innerHTML = ARTIFACTS.map((s) => `<option value="${s}">${srcLabel(s)}</option>`).join("")
    + `<optgroup label="From people">${PEOPLE.filter((s) => s !== "note").map((s) => `<option value="${s}">${srcLabel(s)}</option>`).join("")}</optgroup>`;
  $("c-project").onchange = (e) => { state.project = e.target.value; $("c-newname-wrap").hidden = state.project !== "__new"; if (state.project === "__new") $("c-newname").focus(); };
  document.querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => {
    state.kind = b.dataset.kind;
    document.querySelectorAll("[data-kind]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    src.hidden = state.kind === "note";
    $("c-hint").innerHTML = state.kind === "note"
      ? 'A note can only make claims <b style="color:var(--warm)">reported</b>. Paste a log, report or commit as an artifact to make them <b style="color:var(--ok)">verified</b>.'
      : 'Paste the relevant part of the log or report. Artifacts can make claims <b style="color:var(--ok)">verified</b>.';
  });
  $("c-more").onclick = () => { const box = $("c-more-box"); box.hidden = !box.hidden; $("c-more").setAttribute("aria-expanded", String(!box.hidden)); };
  $("c-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
  $("composer").onsubmit = (e) => { e.preventDefault(); submit(); };
  $("c-submit").onclick = submit;
}

async function submit() {
  const $ = (id) => document.getElementById(id);
  const text = $("c-text").value.trim();
  if (!text) { $("c-text").focus(); toast("Write the update first. One line is enough.", "err"); return; }
  let project = state.project;
  const source = state.kind === "note" ? "note" : $("c-source").value;
  const body = { text, source, occurred_at: $("c-at").value || null, ref: $("c-ref").value.trim() || null };
  if (project === "__new") {
    const name = $("c-newname").value.trim();
    if (!name) { $("c-newname").focus(); toast("Name the new project.", "err"); return; }
    try { project = (await api.createProject(name)).id; } catch (err) { toast(err.message, "err"); return; }
  }
  setCurrentProject(project);
  runStages(project, body);
}

async function runStages(project, body) {
  const sheet = document.getElementById("sheet");
  const started = performance.now();
  let stage = 0;
  const draw = () => mount(sheet, html`
    <div class="sheet-head"><span class="spinner" aria-hidden="true"></span><h2 id="sheet-title">Reconstructing project state…</h2></div>
    <div class="sheet-body">
      <div class="panel panel-pad small dim" style="font-style:italic">“${body.text.length > 220 ? body.text.slice(0, 220) + "…" : body.text}”</div>
      <div class="stages" aria-live="polite">${STAGES.map((s, i) => html`<div class="stage ${i < stage ? "done" : i === stage ? "active" : ""}">
        <span class="dot">${i < stage ? icon("check") : ""}</span><span>${s}</span>
        ${i === stage && i === 1 ? html`<span class="t" id="c-elapsed"></span>` : ""}</div>`)}</div>
      <p class="small muted" style="margin:0">${stage === 1 ? `${ctx.meta.model || "The model"} proposes changes; the validator decides what is applied.` : ""}</p>
    </div>`);
  draw();
  const timer = setInterval(() => { const el = document.getElementById("c-elapsed"); if (el) el.textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`; }, 100);
  setTimeout(() => { if (stage === 0) { stage = 1; draw(); } }, 350);
  let result, error;
  try { result = await api.addEvent({ project, ...body }); } catch (err) { error = err; }
  clearInterval(timer);
  stage = Math.max(stage, 1);
  for (const s of [2, 3, 4]) { stage = s; draw(); await new Promise((r) => setTimeout(r, 160)); }
  invalidate(project);
  await loadWorkspace(true).catch(() => {});
  if (error) return showFailure(project, body, error.message);
  showResult(project, body, result);
  ctx.rerender();
}

function showFailure(project, body, message) {
  mount(document.getElementById("sheet"), html`
    <div class="sheet-head"><span class="result-head"><span class="err">${icon("alert")}</span></span><h2 id="sheet-title">Update not recorded</h2>
      <button class="icon-btn x" data-action="close-sheet" aria-label="Close">${icon("x")}</button></div>
    <div class="sheet-body"><p style="margin:0">${message}</p></div>
    <div class="sheet-foot"><div class="right"><button class="btn" data-action="close-sheet">Close</button>
      <button class="btn primary" id="c-again">Try again</button></div></div>`);
  document.getElementById("c-again").onclick = () => openComposer({ project, prefill: body.text });
}

async function showResult(project, body, d) {
  const t = d.transition;
  const b = await projectBundle(project, true).catch(() => null);
  const events = b ? b.events : { [d.event.id]: d.event };
  const sheet = document.getElementById("sheet");
  const changed = d.labels.length > 0;
  const onlyRejected = !t.error && !changed && t.rejected.length > 0;
  const noop = !t.error && !changed && !t.rejected.length;
  const queued = !!(t.error && d.queued_offline);
  const head = queued ? ["ok", "clock", "Saved. Waiting for Nemotron"]
    : t.error ? ["err", "alert", "TaskMaster couldn't update the project state"]
    : onlyRejected ? ["err", "alert", "State kept: the update conflicts with newer evidence"]
    : noop ? ["ok", "check", "Recorded: no change to the current state"]
    : ["ok", "check", "State reconstructed"];
  const noopReason = (t.applied.find((a) => a.op === "NOOP") || {}).rationale;
  mount(sheet, html`
    <div class="sheet-head"><span class="result-head"><span class="${head[0]}">${icon(head[1])}</span></span>
      <h2 id="sheet-title">${head[2]}</h2>
      <button class="icon-btn x" data-action="close-sheet" aria-label="Close">${icon("x")}</button></div>
    <div class="sheet-body">
      <div class="row small muted">Evidence added <button class="ev-chip" data-ev="${d.event.id}" data-project="${project}"><span class="id">${d.event.id}</span><span class="lbl">${srcLabel(d.event.source)}</span></button>
        ${t.error ? "" : html`<span>·</span><span class="mono">v${t.version_before} → v${t.version_after}</span>`}
        ${t.latency_ms ? html`<span>·</span><span class="mono">${(t.latency_ms / 1000).toFixed(1)} s</span>` : ""}</div>
      ${queued ? html`<div class="banner info"><span class="ic">${icon("clock")}</span><div class="body">
          <div class="title">Stored safely as ${d.event.id}. Nemotron couldn't be reached.</div>
          <div class="small dim">TaskMaster keeps working offline. It checks every minute and applies waiting updates, oldest first,
          as soon as Nebius answers. ${d.queued_total} update${d.queued_total === 1 ? "" : "s"} waiting.</div></div></div>`
        : t.error ? html`<div class="error-card"><span>Your update was saved as evidence <b>${d.event.id}</b>, and the previous state is kept.</span>
          <span class="small dim">${humanError(t.error)}</span></div>`
        : onlyRejected ? html`<p style="margin:0" class="dim">TaskMaster couldn't confidently update the project state because the new evidence conflicts with existing, newer claims. Nothing was overwritten.</p>`
        : noop ? html`<p style="margin:0" class="dim">${noopReason || "The update is stored in the evidence log; it did not change what is currently true."}</p>`
        : diffView(d, events, { onlyChanged: true })}
      ${t.error ? "" : heldBack(t)}
    </div>
    <div class="sheet-foot">
      ${queued ? html`<button class="btn ghost" id="c-another">${icon("plus")}Add another</button>
          <div class="right"><button class="btn" id="c-retry">${icon("retry")}Sync now</button>
          <button class="btn primary" data-action="close-sheet">Done</button></div>`
        : t.error ? html`<div class="right"><button class="btn" data-action="close-sheet">Keep previous state</button>
          <button class="btn primary" id="c-retry">${icon("retry")}Retry update</button></div>`
        : html`<button class="btn ghost" id="c-another">${icon("plus")}Add another</button>
          <div class="right">${onlyRejected ? html`<button class="btn" data-ev="${d.event.id}" data-project="${project}">Review evidence</button>` : ""}
          <a class="btn primary" href="#/p/${project}" id="c-open" style="text-decoration:none">Open project ${icon("arrow")}</a></div>`}
    </div>`);
  const again = document.getElementById("c-another");
  if (again) again.onclick = () => openComposer({ project });
  const open = document.getElementById("c-open");
  if (open) open.onclick = () => closeSheet();
  const retry = document.getElementById("c-retry");
  if (retry) retry.onclick = async () => {
    retry.disabled = true;
    try {
      const r = queued ? await api.syncNow() : await api.retry(project);
      invalidate(project);
      const failed = queued ? r.queued_total > 0 : r.failed.length > 0;
      toast(failed ? "Nemotron still isn't reachable. Your update is kept and will sync automatically." : "State reconstructed.", failed ? "err" : "ok");
      if (!failed) { closeSheet(); ctx.rerender(); }
    } catch (err) { toast(err.message, "err"); }
    retry.disabled = false;
  };
  if (!t.error && changed) toast(`${d.labels[0]}${d.labels.length > 1 ? ` and ${d.labels.length - 1} more` : ""}`);
}

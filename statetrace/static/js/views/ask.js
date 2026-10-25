// Ask TaskMaster: answers shown next to the evidence that supports them, not as chat bubbles.
import { api } from "../api.js";
import { evidenceCard } from "../components.js";
import { ctx, loadWorkspace, projectBundle, setCurrentProject } from "../ctx.js";
import { html, icon, mount, withCitations } from "../ui.js";

function answerView(a, events, question) {
  const lines = a.text.split("\n").filter((l) => l.trim());
  return html`<div class="answer">
    <div class="panel panel-pad">
      <div class="row small" style="margin-bottom:6px;gap:8px">
        ${a.source === "nemotron" ? html`<span class="badge b-accent">${icon("zap")}Nemotron</span>`
          : html`<span class="badge b-muted">${icon("shield")}Stored state</span>`}
        <span class="muted">“${question}”</span></div>
      <div class="headline">${a.headline}</div>
      <div class="lines">${lines.map((l) => {
        const head = /^[A-Z][^:]{2,40}:$/.test(l.trim());
        const ind = /^\s{2,}/.test(l);
        return html`<div class="ln ${head ? "h" : ""} ${ind ? "ind" : ""}">${withCitations(head ? l.trim().replace(/:$/, "") : l.trim(), events)}</div>`;
      })}</div>
      <div class="divider"></div>
      <div class="mode-note">${icon(a.source === "nemotron" ? "zap" : "shield", "sm")}${a.source === "nemotron"
        ? html`${a.mode}${a.latency_ms ? ` · ${(a.latency_ms / 1000).toFixed(1)} s` : ""}. Citations checked against the evidence log; Nemotron advises, it doesn't change the state.`
        : a.mode.startsWith("rendered") ? "Rendered directly from validated claims (Nemotron not used)." : a.mode}</div>
      ${a.stored ? html`<details class="compare"><summary>Compare with the stored-state answer (no model)</summary>
        <div class="lines">${a.stored.text.split("\n").filter((l) => l.trim()).map((l) => html`<div class="ln ${/^\s{2,}/.test(l) ? "ind" : ""}">${withCitations(l.trim(), events)}</div>`)}</div></details>` : ""}
    </div>
    <div class="stack" style="align-content:start">
      <div class="section-head" style="margin:0"><h2>Why I believe this</h2><span class="right mono small muted">${a.citations.length}</span></div>
      ${a.citations.length ? a.citations.slice(0, 8).map((e) => evidenceCard(e)) : html`<div class="panel panel-pad small muted">No evidence cited.</div>`}
      ${a.citations.length > 8 ? html`<div class="small muted">+ ${a.citations.length - 8} more cited in the answer</div>` : ""}
      ${a.next_step ? html`<div class="section-head" style="margin:8px 0 0"><h2>Recorded next step</h2></div>
        <div class="scard next" style="min-height:0"><div class="value">${a.next_step.value}</div>
          <div class="meta">${withCitations(`[${a.next_step.evidence.join(", ")}]`, events)}</div></div>` : ""}
    </div>
  </div>`;
}

export async function renderAsk(r) {
  const ws = await loadWorkspace();
  const pid = r.project || ctx.project || ws.projects[0]?.id;
  r.setCrumbs([{ label: "Ask TaskMaster" }]);
  if (!pid) return html`<div class="empty"><div class="glyph"></div><h2>Nothing to ask about yet</h2><p>Add an update first; TaskMaster answers from the evidence you record.</p></div>`;
  setCurrentProject(pid);
  const b = await projectBundle(pid);
  const initial = r.query.get("q");
  r.after = () => {
    const input = document.getElementById("q");
    const out = document.getElementById("answer");
    const ask = async (question) => {
      if (!question.trim()) return;
      input.value = question;
      mount(out, html`<div class="loading-note" style="margin-top:16px"><span class="spinner"></span>Nemotron is reading the project state and its evidence…</div>`);
      try {
        const a = await api.ask(pid, question);
        if (!r.isCurrent()) return;
        mount(out, answerView(a, b.events, question));
      } catch (err) {
        mount(out, html`<div class="error-card" style="margin-top:16px">${err.message}</div>`);
      }
    };
    document.getElementById("askform").onsubmit = (e) => { e.preventDefault(); ask(input.value); };
    document.querySelectorAll("[data-q]").forEach((btn) => btn.onclick = () => ask(btn.dataset.q));
    document.getElementById("askproj").onchange = (e) => { location.hash = `#/ask/${e.target.value}`; };
    if (initial) ask(initial); else input.focus();
  };
  return html`
    <div class="page-head"><div><h1>Ask Nemotron</h1>
      <div class="sub">Nemotron answers using ${b.summary.name}'s validated state and evidence, and cites what it relies on. If it can't be reached, you get the stored-state answer instead.</div></div></div>
    <div class="row" style="margin-bottom:10px">
      <label class="small muted" for="askproj">Project</label>
      <select id="askproj">${ws.projects.map((p) => html`<option value="${p.id}" ${p.id === pid ? "selected" : ""}>${p.name}</option>`)}</select>
    </div>
    <form class="askbar" id="askform" role="search">
      ${icon("ask")}<label class="sr" for="q">Question</label>
      <input id="q" type="text" placeholder="Where did I leave off?" autocomplete="off">
      <button class="btn accent" type="submit">Ask</button>
    </form>
    <div class="suggest">${ctx.meta.quick_questions.map((q) => html`<button type="button" data-q="${q}">${q}</button>`)}</div>
    ${ctx.meta.mode === "live" && ctx.meta.model ? "" : html`<p class="small muted" style="margin:8px 0 0">${icon("eye", "sm")} Without the live model, the suggested questions still work: they are answered from the validated state.</p>`}
    <div id="answer"></div>`;
}

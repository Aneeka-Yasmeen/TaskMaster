// Compact companion popup. Shows stored, validated state only: missing state stays missing.
// Reuses the dashboard's service layer, drawers ("Why?", evidence, diffs) and Add-update composer.
import { api } from "./api.js";
import { openComposer } from "./composer.js";
import { openDiff, openEvidence, openWhy } from "./components.js";
import { directionBadge } from "./assist.js";
import { applyPrefs } from "./prefs.js";
import { ctx, invalidate, loadWorkspace, savedProject, setCurrentProject } from "./ctx.js";
import {
  ago, closeDrawer, closeSheet, drawerOpen, evChips, fmtFull, healthBadge, html, icon, mount, setVerifiable,
  sheetOpen, toast, vmark, withCitations,
} from "./ui.js";

const main = document.getElementById("c-main");
let brief = null;
let lastAnswer = null;

const QUICK = [
  ["Where did I leave off?", "history"],
  ["What's blocking me?", "block"],
  ["What should I do next?", "arrow"],
];

function staleTag(c) {
  return c && c.stale ? html`<span class="tag" title="No new evidence for 7+ days">${icon("clock", "sm")} stale</span>` : "";
}

function claimBlock(label, kind, c, empty, extra = "") {
  return html`<section class="c-card ${kind}" aria-label="${label}">
    <div class="c-label">${label}</div>
    ${c ? html`<div class="c-value">${c.value}</div>
      <div class="row small" style="gap:6px">${vmark(c)}${staleTag(c)}${extra}
        ${evChips(c.evidence, brief.events, { short: true })}
        <button class="btn ghost sm" data-claim="${c.id}" style="margin-left:auto">Why?</button></div>`
      : html`<div class="c-value muted">${empty}</div>`}
  </section>`;
}

function answerBlock(question, a) {
  const lines = a.text.split("\n").filter((l) => l.trim()).slice(0, 14);
  return html`<section class="c-card c-answer" aria-label="Answer">
    <div class="c-label">${question}</div>
    <div class="c-headline">${a.headline}</div>
    <div class="c-lines">${lines.map((l) => html`<div class="${/^\s{2,}/.test(l) ? "ind" : ""}">${withCitations(l.trim(), brief.events)}</div>`)}</div>
    ${a.text.split("\n").filter((l) => l.trim()).length > 14 ? html`<button class="btn ghost sm" data-open="/ask/${brief.project.id}?q=${encodeURIComponent(question)}">Full answer in dashboard</button>` : ""}
    <div class="mode-note">${icon(a.source === "nemotron" ? "zap" : "shield", "sm")}${a.source === "nemotron" ? `Nemotron${a.latency_ms ? ` · ${(a.latency_ms / 1000).toFixed(1)} s` : ""} · citations checked`
      : a.mode.startsWith("rendered") ? "From stored state (Nemotron not used)" : a.mode}</div>
  </section>`;
}

function render() {
  if (!brief) return;
  const p = brief.project;
  const n = brief.next_step;
  const nextExtra = n ? (n.commitment === "committed"
    ? html`<span class="tag clr">${icon("check", "sm")} committed${n.due_at ? ` · due ${fmtFull(n.due_at)}` : ""}</span>`
    : html`<span class="tag" title="Proposed from evidence; you haven't committed to it">proposed</span>`) : "";
  const ch = brief.latest_change;
  const ms = brief.milestone;
  mount(main, html`
    <div class="c-project">
      <div class="row" style="gap:8px"><b class="c-name">${p.name}</b>${healthBadge(p.health)}</div>
      <div class="small muted">${p.events ? `Last evidence ${ago(p.last_updated)}` : "No evidence recorded yet"}
        ${p.open_contradictions ? html` · <span style="color:var(--warm)">${p.open_contradictions} contradiction${p.open_contradictions > 1 ? "s need" : " needs"} verification</span>` : ""}</div>
    </div>
    ${aiLine()}
    ${claimBlock("Current blocker", "blocker", brief.blocker, "No active blocker recorded.")}
    ${claimBlock("Next step", "next", n, "No next step recorded.", nextExtra)}
    ${ch ? html`<button class="c-card c-change" data-diff="${ch.event}" aria-label="Show the latest state change">
        <span class="c-label">Latest change · ${ch.event} · ${ago(ch.occurred_at)}</span>
        <span class="chips">${ch.labels.length ? ch.labels.map((l) => html`<span class="tag ${/cleared|resolved/i.test(l) ? "clr" : /contradiction/i.test(l) ? "x" : "upd"}">${l}</span>`) : html`<span class="tag">recorded</span>`}</span>
      </button>` : ""}
    ${ms ? html`<section class="c-card ${ms.at_risk ? "risk" : ""}"><div class="c-label">Next deadline</div>
        <div class="c-value">${ms.title}</div>
        <div class="small ${ms.at_risk ? "" : "muted"}" style="${ms.at_risk ? "color:var(--warm)" : ""}">${ms.state === "overdue" ? "Overdue · " : ""}${fmtFull(ms.due_at)}${ms.at_risk && ms.reasons.length ? ` · ${ms.reasons[0]}` : ""}</div></section>` : ""}
    <div class="c-actions" role="group" aria-label="Quick actions">
      ${QUICK.map(([q, ic]) => html`<button class="btn" data-q="${q}">${icon(ic, "sm")}${q}</button>`)}
      <button class="btn primary" data-compose="${p.id}" ${ctx.canWrite ? "" : html`disabled title="Updates need the model connection"`}>${icon("plus", "sm")}Add update</button>
      <button class="btn" data-open="/p/${p.id}/inbox">${icon("commit", "sm")}Review Git imports${p.pending_imports ? html` <span class="tag x">${p.pending_imports}</span>` : ""}</button>
      <button class="btn" data-open="/p/${p.id}/synthesis">${icon("report", "sm")}Synthesis runs</button>
      <button class="btn" data-open="/p/${p.id}">${icon("overview", "sm")}Open full dashboard</button>
    </div>
    ${lastAnswer ? answerBlock(lastAnswer.q, lastAnswer.a) : ""}`);
}

function aiLine() {
  const rv = brief.review?.review?.review;
  return html`<section class="c-card c-ai" aria-label="Nemotron">
    <div class="c-label">${icon("zap", "sm")} Nemotron</div>
    ${rv ? html`<div class="row" style="gap:6px">${directionBadge(rv.direction)}<span class="c-ai-text">${rv.headline}</span></div>
      ${rv.suggestions[0] ? html`<div class="small"><b>Suggests:</b> ${rv.suggestions[0].title}</div>` : ""}`
      : html`<div class="small muted">No review yet.</div>`}
    ${ctx.canWrite ? html`<div><button class="btn sm ${rv ? "ghost" : "accent"}" id="c-review">${rv ? "Refresh review" : "Review now"}</button></div>` : ""}
  </section>`;
}

async function load(project) {
  try {
    const [b, ev, review] = await Promise.all([api.brief(project), api.events(project), api.latestReview(project).catch(() => null)]);
    brief = { ...b, review: { review: review?.review }, events: Object.fromEntries(ev.events.map((e) => [e.id, e])) };
    render();
  } catch (err) {
    mount(main, html`<div class="error-card"><b>Can't show this project right now.</b><span class="small">${err.message}</span></div>`);
  }
}

async function renderFoot() {
  let s = null;
  try { s = await api.companionSettings(); } catch { /* backend unreachable: shown by load() */ }
  const st = s?.status || {};
  const pr = s?.prefs || {};
  const mon = pr.monitoring && !pr.paused;
  mount(document.getElementById("c-status"), html`<span class="led ${mon ? "on" : ""}" title="${mon ? "Background monitoring is on" : "Background monitoring is off"}"></span>`);
  mount(document.getElementById("c-foot"), html`
    <span>${icon("eye", "sm")} Monitoring ${pr.monitoring ? (pr.paused ? "paused" : "on") : "off"}</span>
    <span>${icon("zap", "sm")} ${st.alive ? (st.hotkey === "registered" ? `${st.hotkey_label || "Hotkey"} active` : "hotkey not registered") : "companion helper not running"}</span>
    <button class="btn ghost sm" data-open="/settings" style="margin-left:auto">Settings</button>
    <button class="btn ghost sm" id="c-quit" title="Stop TaskMaster (server and companion)">Quit</button>`);
}

async function boot() {
  applyPrefs();
  try {
    ctx.meta = await api.meta();
  } catch (err) {
    mount(main, html`<div class="error-card"><b>TaskMaster's server isn't reachable.</b>
      <span class="small">Start it with <span class="mono">python -m statetrace companion</span> (or <span class="mono">serve</span>). ${err.message}</span></div>`);
    return;
  }
  setVerifiable(ctx.meta.verifiable_sources);
  ctx.canWrite = !!ctx.meta.can_write && api.mode === "live";
  ctx.canEdit = api.mode === "live" && ["live", "offline"].includes(ctx.meta.mode);
  ctx.rerender = () => { invalidate(ctx.project); load(ctx.project); };
  const ws = await loadWorkspace().catch(() => ({ projects: [] }));
  if (!ws.projects.length) {
    mount(main, html`<div class="empty sm"><h2>No projects yet</h2><p class="small">Add your first update in the dashboard.</p>
      <button class="btn" data-open="/">Open dashboard</button></div>`);
    return renderFoot();
  }
  const fromHash = (location.hash.match(/^#\/p\/([\w-]+)/) || [])[1];
  const saved = fromHash || savedProject();
  setCurrentProject(ws.projects.some((p) => p.id === saved) ? saved : ws.projects[0].id);
  const sel = document.getElementById("c-project");
  mount(sel, ws.projects.map((p) => html`<option value="${p.id}" ${p.id === ctx.project ? "selected" : ""}>${p.name}</option>`));
  sel.onchange = () => { setCurrentProject(sel.value); lastAnswer = null; load(sel.value); };
  document.getElementById("c-dash").innerHTML = '<svg class="i" viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';
  await load(ctx.project);
  renderFoot();
  // refresh only while the window is visible; this is not background monitoring
  setInterval(() => { if (document.visibilityState === "visible" && !sheetOpen() && !drawerOpen()) { load(ctx.project); renderFoot(); } }, 60000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") { load(ctx.project); renderFoot(); } });
}

async function openInDashboard(path) {
  try { await api.openDashboard(path); }
  catch (err) { toast(err.message, "err"); }
}

document.addEventListener("click", async (e) => {
  if (e.target.closest("#c-review")) {
    const b = e.target.closest("#c-review");
    b.disabled = true; b.textContent = "Nemotron is reviewing…";
    try { await api.review(ctx.project, true); } catch (err) { toast(err.message, "err"); }
    return load(ctx.project);
  }
  if (e.target.closest("#c-quit")) {
    if (!confirm("Quit TaskMaster? The server and companion stop; your data is saved.")) return;
    try { await api.shutdown(); mount(main, html`<div class="empty sm"><h2>TaskMaster has stopped</h2><p class="small">You can close this window.</p></div>`); }
    catch (err) { toast(err.message, "err"); }
    return;
  }
  const t = e.target.closest("[data-ev],[data-claim],[data-diff],[data-compose],[data-q],[data-open],[data-action],#c-dash");
  if (!t) return;
  const proj = ctx.project;
  if (t.id === "c-dash") return openInDashboard(`/p/${proj}`);
  if (t.dataset.ev) { e.preventDefault(); return openEvidence(proj, t.dataset.ev); }
  if (t.dataset.claim) { e.preventDefault(); return openWhy(proj, t.dataset.claim); }
  if (t.dataset.diff) { e.preventDefault(); return openDiff(proj, t.dataset.diff); }
  if (t.dataset.open) { e.preventDefault(); return openInDashboard(t.dataset.open); }
  if (t.dataset.compose !== undefined) { e.preventDefault(); return openComposer({ project: proj }); }
  if (t.dataset.q) {
    t.disabled = true;
    try {
      lastAnswer = { q: t.dataset.q, a: await api.ask(proj, t.dataset.q) };
      render();
      document.querySelector(".c-answer")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) { toast(err.message, "err"); }
    t.disabled = false;
    return;
  }
  if (t.dataset.action === "close-sheet") closeSheet();
  else if (t.dataset.action === "close-drawer") closeDrawer();
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && (e.key === "q" || e.key === "Q")) {  // Ctrl+Q: quit TaskMaster
    e.preventDefault();
    document.getElementById("c-quit")?.click();
    return;
  }
  if (e.key !== "Escape") return;
  if (drawerOpen()) closeDrawer(); else if (sheetOpen()) closeSheet();
});
window.addEventListener("hashchange", () => {
  const id = (location.hash.match(/^#\/p\/([\w-]+)/) || [])[1];
  if (id && id !== ctx.project) { setCurrentProject(id); document.getElementById("c-project").value = id; load(id); }
});
boot();

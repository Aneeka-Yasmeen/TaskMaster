// TaskMaster app: boot, hash router, sidebar, global interactions.
import { api } from "./api.js";
import { openComposer } from "./composer.js";
import { openDiff, openEvidence, openWhy } from "./components.js";
import { milestoneAction, openMilestoneSheet } from "./milestones.js";
import { runReview } from "./assist.js";
import { runCatchUp } from "./catchup.js";
import { applyPrefs, prefs, toggleLayout } from "./prefs.js";
import { ctx, loadWorkspace, savedProject, setCurrentProject } from "./ctx.js";
import { ago, closeDrawer, closeSheet, drawerOpen, html, icon, mount, openDrawer, setNow, setVerifiable, sheetOpen, toast } from "./ui.js";
import { renderActivity } from "./views/activity.js";
import { renderAsk } from "./views/ask.js";
import { renderDecisions } from "./views/decisions.js";
import { renderEvidence } from "./views/evidence.js";
import { renderInbox } from "./views/inbox.js";
import { renderOverview } from "./views/overview.js";
import { renderProject } from "./views/project.js";
import { renderProjects } from "./views/projects.js";
import { renderQuestions } from "./views/questions.js";
import { renderSettings } from "./views/settings.js";
import { renderSynthesis } from "./views/synthesis.js";

const main = document.getElementById("main");

const ROUTES = [
  [/^\/?$/, () => ({ nav: "overview", render: renderOverview })],
  [/^\/projects$/, () => ({ nav: "projects", render: renderProjects })],
  [/^\/p\/([\w-]+)$/, (m) => ({ nav: "project", project: m[1], render: renderProject })],
  [/^\/p\/([\w-]+)\/evidence(?:\/(E\d+))?$/, (m) => ({ nav: "evidence", project: m[1], arg: m[2], render: renderEvidence })],
  [/^\/p\/([\w-]+)\/decisions$/, (m) => ({ nav: "decisions", project: m[1], render: renderDecisions })],
  [/^\/p\/([\w-]+)\/questions$/, (m) => ({ nav: "questions", project: m[1], render: renderQuestions })],
  [/^\/p\/([\w-]+)\/inbox$/, (m) => ({ nav: "inbox", project: m[1], render: renderInbox })],
  [/^\/p\/([\w-]+)\/synthesis$/, (m) => ({ nav: "synthesis", project: m[1], render: renderSynthesis })],
  [/^\/activity$/, () => ({ nav: "activity", render: renderActivity })],
  [/^\/ask(?:\/([\w-]+))?$/, (m) => ({ nav: "ask", project: m[1], render: renderAsk })],
  [/^\/settings$/, () => ({ nav: "settings", render: renderSettings })],
];

function parseRoute() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query] = raw.split("?");
  for (const [re, make] of ROUTES) {
    const m = path.match(re);
    if (m) return { ...make(m), query: new URLSearchParams(query || "") };
  }
  return { nav: "overview", render: renderOverview, query: new URLSearchParams() };
}

let renderToken = 0;
async function route() {
  const r = parseRoute();
  if (r.project) setCurrentProject(r.project);
  document.body.classList.remove("nav-open");
  if (!ctx.workspace) await loadWorkspace().catch(() => {});
  renderSidebar(r.nav);
  const token = ++renderToken;
  main.setAttribute("aria-busy", "true");
  try {
    const arg = { ...r, setCrumbs, isCurrent: () => token === renderToken };
    const view = await r.render(arg);
    if (token !== renderToken) return;
    if (view !== undefined) mount(main, view);
    if (arg.after) arg.after();
  } catch (err) {
    if (token !== renderToken) return;
    setCrumbs([]);
    mount(main, html`<div class="empty"><div class="glyph"></div><h2>Something didn't load</h2><p>${err.message}</p>
      <a class="btn" href="#/">Back to overview</a></div>`);
  } finally {
    main.removeAttribute("aria-busy");
  }
  if (!sheetOpen() && !drawerOpen() && r.focus !== false) main.focus({ preventScroll: true });
}
ctx.rerender = () => route();

function setCrumbs(items) {
  mount(document.getElementById("crumbs"), items.map((c, i) => i === items.length - 1
    ? html`<b>${c.label}</b>` : html`<a href="${c.href}">${c.label}</a><span aria-hidden="true">/</span>`));
}

function renderSidebar(active) {
  const ws = ctx.workspace;
  const pid = ctx.project && ws?.projects.some((p) => p.id === ctx.project) ? ctx.project : ws?.projects[0]?.id;
  if (pid && pid !== ctx.project) setCurrentProject(pid);
  const proj = ws?.projects.find((p) => p.id === pid);
  const link = (key, href, ic, label, extra = "") => html`<a href="${href}" ${active === key ? html`aria-current="page"` : ""}>${icon(ic)}<span>${label}</span>${extra}</a>`;
  const dot = (p) => html`<span class="dot" style="background:${p.flags.includes("needs_review") ? "var(--warm)" : p.flags.includes("blocked") ? "var(--danger)" : p.stale ? "var(--muted)" : "var(--ok)"}"></span>`;
  mount(document.getElementById("nav"), html`
    ${link("overview", "#/", "target", "Today")}
    ${link("projects", "#/projects", "projects", "Projects", ws ? html`<span class="count">${ws.projects.length}</span>` : "")}
    ${link("ask", `#/ask${pid ? "/" + pid : ""}`, "zap", "Ask Nemotron", html`<span class="kbd" style="margin-left:auto">/</span>`)}
    ${ws?.projects.length ? html`
      <div class="nav-label">Project</div>
      <label class="sr" for="proj-switch">Current project</label>
      <div style="position:relative">
        <select id="proj-switch" class="project-switch" style="appearance:none;padding-right:28px" aria-label="Current project">
          ${ws.projects.map((p) => html`<option value="${p.id}" ${p.id === pid ? "selected" : ""}>${p.name}</option>`)}
        </select>
        <span style="position:absolute;right:9px;top:9px;pointer-events:none;color:var(--muted)">${icon("chev", "sm")}</span>
      </div>
      ${link("project", `#/p/${pid}`, "target", "Current state", proj ? dot(proj) : "")}
      ${link("evidence", `#/p/${pid}/evidence`, "evidence", "Evidence", proj ? html`<span class="count">${proj.events}</span>` : "")}
      ${ctx.meta.mode === "snapshot" ? "" : link("inbox", `#/p/${pid}/inbox`, "layers", "Inbox",
        proj?.pending_imports ? html`<span class="count" style="color:var(--warm)">${proj.pending_imports} new</span>` : "")}
      ${ctx.meta.mode === "snapshot" ? "" : link("synthesis", `#/p/${pid}/synthesis`, "report", "Synthesis (Yosys)")}
      <details class="nav-more" ${["decisions", "questions", "activity"].includes(active) || prefs.layout === "detailed" ? "open" : ""}>
        <summary>More</summary>
        ${link("decisions", `#/p/${pid}/decisions`, "decisions", "Decisions")}
        ${link("questions", `#/p/${pid}/questions`, "questions", "Questions", proj?.open_questions ? html`<span class="count">${proj.open_questions}</span>` : "")}
        ${link("activity", "#/activity", "activity", "Activity (all projects)")}
      </details>` : ""}
    <div class="nav-label">Workspace</div>
    ${link("settings", "#/settings", "settings", "Settings")}
  `);
  const m = ctx.meta;
  const led = m.mode === "snapshot" || m.mode === "read_only" ? "warn" : m.can_write ? "on" : "warn";
  const engine = m.mode === "snapshot" ? "Read-only snapshot" : m.mode === "read_only" ? "Read-only mode"
    : m.mode === "offline" ? "Offline · scripted ops" : m.model ? m.model.replace(/^nvidia\//, "") : "Engine not connected";
  mount(document.getElementById("sidebar-foot"), html`
    <button class="btn ghost block" data-action="shortcuts">${icon("menu", "sm")}Keyboard shortcuts<span class="kbd" style="margin-left:auto">?</span></button>
    <div class="engine-pill" title="${m.mode === "live" && m.model ? "State engine: " + m.model + " via Nebius Token Factory" : engine}">
      <span class="led ${led}"></span><span>${engine}</span>${m.mode === "live" && m.model ? html`<span class="muted" style="margin-left:auto">Nebius</span>` : ""}</div>`);
  const sw = document.getElementById("proj-switch");
  if (sw) sw.onchange = () => {
    setCurrentProject(sw.value);
    const r = parseRoute();
    location.hash = ["evidence", "decisions", "questions", "inbox", "synthesis"].includes(r.nav) ? `#/p/${sw.value}/${r.nav}` : r.nav === "ask" ? `#/ask/${sw.value}` : `#/p/${sw.value}`;
  };
}

function renderTopbarRight() {
  const m = ctx.meta;
  const badge = m.mode === "snapshot"
    ? html`<span class="badge b-warm hide-mobile" title="Snapshot taken ${m.snapshot_at}">${icon("eye")}Read-only demo snapshot</span>`
    : m.mode === "read_only" ? html`<span class="badge b-warm hide-mobile">${icon("eye")}Read-only</span>`
    : m.is_demo ? html`<span class="badge b-violet hide-mobile" title="Workspace ${m.workspace}: demo projects processed by the real engine">${icon("flask")}Demo workspace</span>` : "";
  mount(document.getElementById("topbar-right"), html`${badge}
    <span id="sync-chip"></span>
    <div class="seg hide-mobile" role="group" aria-label="Layout (shortcut D)" title="Layout (D)">
      <button data-action="layout" data-value="simple" aria-pressed="${prefs.layout === "simple"}">Simple</button>
      <button data-action="layout" data-value="detailed" aria-pressed="${prefs.layout === "detailed"}">Detailed</button></div>
    ${ctx.meta.mode === "snapshot" ? "" : html`<button class="icon-btn bell" data-action="notices" aria-label="Reminders">${icon("clock")}<span class="bell-n" id="bell-n" hidden></span></button>`}
    <button class="btn primary" data-compose="" ${ctx.canWrite ? "" : html`disabled title="Updates need the live engine"`}>${icon("plus")}Add update<span class="kbd hide-mobile">N</span></button>`);
  document.querySelector('[data-action="open-nav"]').innerHTML = '<svg class="i" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
  document.querySelector('[data-action="close-nav"].icon-btn').innerHTML = '<svg class="i" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
}

// global interactions (event delegation) ------------------------------------------------
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-ev],[data-claim],[data-diff],[data-compose],[data-action],[data-ms-action],[data-commit],[data-add-milestone],[data-review],[data-catchup]");
  if (!t) return;
  const link = e.target.closest("a[href]");
  if (link && link !== t && t.contains(link)) return; // let links inside clickable rows navigate
  const proj = t.dataset.project || t.closest("[data-scope-project]")?.dataset.scopeProject || ctx.project;
  if (t.dataset.ev) { e.preventDefault(); e.stopPropagation(); openEvidence(proj, t.dataset.ev); return; }
  if (t.dataset.claim) { e.preventDefault(); openWhy(proj, t.dataset.claim); return; }
  if (t.dataset.diff) { e.preventDefault(); openDiff(proj, t.dataset.diff); return; }
  if (t.dataset.msAction) { e.preventDefault(); milestoneAction(t.dataset.msAction, t.dataset.msId, proj); return; }
  if (t.dataset.commit) { e.preventDefault(); openMilestoneSheet({ project: proj, title: t.dataset.title || "", source_claim: t.dataset.commit }); return; }
  if (t.dataset.addMilestone !== undefined) { e.preventDefault(); openMilestoneSheet({ project: t.dataset.addMilestone || proj, title: t.dataset.msTitle || "" }); return; }
  if (t.dataset.review) { e.preventDefault(); runReview(t.dataset.review, t.dataset.force === "1"); return; }
  if (t.dataset.catchup) { e.preventDefault(); runCatchUp(t.dataset.catchup, t.dataset.force === "1"); return; }
  if (t.dataset.compose !== undefined) { e.preventDefault(); openComposer({ project: t.dataset.compose || ctx.project, prefill: t.dataset.prefill || "" }); return; }
  const a = t.dataset.action;
  if (a === "open-nav") document.body.classList.add("nav-open");
  else if (a === "close-nav") document.body.classList.remove("nav-open");
  else if (a === "close-sheet") closeSheet();
  else if (a === "close-drawer") closeDrawer();
  else if (a === "notices") openNotices();
  else if (a === "layout" || a === "toggle-layout") { if (a === "layout") { if (prefs.layout !== t.dataset.value) toggleLayout(); } else toggleLayout(); renderTopbarRight(); route(); }
  else if (a === "shortcuts") openShortcuts();
  else if (a === "sync-now") syncNow();
  else if (a === "dismiss-notice") dismissNotice(+t.dataset.id);
  else if (a === "scroll") document.getElementById(t.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("[data-claim][role=button], [data-diff][role=button]")) { e.preventDefault(); e.target.click(); return; }
  if ((e.ctrlKey || e.metaKey) && (e.key === "q" || e.key === "Q") && api.mode === "live") {  // Ctrl+Q: quit
    e.preventDefault();
    quitTaskMaster();
    return;
  }
  if (e.key === "Escape") {
    if (drawerOpen()) closeDrawer(); else if (sheetOpen()) closeSheet(); else document.body.classList.remove("nav-open");
    return;
  }
  if (e.target.closest?.("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (sheetOpen() || drawerOpen()) return;
  if (e.key === "n" && ctx.canWrite) { e.preventDefault(); openComposer({ project: ctx.project }); }
  else if (e.key === "/") { e.preventDefault(); location.hash = `#/ask${ctx.project ? "/" + ctx.project : ""}`; }
  else if (e.key === "r" && ctx.canWrite && ctx.project) { e.preventDefault(); runReview(ctx.project, true); }
  else if (e.key === "c" && ctx.canWrite && ctx.project && document.getElementById(`catchup-${ctx.project}`)) { e.preventDefault(); runCatchUp(ctx.project, true); }
  else if (e.key === "d") { e.preventDefault(); toggleLayout(); renderTopbarRight(); route(); }
  else if (e.key === "t") { e.preventDefault(); location.hash = "#/"; }
  else if (e.key === "?") { e.preventDefault(); openShortcuts(); }
});

async function boot() {
  try {
    ctx.meta = await api.meta();
  } catch (err) {
    mount(main, html`<div class="empty"><div class="glyph"></div><h2>TaskMaster can't start</h2><p>${err.message}</p></div>`);
    return;
  }
  applyPrefs();
  setVerifiable(ctx.meta.verifiable_sources);
  if (ctx.meta.snapshot_at) setNow(ctx.meta.snapshot_at);
  ctx.canWrite = !!ctx.meta.can_write && api.mode === "live";
  ctx.canEdit = api.mode === "live" && ["live", "offline"].includes(ctx.meta.mode);
  ctx.project = savedProject();
  try { await loadWorkspace(); } catch (err) { toast(err.message, "err"); }
  renderTopbarRight();
  window.addEventListener("hashchange", route);
  route();
  if (api.mode === "live" && ctx.meta.mode !== "read_only") {
    pollNotices(true); setInterval(pollNotices, 60000);
    pollSync(); setInterval(pollSync, 20000);
  }
}

// Nemotron / offline status --------------------------------------------------------------------
async function pollSync() {
  let s;
  try { s = await api.sync(); } catch { s = null; }
  const el = document.getElementById("sync-chip");
  if (!el) return;
  if (!s) { mount(el, html`<span class="badge b-danger">${icon("alert")}Server unreachable</span>`); return; }
  if (s.queued_total) {
    mount(el, html`<button class="badge b-warm sync-btn" data-action="sync-now" title="Updates saved while Nemotron was unreachable. They apply automatically when it's back; click to try now.">
      ${icon("retry")}${s.queued_total} waiting for Nemotron · Sync now</button>`);
  } else if (!s.assistant) {
    mount(el, html`<span class="badge b-muted" title="${ctx.meta.model_error || ""}">${icon("eye")}Nemotron not connected</span>`);
  } else if (s.online === false) {
    mount(el, html`<span class="badge b-warm">${icon("clock")}Nemotron offline</span>`);
  } else {
    mount(el, html`<span class="badge b-accent hide-mobile" title="${s.model}">${icon("zap")}Nemotron ready</span>`);
  }
}
async function syncNow() {
  toast("Trying to reach Nemotron…");
  try {
    const s = await api.syncNow();
    toast(s.queued_total ? "Nemotron still isn't reachable. Your updates are safe and will sync automatically." : "All waiting updates were applied.",
      s.queued_total ? "err" : "ok");
    await loadWorkspace(true).catch(() => {});
    route();
  } catch (err) { toast(err.message, "err"); }
  pollSync();
}

async function quitTaskMaster() {
  if (!confirm("Quit TaskMaster? The server (and the companion, if it's hosting it) will stop. Your data is saved.")) return;
  try {
    await api.shutdown();
    closeDrawer(); closeSheet();
    mount(main, html`<div class="empty"><div class="glyph"></div><h2>TaskMaster has stopped</h2>
      <p>Everything is saved. You can close this tab. To start again, double-click <span class="mono">scripts\\TaskMaster-Companion.cmd</span>
      or run <span class="mono">python -m statetrace --db demo.db companion</span>.</p></div>`);
  } catch (err) { toast(err.message, "err"); }
}

function openShortcuts() {
  const rows = [
    ["Ctrl + Alt + T", "Open the compact TaskMaster window from any app (needs the companion running)"],
    ["N", "Add an update to the current project"],
    ["/", "Ask Nemotron about the current project"],
    ["C", "Where did I leave off? Reconstruct the current project with Nemotron"],
    ["R", "Ask Nemotron to review the current project"],
    ["T", "Go to Today"],
    ["D", "Switch between Simple and Detailed layout"],
    ["?", "Show these shortcuts"],
    ["Ctrl + Enter", "Submit an update"],
    ["Esc", "Close a panel or dialog"],
    ["Ctrl + Q", "Quit TaskMaster (server and companion; asks first, data is saved)"],
  ];
  openDrawer(html`<div class="drawer-head"><h2 id="drawer-title">Keyboard shortcuts</h2>
      <button class="icon-btn x" data-action="close-drawer" aria-label="Close">${icon("x")}</button></div>
    <div class="drawer-body"><dl class="kvlist shortcuts">${rows.map(([k, d]) => html`<dt>${k.split(" + ").map((x, i) => html`${i ? " + " : ""}<span class="kbd">${x}</span>`)}</dt><dd>${d}</dd>`)}</dl></div>`);
}

// reminders (deduplicated server-side; shown in-app, silent during quiet hours) -------------
let notices = { notices: [], quiet: true };
const seen = new Set();
async function pollNotices(first = false) {
  try { notices = await api.notices(); } catch { return; }
  const n = document.getElementById("bell-n");
  if (n) { n.hidden = !notices.notices.length; n.textContent = notices.notices.length; }
  for (const x of notices.notices) {
    if (!seen.has(x.id) && !first && !notices.quiet) toast(`${x.title}: ${x.reason}`, x.kind === "milestone_overdue" ? "err" : "ok");
    seen.add(x.id);
  }
}
function openNotices() {
  const list = notices.notices;
  openDrawer(html`<div class="drawer-head"><div><h2 id="drawer-title">Reminders</h2>
      <div class="small muted">${notices.quiet ? "Quiet hours: shown here, no pop-ups." : "Each issue is reported once."} <a href="#/settings" data-action="close-drawer">Settings</a></div></div>
      <button class="icon-btn x" data-action="close-drawer" aria-label="Close">${icon("x")}</button></div>
    <div class="drawer-body">${list.length ? html`<div class="panel">${list.map((x) => html`<div class="item">
        <div class="row small"><span class="badge ${x.kind === "milestone_overdue" ? "b-danger" : x.kind === "stale" ? "b-muted" : "b-warm"}">${icon(x.kind === "stale" ? "clock" : "alert")}${x.kind === "stale" ? "Stale" : x.kind === "milestone_overdue" ? "Overdue" : "Due"}</span>
          <a href="#/p/${x.project}" data-action="close-drawer">${x.project}</a><span class="muted">${ago(x.created_at)}</span>
          ${ctx.canEdit ? html`<button class="btn ghost sm" style="margin-left:auto" data-action="dismiss-notice" data-id="${x.id}">Dismiss</button>` : ""}</div>
        <div class="t">${x.title}</div><div class="small dim">Why: ${x.reason}</div></div>`)}</div>`
      : html`<div class="empty sm"><h2>Nothing needs your attention</h2><p class="small">Reminders appear for milestones you set and for projects that go stale.</p></div>`}</div>`);
}
async function dismissNotice(id) {
  try { await api.dismissNotice(id); await pollNotices(); openNotices(); } catch (err) { toast(err.message, "err"); }
}
boot();

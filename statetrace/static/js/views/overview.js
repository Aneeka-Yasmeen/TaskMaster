// Today: the most urgent project first (deterministic priority with stated reasons), then the rest.
import { api } from "../api.js";
import { directionBadge } from "../assist.js";
import { ctx, loadWorkspace } from "../ctx.js";
import { upcomingLine } from "../milestones.js";
import { ago, confMeter, fmtFull, healthBadge, html, icon, sampleBadge, spark, toast } from "../ui.js";

export function projectCard(p) {
  const blocker = p.current_blocker, next = p.next_step;
  return html`<a class="pcard" href="#/p/${p.id}">
    <div class="top"><span class="name">${p.name}</span><span style="margin-left:auto">${sampleBadge(p)}${healthBadge(p.health)}</span></div>
    <div class="goal">${p.goal ? p.goal.value : "No goal recorded yet"}</div>
    <dl class="kv">
      <dt>Blocker</dt><dd class="${blocker ? "blocker" : "none"}">${blocker ? blocker.value : "None"}</dd>
      <dt>Next</dt><dd class="${next ? "" : "none"}">${next ? next.value : "Not recorded"}</dd>
    </dl>
    <div class="foot">
      <span title="${p.last_updated || ""}">${icon("clock", "sm")} ${ago(p.last_updated)}</span>
      ${spark(p.activity)}
      ${p.open_contradictions ? html`<span style="color:var(--warm)">${icon("alert", "sm")} ${p.open_contradictions}</span>` : ""}
      <span style="margin-left:auto">${confMeter(p.confidence, p.support)}</span>
    </div>
  </a>`;
}

export function emptyWorkspace() {
  return html`${intro(true)}<div class="empty">
    <div class="glyph"></div>
    <h2>Your project state starts here.</h2>
    <p>Create a project and add your first engineering update: a note, a sim log, a synthesis report. TaskMaster will reconstruct the project state as you work.</p>
    ${ctx.canEdit ? html`<div class="row" style="gap:8px;justify-content:center">
        <button class="btn primary" data-compose="">${icon("plus")}Add first update</button>
        <button class="btn" id="load-sample" title="Loads a synthetic FFT accelerator project. Works without an API key.">${icon("layers")}Load sample project</button></div>
      <p class="small muted">The sample is synthetic and replays recorded operations — it is not a live Nemotron run, and it's labelled “Sample data” everywhere.</p>`
      : html`<p class="small muted">This instance is read-only.</p>`}
  </div>`;
}

// First-run explanation: what this is, why it isn't a chatbot, and the one thing to try.
const INTRO_KEY = "tm.intro.dismissed";
const introDismissed = () => { try { return localStorage.getItem(INTRO_KEY) === "1"; } catch { return false; } };
function intro(force = false) {
  if (!force && introDismissed()) return "";
  return html`<section class="intro panel panel-pad" id="intro" aria-label="What TaskMaster does">
    <div class="row" style="gap:8px"><h2 style="margin:0;flex:1">${icon("target")} Pick up any project exactly where you left it</h2>
      ${force ? "" : html`<button class="btn ghost sm" id="intro-dismiss" aria-label="Dismiss introduction">Got it</button>`}</div>
    <ol class="intro-steps">
      <li><b>Log evidence as you work</b> — notes, sim logs, Yosys reports, commits. Nothing is ever edited or deleted.</li>
      <li><b>Nemotron proposes state changes; a deterministic validator decides.</b> A claim is <i>verified</i> only when a log, test or report backs it. Conflicts become contradictions, not overwrites.</li>
      <li><b>Ask “Where did I leave off?”</b> You get the blocker, the next action and what's still uncertain, each linked to its evidence.</li>
    </ol>
    <p class="small muted" style="margin:0">Not a chatbot: answers come from a versioned, evidence-backed project state, so you can check every claim and see when it last changed.</p>
  </section>`;
}

export function bindIntro() {
  const d = document.getElementById("intro-dismiss");
  if (d) d.onclick = () => { try { localStorage.setItem(INTRO_KEY, "1"); } catch {} document.getElementById("intro")?.remove(); };
  const s = document.getElementById("load-sample");
  if (s) s.onclick = async () => {
    s.disabled = true;
    s.textContent = "Loading sample…";
    try {
      const r = await api.loadSample();
      toast(`Loaded ${r.name}: ${r.events} evidence items replayed with recorded operations`);
      await loadWorkspace(true);
      location.hash = `#/p/${r.id}`;
    } catch (err) { toast(err.message, "err"); s.disabled = false; s.textContent = "Load sample project"; }
  };
}

const greeting = () => { const h = new Date().getHours(); return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };

function countdown(d) {
  if (!d) return "";
  const s = (new Date(d.due_at) - new Date()) / 1000;
  const txt = s < 0 ? "overdue" : s < 86400 ? `${Math.max(1, Math.round(s / 3600))} h left` : `${Math.round(s / 86400)} days left`;
  return html`<div class="countdown ${s < 0 ? "over" : s < 3 * 86400 ? "soon" : ""}" title="${fmtFull(d.due_at)}">
    <span class="cd-n">${txt}</span><span class="cd-t">${d.title}</span></div>`;
}

function focusCard(p) {
  const pr = p.priority;
  return html`<section class="focus" aria-label="Focus now: ${p.name}">
    <div class="focus-top">
      <span class="focus-k">${icon("target", "sm")} Focus now</span>
      ${pr.reasons.length ? html`<span class="why-first" title="${ctx.workspace.priority_rules}">why: ${pr.reasons.slice(0, 3).join(" · ")}</span>` : ""}
    </div>
    <div class="focus-main">
      <div style="min-width:0">
        <a class="focus-name" href="#/p/${p.id}">${p.name}</a> ${sampleBadge(p)}
        <div class="focus-goal">${p.goal ? p.goal.value : "No goal recorded yet"}</div>
      </div>
      ${countdown(pr.next_deadline)}
    </div>
    <div class="focus-grid">
      <div class="fg-cell ${p.current_blocker ? "blocker" : "clear"}"><div class="fg-k">Blocker</div>
        <div class="fg-v">${p.current_blocker ? p.current_blocker.value : "Nothing is blocking progress"}</div></div>
      <div class="fg-cell next"><div class="fg-k">Next step</div>
        <div class="fg-v">${p.next_step ? p.next_step.value : "No next step recorded"}</div></div>
    </div>
    <div class="focus-ai">
      <span class="ai-mark" aria-hidden="true">${icon("zap")}</span>
      ${p.review ? html`${directionBadge(p.review.direction)}<span class="fa-text">${p.review.headline}
          ${p.review.top_suggestion ? html`<span class="fa-sg">Suggests: ${p.review.top_suggestion}</span>` : ""}</span>`
        : html`<span class="fa-text muted">Nemotron hasn't reviewed this project yet.</span>`}
      ${ctx.canWrite ? html`<button class="btn sm ${p.review ? "ghost" : "accent"}" data-review="${p.id}" data-force="${p.review ? "1" : ""}">${p.review ? "Refresh review" : "Review with Nemotron"}</button>` : ""}
    </div>
    <div class="focus-actions">
      <a class="btn primary" href="#/p/${p.id}" title="Opens the project with its catch-up: blocker, next action and what's uncertain">${icon("arrow")}Where did I leave off?</a>
      <a class="btn" href="#/ask/${p.id}">${icon("ask")}Ask Nemotron</a>
      ${ctx.canWrite ? html`<button class="btn" data-compose="${p.id}">${icon("plus")}Add update</button>` : ""}
    </div>
  </section>`;
}

function upNextRow(p) {
  const pr = p.priority;
  return html`<a class="upnext" href="#/p/${p.id}">
    <span class="un-name">${p.name} ${sampleBadge(p)}</span>
    <span class="un-why">${pr.reasons.length ? pr.reasons.slice(0, 2).join(" · ") : p.events ? "nothing urgent" : "no evidence yet"}</span>
    ${p.review ? directionBadge(p.review.direction) : html`<span></span>`}
    <span class="un-when muted">${pr.next_deadline ? fmtFull(pr.next_deadline.due_at) : ago(p.last_updated)}</span>
  </a>`;
}

export async function renderOverview(r) {
  const { setCrumbs } = r;
  setCrumbs([{ label: "Today" }]);
  r.after = bindIntro;
  const [ws, ms] = await Promise.all([loadWorkspace(true), api.milestones().catch(() => ({ milestones: [] }))]);
  if (!ws.projects.length) return emptyWorkspace();
  const [first, ...rest] = ws.projects;
  const h = ws.health;
  const upcoming = ms.milestones.filter((m) => m.status === "open").slice(0, 5);
  const tile = (n, label, tip, color) => html`<div title="${tip}"><span class="n" style="${n && color ? `color:${color}` : ""}">${n}</span><span class="l">${label}</span></div>`;
  return html`
    <div class="today-head">
      <h1>${greeting()}.</h1>
      <p class="sub">Here's what needs you first, ranked by deadlines, blockers and what you marked important.</p>
    </div>
    ${intro()}
    ${focusCard(first)}
    ${rest.length ? html`<div class="section">
      <div class="section-head"><h2>Up next</h2><a class="right small" href="#/projects">All projects</a></div>
      <div class="panel upnext-list">${rest.map(upNextRow)}</div>
    </div>` : ""}
    <div class="detailed-only">
      ${upcoming.length ? html`<div class="section">
        <div class="section-head"><h2>Upcoming deadlines</h2><span class="right small muted">set by you · flagged only by stated rules</span></div>
        <div class="panel upcoming-list">${upcoming.map(upcomingLine)}</div>
      </div>` : ""}
      <div class="section">
        <div class="section-head"><h2>Project health</h2><span class="right small muted">computed from claims, not estimated</span></div>
        <div class="health-strip">
          ${tile(h.active, "Active", "Projects with evidence in the last 7 days")}
          ${tile(h.blocked, "Blocked", ws.rules.blocked, "var(--danger)")}
          ${tile(h.updated_today, "Updated today", "Projects with new evidence today")}
          ${tile(h.needs_review, "Needs review", "Stale state or unresolved contradiction", "var(--warm)")}
        </div>
      </div>
      <div class="section">
        <div class="section-head"><h2>All projects</h2></div>
        <div class="grid-3">${ws.projects.map(projectCard)}</div>
      </div>
    </div>`;
}

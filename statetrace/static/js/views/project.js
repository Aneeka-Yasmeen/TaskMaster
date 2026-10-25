// Project detail: the reconstructed state, how it got here, and why it is believed.
import { api } from "../api.js";
import { contradictionCard, diffView, errorTag, fieldLabel, heldBack } from "../components.js";
import { ctx, loadWorkspace, projectBundle } from "../ctx.js";
import { milestoneRow } from "../milestones.js";
import { reviewCard } from "../assist.js";
import { catchupCard } from "../catchup.js";
import {
  ago, confMeter, daysSince, sampleBadge, evChips, fmtDate, fmtFull, fmtTime, healthBadge, html, icon, isArtifact, mount, srcIcon, toast, vmark,
} from "../ui.js";

const OPWORD = { ADD: "set", UPDATE: "updated", INVALIDATE: "cleared", REINFORCE: "reinforced" };
const FIELDNAME = { current_blocker: "Blocker", next_step: "Next step", current_status: "Status", last_action: "Last action",
  goal: "Goal", decisions: "Decision", attempts: "Attempt", open_questions: "Question" };

export function opLabels(t) {
  if (!t) return [html`<span class="tag">not processed</span>`];
  if (t.error) return [errorTag(t.error)];
  const seen = new Set(), out = [];
  for (const a of t.applied) {
    let l, cls = "upd";
    if (a.op === "NOOP") continue;
    if (a.op === "CONTRADICT") { l = `Contradiction ${a.contradiction}`; cls = "x"; }
    else if (a.op === "RESOLVE") { l = `${a.contradiction} resolved${a.auto ? " (moot)" : ""}`; cls = "clr"; }
    else if (a.field === "status_items") l = `${(a.key || "status").replace(/_/g, " ")} ${OPWORD[a.op] || ""}`;
    else if (a.field === "open_questions" && a.op === "INVALIDATE") { l = "Question answered"; cls = "clr"; }
    else if (a.field === "current_blocker" && a.op === "INVALIDATE") { l = "Blocker cleared"; cls = "clr"; }
    else if (["attempts", "decisions", "open_questions"].includes(a.field) && a.op === "ADD") l = `${FIELDNAME[a.field]} recorded`;
    else l = `${FIELDNAME[a.field] || a.field} ${OPWORD[a.op] || a.op.toLowerCase()}`;
    if (!seen.has(l)) { seen.add(l); out.push(html`<span class="tag ${cls}">${l}</span>`); }
  }
  if (t.rejected.length) out.push(html`<span class="tag rej" title="Proposed by the model but rejected by the validator">${t.rejected.length} held back</span>`);
  if (!out.length) out.push(html`<span class="tag">No change to current state</span>`);
  return out;
}

export function timelineItem(e, t, events, lateIds, project) {
  const art = isArtifact(e.source);
  return html`<div class="tl-item">
    <div class="when"><b>${fmtTime(e.occurred_at)}</b>${fmtDate(e.occurred_at)}</div>
    <div class="rail"><span class="node ${art ? "artifact" : "report"}" title="${art ? "Artifact" : "Human report"}">${srcIcon(e.source)}</span></div>
    <button class="tl-body" data-diff="${e.id}" data-project="${project}" aria-label="Show the state change caused by ${e.id}">
      <div class="row small" style="gap:6px;margin-bottom:2px"><span class="mono" style="color:var(--accent);font-weight:600">${e.id}</span>
        ${lateIds.has(e.id) ? html`<span class="late small">${icon("history", "sm")} late-arriving</span>` : ""}
        ${e.ref ? html`<span class="mono muted">${e.ref}</span>` : ""}</div>
      <div class="txt">${e.text.length > 200 ? e.text.slice(0, 200) + "…" : e.text}</div>
      <div class="chips">${opLabels(t)}</div>
    </button>
  </div>`;
}

export const lateSet = (list) => {
  const late = new Set();
  let max = "";
  for (const e of list) { if (e.occurred_at < max) late.add(e.id); else max = e.occurred_at; }
  return late;
};

function stateCard(kind, label, ic, c, events, empty, footer = "") {
  return html`<section class="scard ${kind}" aria-label="${label}">
    <div class="label">${icon(ic, "sm")}${label}</div>
    ${c ? html`<div class="value" title="${c.value}">${c.value}</div>
      <div class="meta">${vmark(c)}${evChips(c.evidence, events)}<span class="small muted">${ago(c.as_of)}</span></div>
      <button class="btn ghost sm why" data-claim="${c.id}" title="Why does TaskMaster believe this?">Why?</button>`
    : html`<div class="value" style="color:var(--muted)">${empty}</div>`}
    ${footer}
  </section>`;
}

// A next step is *proposed* from evidence; it becomes a *commitment* only when the user commits.
function commitmentFooter(next, milestones, historical) {
  if (!next || historical) return "";
  const m = milestones.find((x) => x.source_claim === next.id && x.status === "open");
  if (m) {
    return html`<div class="commit committed">${icon("check", "sm")}<b>Committed</b>${m.due_at ? html` · due ${fmtFull(m.due_at)}` : ""}
      ${m.at_risk ? html`<span class="risk-dot" title="${m.reasons.join("; ")}">${icon("alert", "sm")} at risk</span>` : ""}</div>`;
  }
  return html`<div class="commit proposed"><span title="TaskMaster proposed this from the evidence; you haven't committed to it">Proposed from evidence</span>
    ${ctx.canEdit ? html`<button class="btn sm accent" data-commit="${next.id}" data-title="${next.value.slice(0, 200)}">Commit…</button>` : ""}</div>`;
}

const LEGEND = html`<div class="legend" aria-label="How to read claims">
  <span class="vmark verified">${icon("shield", "sm")}Verified: backed by a log, report or test</span>
  <span class="vmark reported">${icon("half", "sm")}Reported: a person said so</span>
  <span class="vmark contested">${icon("alert", "sm")}Contested: conflicting evidence</span>
  <span class="muted"><s>Superseded</s>: replaced by newer evidence</span>
  <span class="muted">${icon("clock", "sm")} Stale: no evidence for 7+ days</span>
</div>`;

function stateArea(view, summary, events, historical, milestones = []) {
  const f = view.fields;
  const one = (k) => f[k][0] || null;
  const blocker = one("current_blocker");
  const items = [...f.status_items].sort((a, b) => (a.as_of < b.as_of ? 1 : -1));
  const supp = summary.support;
  const pct = supp.total ? Math.round((supp.verified / supp.total) * 100) : 0;
  return html`
    <div class="state-grid">
      ${blocker ? stateCard("blocker", "Current blocker", "block", blocker, events)
        : html`<section class="scard clear"><div class="label">${icon("check", "sm")}Current blocker</div><div class="value">Nothing is blocking progress</div>
          <div class="meta small muted">No active blocker in the evidence${view.ended.some((c) => c.field === "current_blocker") ? " — earlier blockers were cleared" : ""}.</div></section>`}
      ${stateCard("next", "Next step", "arrow", one("next_step"), events, "No next step recorded",
        commitmentFooter(one("next_step"), milestones, historical))}
      ${stateCard("", "Last action", "history", one("last_action"), events, "Nothing recorded yet")}
      <section class="scard" aria-label="Confidence">
        <div class="label">${icon("shield", "sm")}Confidence</div>
        ${historical ? html`<div class="small muted">Shown for the latest version only.</div>` : html`
        <div class="confbig ${summary.confidence}"><span class="lvl">${summary.confidence}</span>
          <span class="meter"><i style="width:${pct}%"></i></span>
          <span class="small dim">${supp.verified} of ${supp.total} current-state claims verified by artifacts${summary.open_contradictions ? `; ${summary.open_contradictions} unresolved contradiction${summary.open_contradictions > 1 ? "s" : ""}` : ""}${summary.stale ? "; state is stale" : ""}.</span></div>`}
      </section>
    </div>
    <div class="detailed-only">
    ${one("current_status") ? html`<div class="panel panel-pad row" style="margin-top:12px;gap:10px">
      <span class="small muted" style="font-weight:600;text-transform:uppercase;letter-spacing:.08em;font-size:10.5px">Status</span>
      <span style="flex:1;min-width:200px">${one("current_status").value}</span>${vmark(one("current_status"))}${evChips(one("current_status").evidence, events, { short: true })}
      <button class="btn ghost sm" data-claim="${one("current_status").id}">Why?</button></div>` : ""}
    ${LEGEND}
    ${items.length ? html`<div class="panel table-wrap" style="margin-top:12px">
      <table class="table stackable"><thead><tr><th>Subject</th><th>Current value</th><th>Support</th><th>Evidence</th><th>As of</th></tr></thead>
      <tbody>${items.map((c) => html`<tr data-claim="${c.id}" tabindex="0" role="button" aria-label="Why: ${c.key}">
        <td class="subj">${(c.key || "").replace(/_/g, " ")}</td><td>${c.value}</td><td>${vmark(c)}</td>
        <td>${evChips(c.evidence, events, { short: true })}</td><td class="small muted nowrap">${fmtDate(c.as_of)}</td></tr>`)}</tbody></table></div>` : ""}
    </div>`;
}

export async function renderProject(r) {
  const [b, rev, ws, syn, cu, props] = await Promise.all([projectBundle(r.project, true), api.latestReview(r.project).catch(() => null),
    loadWorkspace().catch(() => null), api.synth(r.project).catch(() => null), api.catchUp(r.project).catch(() => null),
    api.proposals(r.project).catch(() => ({ proposals: [] }))]);
  const s = b.summary, v = b.view, events = b.events;
  r.setCrumbs([{ label: "Projects", href: "#/projects" }, { label: s.name }]);
  const prio = ws?.projects.find((p) => p.id === s.id)?.priority;
  const prioControl = ctx.canEdit ? html`<label class="prio">Priority
      <select data-priority="${s.id}" aria-label="Project priority">${["high", "normal", "low"].map((x) =>
        html`<option value="${x}" ${prio?.priority === x ? "selected" : ""}>${x[0].toUpperCase() + x.slice(1)}</option>`)}</select></label>` : "";
  r.after = () => bindPriority();
  if (!s.events) {
    return html`<div class="page-head"><div style="flex:1"><h1>${s.name}</h1></div>${prioControl}</div>
      <div class="empty"><div class="glyph"></div><h2>${s.name} has no evidence yet</h2>
      <p>Add the first update and TaskMaster will start reconstructing its state.</p>
      ${ctx.canWrite ? html`<button class="btn primary" data-compose="${s.id}">${icon("plus")}Add first update</button>` : ""}</div>`;
  }
  const openX = Object.values(b.state.contradictions).filter((x) => x.status === "open");
  const late = lateSet(b.eventList);
  const recent = b.eventList.slice(-6);
  const totalClaims = Object.keys(b.state.claims).length;
  const activeClaims = Object.values(b.state.claims).filter((c) => c.status === "active").length;
  const heldBackN = Object.values(b.transitions).reduce((a, t) => a + (t.rejected?.length || 0), 0);
  const decisions = [...v.fields.decisions, ...v.ended.filter((c) => c.field === "decisions")];
  const qs = v.fields.open_questions;
  const staleDays = daysSince(s.last_updated);

  r.after = () => {
    bindPriority();
    const slider = document.getElementById("ver");
    const label = document.getElementById("ver-label");
    const area = document.getElementById("state-area");
    if (slider) slider.oninput = async () => {
      const ver = +slider.value;
      const latest = ver === b.state.version;
      label.textContent = latest ? `v${ver} · latest` : `v${ver}`;
      document.getElementById("hist-note").hidden = latest;
      const data = latest ? { view: v, state: b.state } : await api.state(s.id, ver).catch(() => null);
      if (!data || +slider.value !== ver) return;
      document.getElementById("hist-note-text").textContent = latest ? "" : `Viewing the state as it was after ${data.state.last_event_id} (${fmtFull(data.state.last_updated)}).`;
      mount(area, stateArea(data.view, s, events, !latest, b.milestones || []));
    };
    const last = [...b.eventList].reverse().find((e) => b.transitions[e.id] && !b.transitions[e.id].error
      && b.transitions[e.id].applied.some((a) => a.op !== "NOOP"));
    const box = document.getElementById("last-diff");
    if (last && box) api.transition(s.id, last.id).then((d) => {
      if (!r.isCurrent()) return;
      mount(box, html`<div class="section-head"><h2>Latest state change</h2><span class="right small muted">${ago(d.event.occurred_at)} · from ${d.event.id}</span></div>
        ${diffView(d, events, { onlyChanged: true })}${heldBack(d.transition)}`);
    }).catch(() => { box.hidden = true; });
  };

  return html`
    <div class="page-head">
      <div style="min-width:0;flex:1">
        <div class="row" style="gap:10px"><h1>${s.name}</h1>${sampleBadge(s)}${healthBadge(s.health)}
          ${s.flags.filter((f) => f !== s.health).map((f) => healthBadge(f))}</div>
        <div class="sub">${s.goal ? html`${s.goal.value} ${evChips(s.goal.evidence, events, { short: true })}` : "No goal recorded yet."}</div>
        <div class="row small muted" style="margin-top:8px;gap:14px">
          <span>${icon("clock", "sm")} Updated ${ago(s.last_updated)}</span>
          <span>${icon("shield", "sm")} Last verified ${s.last_verified ? ago(s.last_verified) : "never"}</span>
          <span class="mono">v${s.version} · ${s.events} evidence</span>
          ${prio?.reasons.length ? html`<span title="${ws.priority_rules}">${icon("target", "sm")} ${prio.reasons.slice(0, 3).join(" · ")}</span>` : ""}
        </div>
      </div>
      ${prioControl}
    </div>
    ${b.pending_imports || b.failed_imports ? html`<div class="banner info"><span class="ic">${icon("commit")}</span><div class="body">
      <div class="title">${b.pending_imports ? `${b.pending_imports} new commit${b.pending_imports > 1 ? "s" : ""} waiting for review` : ""}${b.pending_imports && b.failed_imports ? " · " : ""}${b.failed_imports ? `${b.failed_imports} import${b.failed_imports > 1 ? "s" : ""} saved but not applied` : ""}</div>
      <div class="small dim">Imported evidence doesn't change the state until you accept it.</div></div>
      <div class="actions"><a class="btn sm" href="#/p/${s.id}/inbox">Open inbox</a></div></div>` : ""}

    ${props.proposals.length ? html`<div class="banner warn"><span class="ic">${icon("eye")}</span><div class="body">
      <div class="title">${props.proposals.length} proposed state change${props.proposals.length > 1 ? "s" : ""} waiting for your review</div>
      <div class="small dim">From imported synthesis reports. The state below doesn't include them until you apply them.</div></div>
      <div class="actions"><a class="btn sm" href="#/p/${s.id}/synthesis">Review</a></div></div>` : ""}

    ${s.stale ? html`<div class="banner stale"><span class="ic">${icon("clock")}</span><div class="body">
      <div class="title">State may be stale</div>
      <div class="small dim">No new evidence for ${staleDays} days; last verified ${s.last_verified ? ago(s.last_verified) : "never"}. Some of this may no longer reflect the current implementation.</div></div>
      <div class="actions"><a class="btn sm" href="#/ask/${s.id}?q=${encodeURIComponent("Where did I leave off?")}">Review project state</a></div></div>` : ""}

    ${catchupCard(s.id, cu, events)}

    ${reviewCard(s.id, rev, events)}

    <div class="flow detailed-only" aria-label="Evidence to next action">
      <a class="flow-step" href="#/p/${s.id}/evidence"><span class="k">${icon("evidence", "sm")}Evidence</span><span class="v">${s.events} items</span>
        <span class="s">latest ${b.eventList.at(-1).id} · ${ago(s.last_updated)}</span></a>
      <a class="flow-step" href="#/activity"><span class="k">${icon("layers", "sm")}Understanding</span><span class="v">${totalClaims} claims</span>
        <span class="s">${totalClaims - activeClaims} superseded · ${heldBackN} held back</span></a>
      <button class="flow-step" data-action="scroll" data-target="state"><span class="k">${icon("shield", "sm")}Current state</span><span class="v">v${s.version}</span>
        <span class="s">${s.support.verified}/${s.support.total} verified · ${s.open_contradictions} contested</span></button>
      <button class="flow-step next" data-action="scroll" data-target="state"><span class="k"><span class="pulse"></span>Next action</span>
        <span class="v">${s.next_step ? s.next_step.value : "—"}</span><span class="s">${s.current_blocker ? "addresses the current blocker" : "no active blocker"}</span></button>
    </div>

    <div class="section" id="state">
      <div class="section-head"><h2>Current state</h2>
        <div class="right scrub"><label for="ver">Time travel</label>
          <input type="range" id="ver" min="1" max="${s.version}" value="${s.version}" aria-describedby="ver-label">
          <span class="mono" id="ver-label">v${s.version} · latest</span></div></div>
      <div class="banner info" id="hist-note" hidden><span class="ic">${icon("history")}</span><div class="body small" id="hist-note-text"></div></div>
      <div id="state-area">${stateArea(v, s, events, false, b.milestones || [])}</div>
    </div>

    ${openX.length ? html`<div class="section"><div class="section-head"><h2>Needs verification</h2><span class="right small muted">${openX.length} unresolved contradiction${openX.length > 1 ? "s" : ""}</span></div>
      ${openX.map((x) => contradictionCard(x, b))}</div>` : ""}

    <div class="section">
      <div class="section-head"><h2>Milestones</h2>
        <span class="right">${ctx.canEdit ? html`<button class="btn sm" data-add-milestone="${s.id}">${icon("plus", "sm")}Add milestone</button>` : ""}</span></div>
      <div class="panel">${(b.milestones || []).length ? (b.milestones || []).map((m) => milestoneRow(m))
        : html`<div class="empty sm"><h2>No milestones</h2><p class="small">Add deadlines you commit to, or commit to the proposed next step. TaskMaster never invents dates.</p></div>`}</div>
    </div>

    ${syn && !syn.snapshot ? html`<div class="section">
      <div class="section-head"><h2>Synthesis runs (Yosys)</h2><a class="right small" href="#/p/${s.id}/synthesis">Import, compare, explain</a></div>
      <a class="panel panel-pad row synth-card" href="#/p/${s.id}/synthesis" style="text-decoration:none;color:inherit;gap:14px">
        ${syn.runs.length ? html`<span>${icon("report", "sm")} <b>${syn.runs.length}</b> run${syn.runs.length > 1 ? "s" : ""}</span>
          <span>latest <span class="mono">${syn.runs[0].filename}</span>: <b>${syn.runs[0].metrics?.cells ?? "?"}</b> cells${syn.runs[0].derived?.flip_flops ? `, ${syn.runs[0].derived.flip_flops} flip-flops` : ""}</span>
          ${evChips([syn.runs[0].event_id], events, { short: true })}
          ${syn.analyses[0]?.analysis ? html`<span class="badge b-accent">${icon("zap")}Nemotron explained the last comparison</span>` : ""}`
        : html`<span class="muted">No synthesis runs yet. Import a Yosys <span class="mono">stat</span> report to track cell counts across experiments.</span>`}
      </a></div>` : ""}

    <div class="simple-only details-cta"><button class="btn" data-action="toggle-layout">${icon("layers", "sm")}Show all details: status, history, decisions, questions <span class="kbd">D</span></button></div>

    <div class="detailed-only">
    <div class="section" id="last-diff"><div class="loading-note"><span class="spinner"></span>Loading the latest state change…</div></div>

    <div class="section">
      <div class="section-head"><h2>What changed</h2><span class="right small muted">click an event to see its before/after</span></div>
      <div class="timeline">
        ${b.eventList.length > recent.length ? html`<div class="tl-item"><div class="when"></div><div class="rail"><span class="node">${icon("history")}</span></div>
          <a class="tl-body small" href="#/activity" style="display:block">${b.eventList.length - recent.length} earlier event${b.eventList.length - recent.length === 1 ? "" : "s"} · open full activity</a></div>` : ""}
        ${recent.map((e) => timelineItem(e, b.transitions[e.id], events, late, s.id))}
        <div class="tl-item terminal"><div class="when"><b>now</b></div><div class="rail"><span class="node state">${icon("target")}</span></div>
          <div class="tl-body"><div class="k">Current state</div>
            <div class="txt">${s.current_blocker ? html`Blocked: ${s.current_blocker.value}` : s.current_status ? s.current_status.value : "No blocker recorded."}</div>
            ${s.next_step ? html`<div class="small" style="margin-top:4px;color:var(--accent)">→ ${s.next_step.value}</div>` : ""}</div></div>
      </div>
    </div>

    <div class="section grid-2">
      <div>
        <div class="section-head"><h2>Decisions</h2><a class="right small" href="#/p/${s.id}/decisions">All decisions</a></div>
        <div class="panel">${decisions.length ? decisions.slice(-4).reverse().map((c) => html`<div class="item clickable ${c.status !== "active" ? "ended" : ""}" data-claim="${c.id}" tabindex="0" role="button">
          <div class="row small">${c.status === "active" ? html`<span class="badge b-ok">Active</span>` : html`<span class="badge b-muted">${c.status === "invalidated" ? "Reversed" : "Superseded"}</span>`}
            <span class="muted">${fmtDate(c.as_of)}</span></div><div class="t">${c.value}</div></div>`)
          : html`<div class="empty sm"><h2>No decisions recorded</h2><p class="small">Notes like “Decision: switch to X because Y” become decisions with their reasons.</p></div>`}</div>
      </div>
      <div>
        <div class="section-head"><h2>Open questions</h2><a class="right small" href="#/p/${s.id}/questions">All questions</a></div>
        <div class="panel">${qs.length ? qs.map((c) => html`<div class="item clickable" data-claim="${c.id}" tabindex="0" role="button">
          <div class="row small">${c.progress === "investigating" ? html`<span class="badge b-accent">Investigating</span>` : html`<span class="badge b-warm">Open</span>`}
            <span class="muted">${fmtDate(c.as_of)}</span></div><div class="t">${c.value}</div></div>`)
          : html`<div class="empty sm"><h2>No open questions</h2><p class="small">Unresolved questions from your updates show up here until evidence answers them.</p></div>`}</div>
      </div>
    </div>
    </div>`;
}

function bindPriority() {
  const sel = document.querySelector("[data-priority]");
  if (!sel) return;
  sel.onchange = async () => {
    try {
      await api.setPriority(sel.dataset.priority, sel.value);
      await loadWorkspace(true);
      toast(`Priority set to ${sel.value}`);
      ctx.rerender();
    } catch (err) { toast(err.message, "err"); }
  };
}

export { fieldLabel, confMeter };

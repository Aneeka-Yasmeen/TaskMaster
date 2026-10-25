// Reusable UI components: provenance, evidence drawer, "why" drawer, state diff, contradictions.
import { api } from "./api.js";
import { ctx, evidenceIndex, projectBundle } from "./ctx.js";
import {
  ago, evChip, evChips, fmtFull, html, icon, isArtifact, openDrawer, raw, srcIcon, srcLabel, vmark,
} from "./ui.js";

const FIELD = {
  goal: "Goal", last_action: "Last action", current_status: "Current status", current_blocker: "Current blocker",
  next_step: "Next step", open_questions: "Open question", decisions: "Decision", attempts: "Attempt", status_items: "Status",
};
export const fieldLabel = (c) => (c.field === "status_items" && c.key ? c.key.replace(/_/g, " ") : FIELD[c.field] || c.field);

export const provenance = (c, events, opts) => html`<span class="row" style="gap:6px">${vmark(c)}${evChips(c.evidence, events, opts)}</span>`;

const drawerHead = (title, sub) => html`
  <div class="drawer-head">
    <div style="min-width:0"><h2 id="drawer-title">${title}</h2>${sub ? html`<div class="small muted">${sub}</div>` : ""}</div>
    <button class="icon-btn x" data-action="close-drawer" aria-label="Close">${icon("x")}</button>
  </div>`;

export function evidenceCard(e, extra = "") {
  const art = isArtifact(e.source);
  return html`<button class="evcard" data-ev="${e.id}">
    <span class="h"><span class="${art ? "vmark verified" : "vmark reported"}">${srcIcon(e.source)}</span>
      <b class="mono" style="color:var(--accent)">${e.id}</b><span>${srcLabel(e.source)}</span>
      ${e.ref ? html`<span class="mono muted" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.ref}</span>` : ""}
      <span class="muted" style="margin-left:auto;white-space:nowrap">${fmtFull(e.occurred_at)}</span></span>
    <span class="t">${e.text}</span>
    <span class="small ${art ? "" : "muted"}" style="color:${art ? "var(--ok)" : ""}">${art ? "Artifact — can verify claims" : "Human report — supports “reported” only"}${extra}</span>
  </button>`;
}

// ---------------------------------------------------------------------------------------------
const scope = (projectId) => { document.getElementById("drawer").dataset.scopeProject = projectId; };

export async function openEvidence(projectId, eid) {
  scope(projectId);
  openDrawer(html`${drawerHead(eid, "Loading evidence…")}<div class="drawer-body"><div class="skel" style="height:160px"></div></div>`);
  try {
    const [idx, b] = await Promise.all([evidenceIndex(projectId), projectBundle(projectId)]);
    const e = idx[eid];
    if (!e) throw new Error(`Evidence ${eid} was not found.`);
    const art = isArtifact(e.source);
    const late = b.eventList.some((o) => o.seq < e.seq && o.occurred_at > e.occurred_at);
    openDrawer(html`
      ${drawerHead(html`<span class="mono" style="color:var(--accent)">${e.id}</span> · ${srcLabel(e.source)}`,
        html`${b.summary.name} · occurred ${fmtFull(e.occurred_at)} · recorded ${fmtFull(e.recorded_at)}`)}
      <div class="drawer-body">
        <div class="row">
          <span class="badge ${art ? "b-ok" : "b-warm"}">${srcIcon(e.source)}${art ? "Artifact" : "Human report"}</span>
          ${e.ref ? html`<span class="tag mono">${e.ref}</span>` : ""}
          ${e.event_type ? html`<span class="tag">${e.event_type}</span>` : ""}
          ${late ? html`<span class="badge b-violet" title="It happened before evidence that was already processed">${icon("history")}Late-arriving</span>` : ""}
          ${b.summary.sample ? html`<span class="badge b-muted" title="Part of a sample project: synthetic, written for the demo">Sample evidence</span>` : ""}
        </div>
        <pre class="evidence">${e.text}</pre>
        <p class="small muted" style="margin:0">${art
          ? "Machine-produced evidence. Claims citing it can be marked verified."
          : "A person's statement. Claims that rely only on it stay “reported” until an artifact backs them."}</p>
        <div>
          <div class="section-head"><h2>Supports ${e.supports.length} claim${e.supports.length === 1 ? "" : "s"}</h2></div>
          <div class="panel">${e.supports.length ? e.supports.map((c) => claimRow(c)) : html`<div class="item muted small">This evidence does not currently support any claim.</div>`}</div>
        </div>
        ${e.ended.length ? html`<div><div class="section-head"><h2>Made ${e.ended.length} belief${e.ended.length === 1 ? "" : "s"} obsolete</h2></div>
          <div class="panel">${e.ended.map((c) => claimRow(c))}</div></div>` : ""}
        ${e.contradictions.length ? html`<div><div class="section-head"><h2>Contradictions</h2></div>
          <div class="panel">${e.contradictions.map((x) => html`<div class="item"><div class="row"><span class="badge ${x.status === "open" ? "b-warm" : "b-ok"}">${x.id} · ${x.status === "open" ? "Needs verification" : "Resolved"}</span></div><div class="dim">${x.description}</div></div>`)}</div></div>` : ""}
        ${e.processed ? html`<button class="btn accent" data-diff="${e.id}">${icon("layers")}Show the state change this caused</button>`
          : e.error ? html`<div class="error-card"><b>${/^\[(awaiting review|rejected by user)\]/.test(e.error) ? "Evidence saved; state not changed." : "This update was saved but not applied."}</b><span class="small">${humanError(e.error)}</span></div>` : ""}
      </div>`);
  } catch (err) {
    openDrawer(html`${drawerHead(eid)}<div class="drawer-body"><div class="error-card">${err.message}</div></div>`);
  }
}

function claimRow(c) {
  const ended = c.status !== "active";
  return html`<div class="item clickable ${ended ? "ended" : ""}" data-claim="${c.id}" tabindex="0" role="button">
    <div class="row small"><span class="muted" style="text-transform:capitalize">${fieldLabel(c)}</span>${vmark(c)}
      ${ended ? html`<span class="badge b-muted">${c.status}</span>` : html`<span class="badge b-accent">current</span>`}
      <span class="mono muted" style="margin-left:auto">${c.id}</span></div>
    <div class="t" style="${ended ? "text-decoration:line-through;text-decoration-color:var(--line-2)" : ""}">${c.value}</div>
  </div>`;
}

// ---------------------------------------------------------------------------------------------
export async function openWhy(projectId, claimId) {
  scope(projectId);
  openDrawer(html`${drawerHead("Why TaskMaster believes this", "Loading…")}<div class="drawer-body"><div class="skel" style="height:200px"></div></div>`);
  try {
    const b = await projectBundle(projectId);
    const c = b.state.claims[claimId];
    if (!c) throw new Error("That claim no longer exists.");
    const chain = [];
    let prev = c.supersedes;
    while (prev && b.state.claims[prev]) { chain.push(b.state.claims[prev]); prev = b.state.claims[prev].supersedes; }
    const xs = Object.values(b.state.contradictions).filter((x) => x.claim_ids.includes(c.id));
    const ended = c.status !== "active";
    openDrawer(html`
      ${drawerHead("Why TaskMaster believes this", html`${b.summary.name} · <span class="mono">${c.id}</span>`)}
      <div class="drawer-body">
        <div class="panel panel-pad stack">
          <div class="row small"><span class="muted" style="text-transform:capitalize">${fieldLabel(c)}</span>
            ${ended ? html`<span class="badge b-muted">No longer current · ${c.status}</span>` : html`<span class="badge b-accent">Current belief</span>`}</div>
          <div style="font-size:16px;font-weight:550;line-height:1.45">${c.value}</div>
          <div class="row">${vmark(c)}<span class="small muted">confidence ${c.confidence} · as of ${fmtFull(c.as_of)}</span></div>
          ${c.reason ? html`<div class="small"><b>Reason:</b> <span class="dim">${c.reason}</span></div>` : ""}
          ${c.tradeoff ? html`<div class="small"><b>Tradeoff:</b> <span class="dim">${c.tradeoff}</span></div>` : ""}
          ${c.rationale ? html`<div class="small muted">Engine rationale: ${c.rationale}</div>` : ""}
        </div>
        <div><div class="section-head"><h2>Supported by</h2></div>
          <div class="stack">${c.evidence.map((eid) => b.events[eid] ? evidenceCard(b.events[eid]) : "")}</div>
          ${c.verification === "reported" ? html`<p class="small" style="color:var(--warm);margin:8px 0 0">No artifact supports this yet, so it stays “reported”. Attach a log or report to verify it.</p>` : ""}
        </div>
        ${ended ? html`<div class="banner info"><span class="ic">${icon("history")}</span><div class="body"><div class="title">Ended by ${c.ended_by}</div>
          <div class="small dim">${c.end_reason || ""}</div><div style="margin-top:6px">${evChip(c.ended_by, b.events)}</div></div></div>` : ""}
        ${chain.length ? html`<div><div class="section-head"><h2>Replaced earlier beliefs</h2></div><div class="panel">
          ${chain.map((p) => html`<div class="item ended"><div class="row small"><span class="mono muted">${p.id}</span><span class="badge b-muted">${p.status} by ${p.ended_by}</span>
            <span class="muted" style="margin-left:auto">${fmtFull(p.as_of)}</span></div><div class="t">${p.value}</div>${evChips(p.evidence, b.events)}</div>`)}</div></div>` : ""}
        ${xs.length ? html`<div><div class="section-head"><h2>Contradictions</h2></div>${xs.map((x) => contradictionCard(x, b, true))}</div>` : ""}
      </div>`);
  } catch (err) {
    openDrawer(html`${drawerHead("Why TaskMaster believes this")}<div class="drawer-body"><div class="error-card">${err.message}</div></div>`);
  }
}

// ---------------------------------------------------------------------------------------------
const CORE = [["current_blocker", "Blocker"], ["next_step", "Next step"], ["current_status", "Status"], ["last_action", "Last action"]];

export function diffView(d, events, opts = {}) {
  const changed = (k) => (d.before[k]?.id || null) !== (d.after[k]?.id || null);
  const keys = new Set([...Object.keys(d.before.status_items), ...Object.keys(d.after.status_items)]);
  const items = [...keys].filter((k) => d.before.status_items[k]?.id !== d.after.status_items[k]?.id);
  const rows = CORE.filter(([k]) => !opts.onlyChanged || changed(k));
  const col = (side) => html`<div class="col ${side}"><h3>${side === "before" ? "Before" : "After"}
      <span class="mono" style="font-weight:500">v${side === "before" ? d.transition.version_before : d.transition.version_after}</span></h3>
    ${rows.map(([k, label]) => { const c = d[side][k]; return html`<div class="f ${changed(k) ? "changed" : ""} ${side}"><span class="k">${label}</span>
      <span class="v">${c ? c.value : html`<span class="none">${k === "current_blocker" ? "No blocker" : "—"}</span>`}</span></div>`; })}
    ${items.map((k) => { const c = d[side].status_items[k]; return html`<div class="f changed ${side}"><span class="k mono">${k}</span>
      <span class="v">${c ? c.value : html`<span class="none">—</span>`}</span></div>`; })}
  </div>`;
  return html`<div class="diff">${col("before")}
    <div class="mid"><div class="k">What changed?</div>
      ${d.labels.length ? d.labels.map((l) => html`<span class="tag ${/cleared|resolved/i.test(l) ? "clr" : /contradiction/i.test(l) ? "x" : "upd"}">${l}</span>`) : html`<span class="tag">No change</span>`}
      <div class="arrow">${icon("arrow")}</div>
      <div style="text-align:center">${evChip(d.event.id, events)}</div>
    </div>${col("after")}</div>`;
}

export function heldBack(t) {
  const rej = (t.rejected || []).map((r) => humanReject(r));
  const warn = (t.warnings || []).filter((w) => w.type === "verification_downgraded" || w.type === "unknown_evidence_removed")
    .map((w) => w.type === "verification_downgraded" ? `Kept as “reported”: ${w.detail.replace(/cites no verifiable artifact/, "— no artifact supports it")}` : `Removed invented citation(s): ${w.ids.join(", ")}`);
  if (!rej.length && !warn.length) return "";
  return html`<div class="held"><b class="small" style="color:var(--text)">${icon("shield", "sm")} Held back by the validator</b>${[...rej, ...warn].map((x) => html`<div>• ${x}</div>`)}</div>`;
}

export function humanReject(r) {
  const op = r.op && typeof r.op === "object" ? r.op : {};
  const what = op.field ? `${op.op || "change"} to ${op.field.replace(/_/g, " ")}${op.key ? ` (${op.key})` : ""}` : "a proposed change";
  if (/stale evidence/.test(r.reason)) return `Ignored ${what}: this evidence is older than the claim it would replace.`;
  if (/no active claim/.test(r.reason)) return `Skipped ${what}: there was nothing current to change.`;
  if (/duplicate/.test(r.reason)) return `Skipped a duplicate contradiction.`;
  return `Skipped ${what}: ${r.reason}.`;
}

// Non-failure outcomes recorded as transitions: a proposal waiting for review, or one the user declined.
export function errorTag(e) {
  if (/^\[awaiting review\]/.test(e)) return html`<span class="tag upd" title="A proposed change is waiting for your review">proposed — awaiting review</span>`;
  if (/^\[rejected by user\]/.test(e)) return html`<span class="tag" title="You declined the proposed change; the evidence is kept">change declined — evidence kept</span>`;
  if (/^\[validator\]/.test(e)) return html`<span class="tag x" title="${e}">validator refused the update — evidence kept</span>`;
  return html`<span class="tag x">update failed — evidence kept</span>`;
}

export function humanError(e) {
  if (/^\[awaiting review\]/.test(e)) return "A proposed state change is waiting for your review on the Synthesis page.";
  if (/^\[rejected by user\]/.test(e)) return "You discarded the proposed state change. The evidence stays in the log.";
  if (/^\[validator\]/.test(e)) return "The validator could not apply the model's proposal, so nothing changed. " + e.replace(/^\[validator\]\s*/, "").slice(0, 160);
  if (/NEBIUS_API_KEY|401|403/.test(e)) return "The model connection was refused. Check the API key in .env.";
  if (/429/.test(e)) return "The model is rate-limited right now. Wait a moment and retry.";
  if (/cannot reach|timed out|URLError/i.test(e)) return "The model service could not be reached. Check your connection and retry.";
  if (/JSON/.test(e)) return "The model's answer could not be read as a state update. Retrying usually works.";
  return "The model call failed. The previous state is kept.";
}

export async function openDiff(projectId, eid) {
  scope(projectId);
  openDrawer(html`${drawerHead("State change", "Loading…")}<div class="drawer-body"><div class="skel" style="height:220px"></div></div>`);
  try {
    const [d, b] = await Promise.all([api.transition(projectId, eid), projectBundle(projectId)]);
    if (!d.transition) throw new Error("This evidence has not been processed yet.");
    const t = d.transition;
    openDrawer(html`
      ${drawerHead(html`State change from <span class="mono" style="color:var(--accent)">${eid}</span>`,
        html`${b.summary.name} · v${t.version_before} → v${t.version_after}${t.latency_ms ? ` · ${(t.latency_ms / 1000).toFixed(1)} s` : ""}${t.model ? ` · ${t.model}` : ""}`)}
      <div class="drawer-body">
        ${evidenceCard(d.event)}
        ${t.error ? html`<div class="error-card"><b>TaskMaster couldn't update the state from this evidence.</b><span class="small">${humanError(t.error)}</span></div>`
          : diffView(d, b.events)}
        ${t.error ? "" : heldBack(t)}
        ${t.error ? "" : html`<details><summary class="small muted" style="cursor:pointer">Raw operations (${t.applied.length} applied, ${t.rejected.length} rejected)</summary>
          <pre class="evidence" style="margin-top:8px">${JSON.stringify({ applied: t.applied, rejected: t.rejected, warnings: t.warnings }, null, 2)}</pre></details>`}
      </div>`);
  } catch (err) {
    openDrawer(html`${drawerHead("State change")}<div class="drawer-body"><div class="error-card">${err.message}</div></div>`);
  }
}

// ---------------------------------------------------------------------------------------------
export function contradictionCard(x, b, compact = false) {
  const claims = x.claim_ids.map((id) => b.state.claims[id]).filter(Boolean);
  const opener = b.events[x.opened_by];
  const open = x.status === "open";
  return html`<div class="contra" role="${open ? "alert" : ""}">
    <div class="head">${icon("alert")}${open ? "Contradictory evidence detected" : "Contradiction resolved"}<span class="mono small muted" style="margin-left:auto">${x.id}</span></div>
    <div class="cols">
      <div class="side"><span class="k">Claim on record</span>
        ${claims.slice(0, 1).map((c) => html`<div class="clamp">${c.value}</div><div class="row">${vmark({ ...c, contested: false })}${evChips(c.evidence, b.events)}</div>`)}
        ${claims.length > 1 ? html`<div class="small muted">+ ${claims.length - 1} related claim${claims.length > 2 ? "s" : ""} contested:
          ${claims.slice(1).map((c) => html`<button class="ev-chip" data-claim="${c.id}"><span class="lbl" style="font-family:var(--mono)">${c.field === "status_items" ? c.key : c.field.replace(/_/g, " ")}</span></button>`)}</div>` : ""}</div>
      <div class="vs">VS</div>
      <div class="side"><span class="k">Conflicting evidence</span>
        ${opener ? html`<div class="clamp">“${opener.text}”</div><div class="row"><span class="small muted">${srcLabel(opener.source)} · ${fmtFull(opener.occurred_at)}</span>${evChip(opener.id, b.events, { short: true })}</div>` : ""}
        <div class="small dim">${x.description}</div></div>
      <div class="status"><span class="k small muted" style="font-weight:600;letter-spacing:.08em;text-transform:uppercase;font-size:10.5px">Status</span>
        ${open ? html`<span class="badge b-warm">${icon("eye")}Needs verification</span>` : html`<span class="badge b-ok">${icon("check")}Resolved by ${x.resolved_by}</span>`}
        ${open ? html`<span class="small muted">TaskMaster won't pick a side until evidence settles it.</span>` : html`<span class="small dim">${x.resolution}</span>`}
        ${!compact && open ? html`<div class="row"><button class="btn sm" data-ev="${x.opened_by}">Review evidence</button>
          ${ctx.canWrite ? html`<button class="btn sm accent" data-compose="${b.summary.id}" data-prefill="Re ${x.id}: ">Add evidence</button>` : ""}</div>` : ""}
      </div>
    </div>
  </div>`;
}
export { raw, ago };

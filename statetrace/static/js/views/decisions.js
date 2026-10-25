// Decision history: what was decided, why, at what cost, and what was later reversed.
import { projectBundle } from "../ctx.js";
import { evChips, fmtDate, html, icon, vmark } from "../ui.js";

function decision(c, b) {
  const active = c.status === "active";
  const status = active ? html`<span class="badge b-ok">${icon("check")}Active</span>`
    : c.status === "invalidated" ? html`<span class="badge b-warm">${icon("x")}Reversed</span>` : html`<span class="badge b-muted">${icon("history")}Superseded</span>`;
  return html`<div class="item ${active ? "" : "ended"}">
    <div class="row">${status}<span class="small muted">${fmtDate(c.as_of)}</span>${vmark(c)}
      <button class="btn ghost sm" style="margin-left:auto" data-claim="${c.id}">Why?</button></div>
    <div class="t" style="font-size:15px">${c.value}</div>
    <dl class="kv">
      ${c.reason ? html`<dt>Reason</dt><dd>${c.reason}</dd>` : c.rationale && c.rationale.length > 12 ? html`<dt>Context</dt><dd>${c.rationale}</dd>` : ""}
      ${c.tradeoff ? html`<dt>Tradeoff</dt><dd>${c.tradeoff}</dd>` : ""}
      <dt>Evidence</dt><dd>${evChips(c.evidence, b.events)}</dd>
      ${!active ? html`<dt>${c.status === "invalidated" ? "Reversed" : "Replaced"}</dt><dd>${c.end_reason || ""} ${evChips([c.ended_by], b.events)}</dd>` : ""}
    </dl>
  </div>`;
}

function attempt(c, b) {
  const failed = /fail|abandon|drop|revert|no gain|unstable|worse|diverg/i.test(c.value + " " + (c.outcome || ""));
  return html`<div class="item">
    <div class="row small"><span class="muted">${fmtDate(c.as_of)}</span>${vmark(c)}
      ${failed ? html`<span class="badge b-muted">didn't work out</span>` : ""}
      <button class="btn ghost sm" style="margin-left:auto" data-claim="${c.id}">Why?</button></div>
    <div class="t">${c.value}</div>
    ${c.outcome ? html`<div class="small dim">Outcome: ${c.outcome}</div>` : ""}
    ${evChips(c.evidence, b.events)}
  </div>`;
}

export async function renderDecisions(r) {
  const b = await projectBundle(r.project);
  r.setCrumbs([{ label: "Projects", href: "#/projects" }, { label: b.summary.name, href: `#/p/${r.project}` }, { label: "Decisions" }]);
  const all = Object.values(b.state.claims);
  const decisions = all.filter((c) => c.field === "decisions").sort((a, c) => (a.as_of < c.as_of ? 1 : -1));
  const attempts = all.filter((c) => c.field === "attempts" && c.status !== "superseded").sort((a, c) => (a.as_of < c.as_of ? 1 : -1));
  const reversed = decisions.filter((c) => c.status !== "active").length;
  return html`
    <div class="page-head"><div><h1>Decisions</h1>
      <div class="sub">The project's history without rereading every event: ${decisions.length} decision${decisions.length === 1 ? "" : "s"}${reversed ? `, ${reversed} later reversed or superseded` : ""}, and ${attempts.length} approach${attempts.length === 1 ? "" : "es"} tried.</div></div>
      <div class="actions"><a class="btn" href="#/ask/${r.project}?q=${encodeURIComponent("Show me decisions that were later reversed")}">${icon("ask")}Which were reversed?</a></div></div>
    <div class="grid-2" style="align-items:start">
      <div><div class="section-head"><h2>Decision history</h2></div>
        <div class="panel">${decisions.length ? decisions.map((c) => decision(c, b))
          : html`<div class="empty sm"><h2>No decisions yet</h2><p class="small">Write “Decision: X, because Y; tradeoff Z” in an update.</p></div>`}</div></div>
      <div><div class="section-head"><h2>What was tried</h2></div>
        <div class="panel">${attempts.length ? attempts.map((c) => attempt(c, b))
          : html`<div class="empty sm"><h2>No attempts recorded</h2><p class="small">Updates like “Tried pipelining…” are tracked with their outcome.</p></div>`}</div></div>
    </div>`;
}

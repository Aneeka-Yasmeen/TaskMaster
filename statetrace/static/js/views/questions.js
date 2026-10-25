// Open questions: open → investigating → resolved (resolved only by evidence).
import { ctx, projectBundle } from "../ctx.js";
import { evChips, fmtDate, html, icon, vmark } from "../ui.js";

export async function renderQuestions(r) {
  const b = await projectBundle(r.project);
  r.setCrumbs([{ label: "Projects", href: "#/projects" }, { label: b.summary.name, href: `#/p/${r.project}` }, { label: "Questions" }]);
  const qs = Object.values(b.state.claims).filter((c) => c.field === "open_questions" && c.status !== "superseded");
  const open = qs.filter((c) => c.status === "active" && c.progress !== "investigating");
  const inv = qs.filter((c) => c.status === "active" && c.progress === "investigating");
  const done = qs.filter((c) => c.status === "invalidated");
  const col = (title, badge, items, emptyText) => html`<div>
    <div class="section-head"><h2>${title}</h2><span class="right mono small muted">${items.length}</span></div>
    <div class="panel">${items.length ? items.map((c) => html`<div class="item">
      <div class="row small">${badge}<span class="muted">${fmtDate(c.as_of)}</span>${vmark(c)}
        <button class="btn ghost sm" style="margin-left:auto" data-claim="${c.id}">Why?</button></div>
      <div class="t">${c.value}</div>
      ${c.status === "invalidated" ? html`<div class="small" style="color:var(--ok)">Answered by ${c.ended_by}: <span class="dim">${c.end_reason || ""}</span></div>` : ""}
      ${evChips(c.evidence, b.events)}
      ${c.status === "active" && ctx.canWrite ? html`<div><button class="btn sm ghost" data-compose="${r.project}" data-prefill="Answer to “${c.value.slice(0, 80)}”: ">${icon("plus", "sm")}Add evidence that answers this</button></div>` : ""}
    </div>`) : html`<div class="empty sm"><p class="small">${emptyText}</p></div>`}</div></div>`;
  return html`
    <div class="page-head"><div><h1>Open questions</h1>
      <div class="sub">Unresolved questions stay visible until evidence answers them. TaskMaster never closes a question on its own say-so.</div></div></div>
    <div class="grid-3" style="align-items:start">
      ${col("Open", html`<span class="badge b-warm">Open</span>`, open, "No open questions.")}
      ${col("Investigating", html`<span class="badge b-accent">Investigating</span>`, inv, "Nothing under investigation. Say “investigating X” in an update.")}
      ${col("Resolved", html`<span class="badge b-ok">${icon("check")}Resolved</span>`, done, "No questions answered yet.")}
    </div>`;
}

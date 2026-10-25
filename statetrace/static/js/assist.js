// Nemotron's review card: direction, progress, concerns and suggestions. Suggestions are advice:
// TaskMaster never applies them. "Use as update" / "Make milestone" go through the normal flows.
import { api } from "./api.js";
import { ctx, invalidate, loadWorkspace } from "./ctx.js";
import { ago, evChips, html, icon, mount, toast } from "./ui.js";

export const DIRECTION = {
  on_track: ["b-ok", "check", "On track"],
  at_risk: ["b-warm", "alert", "At risk"],
  off_track: ["b-danger", "x", "Off track"],
  blocked: ["b-danger", "block", "Blocked"],
  unclear: ["b-muted", "questions", "Unclear"],
};
export const directionBadge = (d) => { const [c, i, l] = DIRECTION[d] || DIRECTION.unclear; return html`<span class="badge ${c}">${icon(i)}${l}</span>`; };

export function reviewCard(project, data, events, opts = {}) {
  const r = data?.review;
  const rv = r?.review;
  const stale = r && data.current_version !== undefined && r.version !== data.current_version;
  const can = ctx.canWrite;
  const head = html`<div class="review-head"><span class="ai-mark" aria-hidden="true">${icon("zap")}</span>
      <h2 class="review-title">Nemotron's review</h2>
      ${can ? html`<button class="btn sm ${r ? "ghost" : "accent"}" data-review="${project}" data-force="${r ? "1" : ""}" title="Shortcut: R">
        ${icon("retry", "sm")}${r ? "Refresh" : "Review now"}</button>` : ""}</div>`;
  if (!rv) {
    return html`<section class="review" id="review-${project}" aria-label="Nemotron's review">${head}
      <p class="review-empty">${can ? "Ask Nemotron to compare the evidence with your goal and deadlines and suggest what to do next."
        : "Nemotron isn't connected, so there's no review yet."}${data?.last_error ? html`<br><span class="small" style="color:var(--warm)">Last attempt failed: ${data.last_error.slice(0, 140)}</span>` : ""}</p></section>`;
  }
  const items = (list, cls) => list.length ? html`<ul class="review-list ${cls}">${list.map((x) => html`<li>${x.text}${x.evidence?.length ? html` ${evChips(x.evidence, events, { short: true })}` : ""}</li>`)}</ul>` : "";
  return html`<section class="review" id="review-${project}" aria-label="Nemotron's review">${head}
    <div class="review-verdict">${directionBadge(rv.direction)}<span class="review-headline">${rv.headline}</span></div>
    ${opts.compact ? "" : html`<div class="review-cols">
      ${rv.progress.length ? html`<div><div class="review-k">Going well</div>${items(rv.progress, "good")}</div>` : ""}
      ${rv.concerns.length ? html`<div><div class="review-k">Concerns</div>${items(rv.concerns, "bad")}</div>` : ""}
    </div>`}
    ${rv.suggestions.length ? html`<div class="review-k">Suggestions</div>
      <div class="suggestions">${(opts.compact ? rv.suggestions.slice(0, 1) : rv.suggestions).map((sg) => html`<div class="suggestion">
        <div class="sg-title">${sg.title}</div>
        ${sg.why ? html`<div class="sg-why">${sg.why} ${sg.evidence?.length ? evChips(sg.evidence, events, { short: true }) : ""}</div>` : ""}
        ${ctx.canEdit && !opts.compact ? html`<div class="row" style="gap:6px">
          ${ctx.canWrite ? html`<button class="btn sm" data-compose="${project}" data-prefill="Decided to: ${sg.title}. ">${icon("plus", "sm")}Use as update</button>` : ""}
          <button class="btn sm ghost" data-add-milestone="${project}" data-ms-title="${sg.title}">${icon("clock", "sm")}Make milestone</button></div>` : ""}
      </div>`)}</div>` : ""}
    ${rv.questions.length && !opts.compact ? html`<div class="review-k">Questions to consider</div><ul class="review-list">${rv.questions.map((q) => html`<li>${q}</li>`)}</ul>` : ""}
    <div class="review-foot">${icon("shield", "sm")} Suggestions only: TaskMaster never acts on them. Reviewed ${ago(r.created_at)} for state v${r.version}
      ${stale ? html` · <b style="color:var(--warm)">the state has changed since</b>` : ""} · confidence ${rv.confidence}${r.latency_ms ? ` · ${(r.latency_ms / 1000).toFixed(1)} s` : ""}</div>
  </section>`;
}

export async function runReview(project, force) {
  const box = document.getElementById(`review-${project}`);
  if (box) mount(box, html`<div class="review-head"><span class="ai-mark" aria-hidden="true">${icon("zap")}</span><h2 class="review-title">Nemotron's review</h2></div>
    <div class="loading-note"><span class="spinner"></span>Nemotron is reading the evidence and comparing it with your goal and deadlines…</div>`);
  try {
    await api.review(project, force);
    invalidate(project);
    await loadWorkspace(true).catch(() => {});
    toast("Nemotron's review is ready");
  } catch (err) { toast(err.message, "err"); }
  ctx.rerender();
}

// "Where did I leave off, and what should I do next?" — the catch-up card.
// Nemotron chooses and orders claims; every displayed FACT is the stored text of a validated claim, with
// its support (verified / reported / contested) and evidence. Nemotron's own wording appears only as a
// labelled note and never carries a badge. Items no claim supports are labelled as its inference, and a
// next action that isn't recorded in the evidence is labelled as its suggestion.
import { api } from "./api.js";
import { ctx } from "./ctx.js";
import { ago, evChips, html, icon, mount, toast } from "./ui.js";

const BASIS = {
  verified: ["verified", "shield", "Verified", "Backed by a log, report or test"],
  reported: ["reported", "half", "Reported", "A person said so; no artifact confirms it yet"],
  inferred: ["inferred", "tilde", "Inferred", "Deduced by the state engine, not stated in evidence"],
  contested: ["contested", "alert", "Contested", "Conflicting evidence exists"],
  inference: ["inference", "tilde", "Nemotron's inference — not established", "No validated claim supports this; treat it as an opinion"],
  suggestion: ["inference", "zap", "Nemotron's suggestion — not in the evidence", "No recorded next step says this; Nemotron proposed it from the claims listed"],
};
const basisMark = (b) => { const [c, i, l, t] = BASIS[b] || BASIS.inference; return html`<span class="vmark ${c}" title="${t}">${icon(i, "sm")}${l}</span>`; };

const nemo = (label, text) => html`<div class="cu-note"><span class="cu-note-k">${icon("zap", "sm")}${label}</span> ${text}</div>`;

function item(x, events) {
  return html`<li class="cu-item ${x.basis === "suggestion" ? "inference" : x.basis}">
    <div class="cu-text">${x.text}</div>
    ${x.note ? nemo("Nemotron's wording (not verified):", x.note) : ""}
    ${x.why ? nemo("Why, per Nemotron:", x.why) : ""}
    ${x.based_on?.length ? html`<div class="small dim">Based on: ${x.based_on.map((b) => html`<button class="btn ghost sm" data-claim="${b.id}" title="${b.text}">${b.id} (${b.contested ? "contested" : b.verification})</button>`)}</div>` : ""}
    <div class="cu-meta">${basisMark(x.basis)}${x.evidence?.length ? evChips(x.evidence, events, { short: true }) : ""}
      ${x.as_of ? html`<span class="small muted">as of ${ago(x.as_of)}</span>` : ""}
      ${x.claims.map((c) => html`<button class="btn ghost sm" data-claim="${c}" title="Why does TaskMaster believe ${c}?">Why ${c}?</button>`)}</div>
  </li>`;
}

const section = (title, list, events, cls = "") => list?.length
  ? html`<div class="cu-sec ${cls}"><div class="review-k">${title}</div><ul class="cu-list">${list.map((x) => item(x, events))}</ul></div>` : "";

export function catchupCard(project, d, events) {
  const can = ctx.canWrite && d?.nemotron_available;
  const fromModel = d?.source === "nemotron";
  const head = html`<div class="review-head"><span class="ai-mark" aria-hidden="true">${icon("target")}</span>
    <h2 class="review-title">Where you left off &amp; what to do next</h2>
    ${can ? html`<button class="btn sm ${fromModel ? "ghost" : "accent"}" data-catchup="${project}" data-force="${fromModel ? "1" : ""}" title="Shortcut: C">
      ${icon("zap", "sm")}${fromModel ? "Ask Nemotron again" : "Reconstruct with Nemotron"}</button>` : ""}</div>`;
  if (!d) return html`<section class="review catchup" id="catchup-${project}">${head}<p class="review-empty">Couldn't load the catch-up.</p></section>`;
  const src = fromModel
    ? html`<span class="badge b-accent">${icon("zap")}Nemotron, checked against validated state v${d.version}</span>`
    : html`<span class="badge b-muted">${icon("layers")}Stored state only — no model involved</span>`;
  return html`<section class="review catchup" id="catchup-${project}" aria-label="Where you left off">${head}
    <div class="row" style="gap:6px">${src}${d.stale ? html`<span class="badge b-warm">${icon("clock")}Stale: last evidence ${ago(d.last_evidence)}</span>` : ""}</div>
    <p class="cu-headline">${d.headline}</p>
    ${d.headline_source === "nemotron" ? html`<div class="small muted">${icon("zap", "sm")} Nemotron's summary. The items below show what each part rests on.</div>` : ""}
    ${d.model_error ? html`<div class="banner warn small"><span class="ic">${icon("alert")}</span><div class="body">Nemotron's reply couldn't be used (${d.model_error.slice(0, 140)}). Showing the stored-state reconstruction instead.</div></div>` : ""}
    ${d.empty ? html`<p class="review-empty">There isn't enough validated evidence to reconstruct where you left off. Add an update or import a report.</p>` : ""}
    <div class="cu-next ${d.next_action ? "" : "none"}">
      <div class="review-k">${icon("arrow", "sm")} Next action</div>
      ${d.next_action ? html`<ul class="cu-list">${item(d.next_action, events)}</ul>`
        : html`<p class="cu-none">${icon("questions", "sm")} No defensible next action: ${d.no_next_action_reason}</p>`}
    </div>
    <div class="review-cols">
      ${section("Where you left off", d.left_off, events)}
      ${section("Established (verified)", d.established, events, "good")}
    </div>
    ${d.contradictions?.length ? html`<div class="cu-sec bad"><div class="review-k">Unresolved contradictions</div><ul class="cu-list">${d.contradictions.map((x) => html`<li class="cu-item contested">
      <div class="cu-text">${x.id}: ${x.description}</div><div class="cu-meta">${basisMark("contested")}${evChips(x.evidence, events, { short: true })}</div></li>`)}</ul></div>` : ""}
    <div class="review-cols">
      ${section("Blockers", d.blockers, events, "bad")}
      ${section("Uncertain — not verified", d.uncertain, events)}
    </div>
    ${d.missing_evidence?.length ? html`<div class="review-k">Evidence that would settle it${fromModel ? " (suggested by Nemotron)" : ""}</div><ul class="review-list">${d.missing_evidence.map((m) => html`<li>${m}</li>`)}</ul>` : ""}
    ${d.validator_notes?.length ? html`<details class="small"><summary>${icon("shield", "sm")} Validator adjusted ${d.validator_notes.length} thing${d.validator_notes.length > 1 ? "s" : ""} in Nemotron's reply</summary>
      <ul>${d.validator_notes.map((n) => html`<li>${n}</li>`)}</ul></details>` : ""}
    <div class="review-foot">${icon("shield", "sm")} Facts, support labels and evidence come from validated claims, not from the model.
      ${d.mode}${d.cached ? ` · saved ${ago(d.created_at)}` : ""}${d.latency_ms ? ` · ${(d.latency_ms / 1000).toFixed(1)} s` : ""}
      ${!d.nemotron_available ? " · Nemotron not connected (set NEBIUS_API_KEY to enable)" : ""}</div>
  </section>`;
}

// Long Nemotron calls: show elapsed time, explain slowness, and stay safe if the user navigates away.
export async function runCatchUp(project, force) {
  const box = document.getElementById(`catchup-${project}`);
  const t0 = Date.now();
  let timer;
  if (box) {
    mount(box, html`<div class="review-head"><span class="ai-mark" aria-hidden="true">${icon("target")}</span><h2 class="review-title">Where you left off &amp; what to do next</h2></div>
      <div class="loading-note" role="status"><span class="spinner"></span>Nemotron is reconstructing the project from its validated state… <b class="mono" id="cu-elapsed-${project}">0 s</b>
      <span class="small muted" id="cu-slow-${project}"></span></div>`);
    timer = setInterval(() => {
      const s = Math.round((Date.now() - t0) / 1000);
      const el = document.getElementById(`cu-elapsed-${project}`);
      if (!el) return clearInterval(timer);  // user navigated away; the request finishes and is cached server-side
      el.textContent = `${s} s`;
      if (s >= 25) document.getElementById(`cu-slow-${project}`).textContent = " · large models can take up to a minute; you can leave this page, the result is saved.";
    }, 1000);
  }
  try {
    const d = await api.runCatchUp(project, force);
    toast(d.source === "nemotron" ? "Catch-up ready" : "Nemotron unavailable — showing the stored-state catch-up", d.source === "nemotron" ? "" : "err");
  } catch (err) { toast(err.message, "err"); }
  clearInterval(timer);
  if (ctx.project === project) ctx.rerender();
}

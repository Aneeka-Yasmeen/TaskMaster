// Milestones: user commitments with due dates. Kept apart from evidence-derived claims.
import { api } from "./api.js";
import { ctx, invalidate, loadWorkspace } from "./ctx.js";
import { ago, closeSheet, fmtFull, html, icon, openSheet, toast } from "./ui.js";

const STATE = {
  overdue: ["b-danger", "alert", "Overdue"], due_soon: ["b-warm", "clock", "Due soon"], upcoming: ["b-accent", "clock", "Upcoming"],
  no_date: ["b-muted", "clock", "No date"], done: ["b-ok", "check", "Done"], dropped: ["b-muted", "x", "Dropped"],
  unconfirmed: ["b-violet", "eye", "Needs confirmation"],
};
export const msBadge = (m) => { const [c, i, l] = STATE[m.state] || STATE.upcoming; return html`<span class="badge ${c}">${icon(i)}${l}</span>`; };

export function milestoneRow(m, opts = {}) {
  const open = m.status === "open";
  return html`<div class="item ms ${open ? "" : "ended"}">
    <div class="row small">${msBadge(m)}
      ${m.due_at ? html`<span class="${m.state === "overdue" ? "" : "muted"}" title="${fmtFull(m.due_at)}">${m.state === "overdue" ? "was due" : "due"} ${fmtFull(m.due_at)}</span>` : ""}
      ${opts.project ? html`<a href="#/p/${m.project}" class="muted">${m.project_name}</a>` : ""}
      <span class="tag" title="${m.origin === "user" ? "You entered this" : "Suggested from evidence; not a deadline until you confirm it"}">${m.origin === "user" ? "set by you" : "inferred"}</span>
      ${m.source_claim ? html`<span class="tag upd" title="Created from the proposed next step ${m.source_claim}">from next step</span>` : ""}
      ${ctx.canEdit && !opts.compact ? html`<span class="ms-actions">
        ${open ? html`<button class="btn ghost sm" data-ms-action="done" data-ms-id="${m.id}">${icon("check", "sm")}Done</button>
          <button class="btn ghost sm" data-ms-action="date" data-ms-id="${m.id}">Change date</button>
          <button class="btn ghost sm" data-ms-action="drop" data-ms-id="${m.id}">Drop</button>`
          : html`<button class="btn ghost sm" data-ms-action="reopen" data-ms-id="${m.id}">Reopen</button>`}
        <button class="btn ghost sm" data-ms-action="delete" data-ms-id="${m.id}" aria-label="Delete milestone">${icon("x", "sm")}</button></span>` : ""}
    </div>
    <div class="t">${m.title}</div>
    ${m.reasons?.length && open ? html`<ul class="reasons">${m.reasons.map((r) => html`<li>${r}</li>`)}</ul>` : ""}
    ${!m.confirmed && ctx.canEdit ? html`<div><button class="btn sm accent" data-ms-action="confirm" data-ms-id="${m.id}">Confirm this date</button></div>` : ""}
  </div>`;
}

export function openMilestoneSheet({ project, title = "", source_claim = null } = {}) {
  if (!ctx.canEdit) { toast("This instance is read-only.", "err"); return; }
  openSheet(html`
    <div class="sheet-head"><span class="logo" aria-hidden="true" style="width:20px;height:20px"></span>
      <h2 id="sheet-title">${source_claim ? "Commit to this next step" : "Add milestone"}</h2>
      <button class="icon-btn x" data-action="close-sheet" aria-label="Close">${icon("x")}</button></div>
    <form class="sheet-body" id="ms-form" autocomplete="off">
      <label class="field">What will be done<input type="text" id="ms-title" value="${title}" required maxlength="200" autofocus></label>
      <div class="row" style="gap:10px">
        <label class="field" style="flex:1;min-width:200px">Due (optional)<input type="datetime-local" id="ms-due" step="60"></label>
        <label class="field" style="flex:1;min-width:200px">Remind me
          <select id="ms-remind"><option value="default">Default (Settings)</option><option value="10080,1440">1 week and 1 day before</option>
            <option value="1440,120">1 day and 2 hours before</option><option value="120">2 hours before</option><option value="">No reminders</option></select></label>
      </div>
      <p class="small muted" style="margin:0">${source_claim
        ? "The next step was proposed from evidence. Committing records that you decided to do it; it doesn't change the evidence."
        : "Milestones are your commitments. TaskMaster never invents deadlines; reminders respect your quiet hours."}</p>
    </form>
    <div class="sheet-foot"><div class="right"><button class="btn ghost" data-action="close-sheet">Cancel</button>
      <button class="btn primary" id="ms-save">${icon("check")}${source_claim ? "Commit" : "Add milestone"}</button></div></div>`);
  const save = async () => {
    const t = document.getElementById("ms-title").value.trim();
    if (!t) { document.getElementById("ms-title").focus(); return; }
    const r = document.getElementById("ms-remind").value;
    // [] = use the defaults from Settings, [-1] = no reminders at all
    const reminders = r === "default" ? [] : r === "" ? [-1] : r.split(",").map(Number);
    const body = { project, title: t, due_at: document.getElementById("ms-due").value || null, source_claim, reminders };
    try {
      await api.addMilestone(body);
      invalidate(project); await loadWorkspace(true).catch(() => {});
      closeSheet(); toast(source_claim ? "Committed to the next step" : "Milestone added"); ctx.rerender();
    } catch (err) { toast(err.message, "err"); }
  };
  document.getElementById("ms-save").onclick = save;
  document.getElementById("ms-form").onsubmit = (e) => { e.preventDefault(); save(); };
}

export async function milestoneAction(action, id, project) {
  try {
    if (action === "delete") {
      if (!confirm("Delete this milestone? This removes it and its reminders.")) return;
      await api.deleteMilestone(+id);
    } else if (action === "date") {
      const v = prompt("New due date and time (YYYY-MM-DD HH:MM), or empty to clear:");
      if (v === null) return;
      await api.updateMilestone({ id: +id, due_at: v.trim() ? v.trim().replace(" ", "T") : null });
    } else if (action === "confirm") {
      await api.updateMilestone({ id: +id, confirmed: true });
    } else {
      await api.updateMilestone({ id: +id, status: { done: "done", drop: "dropped", reopen: "open" }[action] });
    }
    if (project) invalidate(project);
    await loadWorkspace(true).catch(() => {});
    ctx.rerender();
  } catch (err) { toast(err.message, "err"); }
}

const rel = (iso) => {
  const s = (new Date(iso) - new Date()) / 1000;
  if (s < 0) return `due ${ago(iso)}`;
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))} min`;
  if (s < 172800) return `in ${Math.round(s / 3600)} h`;
  return `in ${Math.round(s / 86400)} days`;
};

export const upcomingLine = (m) => html`<a class="upcoming ${m.at_risk ? "risk" : ""}" href="#/p/${m.project}">
  ${msBadge(m)}<span class="t">${m.title}</span><span class="muted small">${m.project_name}</span>
  <span class="small ${m.state === "overdue" ? "" : "muted"} due" title="${m.due_at ? fmtFull(m.due_at) : ""}">${m.due_at ? rel(m.due_at) : "no date"}</span>
  ${m.at_risk && m.reasons.length ? html`<span class="small reason">${icon("alert", "sm")} ${m.reasons.join(" · ")}</span>` : ""}</a>`;

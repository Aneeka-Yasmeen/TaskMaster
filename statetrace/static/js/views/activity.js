// Workspace activity: every piece of evidence across projects, and what it changed.
import { api } from "../api.js";
import { errorTag } from "../components.js";
import { loadWorkspace } from "../ctx.js";
import { fmtDate, fmtTime, html, icon, isArtifact, srcIcon, srcLabel } from "../ui.js";

export async function renderActivity({ setCrumbs }) {
  setCrumbs([{ label: "Activity" }]);
  const [{ activity }, ws] = await Promise.all([api.activity(), loadWorkspace()]);
  if (!activity.length) return html`<div class="empty"><div class="glyph"></div><h2>No activity yet</h2><p>Every update you record appears here with the state change it caused.</p></div>`;
  const byDay = new Map();
  for (const a of [...activity].sort((x, y) => (x.occurred_at < y.occurred_at ? 1 : -1))) {
    const d = a.occurred_at.slice(0, 10);
    if (!byDay.has(d)) byDay.set(d, []);
    byDay.get(d).push(a);
  }
  const OPS = { ADD: ["plus", "added"], UPDATE: ["retry", "updated"], INVALIDATE: ["x", "cleared"], CONTRADICT: ["alert", "contradiction"], RESOLVE: ["check", "resolved"], REINFORCE: ["plus", "reinforced"] };
  return html`
    <div class="page-head"><div><h1>Activity</h1>
      <div class="sub">All evidence across ${ws.projects.length} projects, by when it happened. Click an item to see the state change it caused.</div></div></div>
    ${[...byDay.entries()].map(([day, items]) => html`
      <div class="section" style="margin-top:18px">
        <div class="section-head"><h2>${fmtDate(day + "T12:00:00")}</h2><span class="right mono small muted">${items.length}</span></div>
        <div class="panel">${items.map((a) => html`
          <div class="item clickable" data-diff="${a.id}" data-project="${a.project}" tabindex="0" role="button" style="grid-template-columns:52px 22px minmax(0,1fr);display:grid;gap:10px;align-items:start">
            <span class="mono small muted" style="padding-top:2px">${fmtTime(a.occurred_at)}</span>
            <span style="color:${isArtifact(a.source) ? "var(--ok)" : "var(--warm)"};padding-top:2px">${srcIcon(a.source)}</span>
            <span style="min-width:0;display:grid;gap:4px">
              <span class="row small" style="gap:8px"><a href="#/p/${a.project}" style="font-weight:600;color:var(--text)">${a.project_name}</a>
                <span class="mono" style="color:var(--accent)">${a.id}</span><span class="muted">${srcLabel(a.source)}</span>${a.ref ? html`<span class="mono muted">${a.ref}</span>` : ""}</span>
              <span style="overflow-wrap:anywhere">${a.text.length > 220 ? a.text.slice(0, 220) + "…" : a.text}</span>
              <span class="chips">${a.error ? errorTag(a.error)
                : a.changes ? a.ops.map((o) => html`<span class="tag ${o === "CONTRADICT" ? "x" : o === "INVALIDATE" || o === "RESOLVE" ? "clr" : "upd"}">${icon(OPS[o]?.[0] || "retry", "sm")} ${OPS[o]?.[1] || o.toLowerCase()}</span>`)
                : html`<span class="tag">no change</span>`}
                ${a.rejected ? html`<span class="tag rej">${a.rejected} held back</span>` : ""}
                <span class="small muted">${a.changes} change${a.changes === 1 ? "" : "s"}</span></span>
            </span>
          </div>`)}</div>
      </div>`)}`;
}

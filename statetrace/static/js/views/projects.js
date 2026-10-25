import { loadWorkspace } from "../ctx.js";
import { ago, confMeter, healthBadge, html, icon, sampleBadge, spark } from "../ui.js";
import { bindIntro, emptyWorkspace } from "./overview.js";

export async function renderProjects(r) {
  r.setCrumbs([{ label: "Projects" }]);
  const ws = await loadWorkspace(true);
  if (!ws.projects.length) { r.after = bindIntro; return emptyWorkspace(); }
  return html`
    <div class="page-head"><div><h1>Projects</h1><div class="sub">${ws.projects.length} projects, sorted by most recent evidence.</div></div>
      <div class="actions"><button class="btn primary" data-compose="">${icon("plus")}Add update</button></div></div>
    <div class="panel table-wrap">
      <table class="table stackable">
        <thead><tr><th>Project</th><th>Health</th><th>Current blocker</th><th>Next step</th><th>Evidence</th><th>Confidence</th><th>Updated</th></tr></thead>
        <tbody>${ws.projects.map((p) => html`<tr onclick="location.hash='#/p/${p.id}'">
          <td><a href="#/p/${p.id}" style="color:var(--text);font-weight:600">${p.name}</a> ${sampleBadge(p)}<div class="small muted" style="max-width:260px">${p.goal ? p.goal.value.slice(0, 90) : ""}</div></td>
          <td>${healthBadge(p.health)}</td>
          <td style="max-width:260px;${p.current_blocker ? "color:var(--danger)" : ""}">${p.current_blocker ? p.current_blocker.value : html`<span class="muted">None</span>`}</td>
          <td style="max-width:260px">${p.next_step ? p.next_step.value : html`<span class="muted">—</span>`}</td>
          <td class="nowrap"><span class="mono">${p.events}</span> ${spark(p.activity)}</td>
          <td>${confMeter(p.confidence, p.support)}</td>
          <td class="nowrap muted">${ago(p.last_updated)}</td></tr>`)}</tbody>
      </table>
    </div>`;
}

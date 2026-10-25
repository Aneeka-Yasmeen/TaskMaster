// Evidence library: every piece of evidence, what it supports, what it made obsolete.
import { fieldLabel } from "../components.js";
import { evidenceIndex, projectBundle } from "../ctx.js";
import { fmtFull, html, icon, isArtifact, mount, srcIcon, srcLabel, vmark } from "../ui.js";
import { lateSet, opLabels } from "./project.js";

function detail(e, b, late) {
  if (!e) return html`<div class="empty sm"><h2>Select evidence</h2><p class="small">Pick an item to see exactly which beliefs it supports.</p></div>`;
  const art = isArtifact(e.source);
  const claim = (c) => html`<div class="item clickable ${c.status !== "active" ? "ended" : ""}" data-claim="${c.id}" tabindex="0" role="button">
    <div class="row small"><span class="muted" style="text-transform:capitalize">${fieldLabel(c)}</span>${vmark(c)}
      ${c.status === "active" ? html`<span class="badge b-accent">current</span>` : html`<span class="badge b-muted">${c.status}</span>`}
      <span class="mono muted" style="margin-left:auto">${c.id}</span></div><div class="t">${c.value}</div></div>`;
  return html`<div class="panel panel-pad stack">
      <div class="row"><span class="mono" style="font-size:15px;font-weight:600;color:var(--accent)">${e.id}</span>
        <span class="badge ${art ? "b-ok" : "b-warm"}">${srcIcon(e.source)}${srcLabel(e.source)}</span>
        ${e.ref ? html`<span class="tag mono">${e.ref}</span>` : ""}
        ${late.has(e.id) ? html`<span class="badge b-violet">${icon("history")}Late-arriving</span>` : ""}</div>
      <dl class="kvlist" style="grid-template-columns:110px minmax(0,1fr)">
        <dt>Occurred</dt><dd>${fmtFull(e.occurred_at)}</dd>
        <dt>Recorded</dt><dd>${fmtFull(e.recorded_at)}</dd>
        <dt>Evidence type</dt><dd>${art ? "Artifact: can verify claims" : "Human report: supports “reported” claims only"}</dd>
      </dl>
      <pre class="evidence">${e.text}</pre>
      <div class="chips">${opLabels(b.transitions[e.id])}</div>
      <div><button class="btn sm accent" data-diff="${e.id}">${icon("layers", "sm")}Before / after</button></div>
    </div>
    <div class="section-head" style="margin-top:16px"><h2>Supports ${e.supports.length} claim${e.supports.length === 1 ? "" : "s"}</h2></div>
    <div class="panel">${e.supports.length ? e.supports.map(claim) : html`<div class="item small muted">Not cited by any claim.</div>`}</div>
    ${e.ended.length ? html`<div class="section-head" style="margin-top:16px"><h2>Made obsolete</h2></div><div class="panel">${e.ended.map(claim)}</div>` : ""}`;
}

export async function renderEvidence(r) {
  const [b, idx] = await Promise.all([projectBundle(r.project), evidenceIndex(r.project)]);
  r.setCrumbs([{ label: "Projects", href: "#/projects" }, { label: b.summary.name, href: `#/p/${r.project}` }, { label: "Evidence" }]);
  const list = Object.values(idx).reverse();
  const late = lateSet(b.eventList);
  let filter = "all", q = "", selected = r.arg || list[0]?.id;
  const rows = () => list.filter((e) => (filter === "all" || (filter === "artifact") === isArtifact(e.source))
    && (!q || `${e.id} ${e.text} ${e.ref || ""} ${e.source}`.toLowerCase().includes(q)));
  const renderList = () => {
    const rs = rows();
    mount(document.getElementById("evlist"), rs.length ? rs.map((e) => html`
      <button class="evrow" role="option" aria-selected="${e.id === selected}" data-pick="${e.id}">
        <span class="src ${isArtifact(e.source) ? "artifact" : "report"}">${srcIcon(e.source)}</span>
        <span style="min-width:0"><span class="row small" style="gap:6px"><b class="mono" style="color:var(--accent)">${e.id}</b>
          <span class="muted">${srcLabel(e.source)}</span><span class="muted" style="margin-left:auto">${fmtFull(e.occurred_at)}</span></span>
          <span class="t">${e.text}</span>
          <span class="small muted">${e.supports.length} claim${e.supports.length === 1 ? "" : "s"}${e.ended.length ? ` · ended ${e.ended.length}` : ""}${e.contradictions.length ? " · contradiction" : ""}</span></span>
      </button>`) : html`<div class="empty sm"><h2>No matching evidence</h2></div>`);
  };
  r.after = () => {
    renderList();
    mount(document.getElementById("evdetail"), detail(idx[selected], b, late));
    document.getElementById("evlist").onclick = (ev) => {
      const t = ev.target.closest("[data-pick]");
      if (!t) return;
      selected = t.dataset.pick;
      history.replaceState(null, "", `#/p/${r.project}/evidence/${selected}`);
      renderList();
      mount(document.getElementById("evdetail"), detail(idx[selected], b, late));
      if (window.innerWidth < 900) document.getElementById("evdetail").scrollIntoView({ behavior: "smooth" });
    };
    document.getElementById("evq").oninput = (ev) => { q = ev.target.value.toLowerCase(); renderList(); };
    document.querySelectorAll("[data-filter]").forEach((btn) => btn.onclick = () => {
      filter = btn.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((x) => x.setAttribute("aria-pressed", String(x === btn)));
      renderList();
    });
  };
  const nArt = list.filter((e) => isArtifact(e.source)).length;
  return html`
    <div class="page-head"><div><h1>Evidence</h1>
      <div class="sub">Everything TaskMaster knows about ${b.summary.name} comes from these ${list.length} items. The log is append-only: nothing here is ever edited or deleted.</div></div></div>
    <div class="split">
      <div class="panel">
        <div class="panel-pad stack" style="border-bottom:1px solid var(--line)">
          <input type="search" id="evq" placeholder="Search evidence, refs, ids…" aria-label="Search evidence">
          <div class="seg" role="group" aria-label="Filter by evidence type">
            <button data-filter="all" aria-pressed="true">All ${list.length}</button>
            <button data-filter="artifact" aria-pressed="false">Artifacts ${nArt}</button>
            <button data-filter="report" aria-pressed="false">Reports ${list.length - nArt}</button>
          </div>
        </div>
        <div class="evlist" id="evlist" role="listbox" aria-label="Evidence"></div>
      </div>
      <div id="evdetail"></div>
    </div>`;
}

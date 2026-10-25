// Inbox: evidence sources (local Git) and staged imports awaiting review.
// Nothing here changes the project state until the user accepts it.
import { api } from "../api.js";
import { humanError } from "../components.js";
import { ctx, invalidate, loadWorkspace, projectBundle } from "../ctx.js";
import { ago, fmtFull, html, icon, mount, toast } from "../ui.js";

function sourceCard(s) {
  const c = s.config;
  return html`<div class="item">
    <div class="row small">
      <span class="badge ${s.enabled ? "b-ok" : "b-muted"}">${icon(s.enabled ? "zap" : "clock")}${s.enabled ? "Active" : "Paused"}</span>
      <span class="badge b-muted">${icon("commit")}Git${c.wsl ? " · WSL" : ""}</span>
      ${s.auto_accept ? html`<span class="badge b-warm" title="New commits go straight into the state engine">auto-accept</span>` : ""}
      <span class="muted" style="margin-left:auto">${s.last_scan_at ? `scanned ${ago(s.last_scan_at)}` : "never scanned"}</span>
    </div>
    <div class="mono" style="overflow-wrap:anywhere">${c.path} <span class="muted">@ ${c.branch}</span></div>
    ${s.last_error ? html`<div class="small" style="color:var(--warm)">${icon("alert", "sm")} Last scan failed: ${s.last_error}</div>` : ""}
    ${ctx.canEdit ? html`<div class="row">
      <button class="btn sm accent" data-src="scan" data-id="${s.id}" ${s.enabled ? "" : "disabled"}>${icon("retry", "sm")}Scan now</button>
      <button class="btn sm ghost" data-src="${s.enabled ? "pause" : "resume"}" data-id="${s.id}">${s.enabled ? "Pause" : "Resume"}</button>
      <button class="btn sm ghost" data-src="auto" data-id="${s.id}" data-on="${s.auto_accept ? "0" : "1"}">${s.auto_accept ? "Turn off auto-accept" : "Auto-accept…"}</button>
      <button class="btn sm ghost" data-src="remove" data-id="${s.id}">Remove</button></div>` : ""}
  </div>`;
}

function itemRow(i, selectable) {
  const p = i.payload;
  return html`<label class="item import-item ${i.status}">
    <span class="row small" style="gap:8px">
      ${selectable ? html`<input type="checkbox" data-item="${i.id}" aria-label="Select ${i.title}">` : ""}
      <span class="badge b-muted">${icon("commit")}<span class="mono">${p.ref}</span></span>
      <span class="muted">${fmtFull(i.occurred_at)}</span><span class="muted">${p.meta?.branch || ""}</span>
      ${i.event_id ? html`<button class="ev-chip" data-ev="${i.event_id}"><span class="id">${i.event_id}</span></button>` : ""}
      <span class="muted" style="margin-left:auto">${p.meta?.author || ""}</span></span>
    <span class="t">${i.title}</span>
    ${p.meta?.stat ? html`<span class="small muted mono">${p.meta.stat}</span>` : ""}
    ${i.error ? html`<span class="small" style="color:var(--warm)">${icon("alert", "sm")} Evidence saved, state update failed: ${humanError(i.error)}</span>` : ""}
  </label>`;
}

export async function renderInbox(r) {
  const [b, data] = await Promise.all([projectBundle(r.project), api.sources(r.project)]);
  r.setCrumbs([{ label: "Projects", href: "#/projects" }, { label: b.summary.name, href: `#/p/${r.project}` }, { label: "Inbox" }]);
  const by = (s) => data.items.filter((i) => i.status === s);
  const pending = by("pending"), failed = by("failed"), accepted = by("accepted").slice(-8).reverse(), skipped = by("skipped");

  r.after = () => {
    const main = document.getElementById("main");
    const refresh = async () => { invalidate(r.project); await loadWorkspace(true).catch(() => {}); ctx.rerender(); };
    const selected = () => [...main.querySelectorAll("[data-item]:checked")].map((x) => +x.dataset.item);
    main.querySelectorAll("[data-src]").forEach((btn) => btn.onclick = async () => {
      const id = +btn.dataset.id, a = btn.dataset.src;
      try {
        if (a === "scan") {
          btn.disabled = true;
          const res = await api.scan(r.project, id);
          const s = res.scans[0] || {};
          toast(s.error ? `Scan failed: ${s.error}` : `${s.new} new commit${s.new === 1 ? "" : "s"} staged for review`, s.error ? "err" : "ok");
        } else if (a === "pause" || a === "resume") await api.updateSource({ id, enabled: a === "resume" });
        else if (a === "auto") {
          if (btn.dataset.on === "1" && !confirm("Auto-accept sends every new commit message to the model and updates the project state without review. Turn it on?")) return;
          await api.updateSource({ id, auto_accept: btn.dataset.on === "1" });
        } else if (a === "remove") {
          if (!confirm("Remove this source? Pending and skipped items are discarded. Accepted evidence stays in the log.")) return;
          await api.removeSource(id);
        }
        refresh();
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    });
    const form = document.getElementById("src-form");
    if (form) form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        await api.addSource({ project: r.project, path: form.path.value.trim(), branch: form.branch.value.trim() || null, wsl: form.wsl.checked });
        toast("Source added. Scan it to stage commits for review.");
        refresh();
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
    const act = async (kind) => {
      const ids = kind === "retry" ? failed.map((i) => i.id) : selected();
      if (!ids.length) { toast("Select at least one commit.", "err"); return; }
      const status = document.getElementById("inbox-status");
      try {
        if (kind === "skip") { await api.skipImports(r.project, ids); toast(`${ids.length} skipped`); return refresh(); }
        mount(status, html`<div class="loading-note"><span class="spinner"></span>Running ${ids.length} commit${ids.length > 1 ? "s" : ""} through the state engine, oldest first (about 8 s each)…</div>`);
        const res = kind === "accept" ? await api.acceptImports(r.project, ids) : await api.retryImports(r.project, ids);
        const bad = res.results.filter((x) => x.error).length;
        toast(bad ? `${res.results.length - bad} applied, ${bad} saved but not applied (retry later)` : `${res.results.length} applied to the project state`, bad ? "err" : "ok");
        refresh();
      } catch (err) { mount(status, ""); toast(err.message, "err"); }
    };
    main.querySelectorAll("[data-bulk]").forEach((btn) => btn.onclick = () => act(btn.dataset.bulk));
    const all = document.getElementById("sel-all");
    if (all) all.onchange = () => main.querySelectorAll("[data-item]").forEach((x) => { x.checked = all.checked; });
  };

  if (data.snapshot) {
    return html`<div class="page-head"><div><h1>Inbox</h1><div class="sub">Evidence sources are local to your machine and are not part of this read-only snapshot.</div></div></div>`;
  }
  return html`
    <div class="page-head"><div><h1>Inbox</h1>
      <div class="sub">New evidence from connected sources waits here. Nothing changes ${b.summary.name}'s state until you accept it.</div></div></div>
    <div class="split" style="grid-template-columns:minmax(280px,400px) minmax(0,1fr)">
      <div class="stack">
        <div class="section-head" style="margin:0"><h2>Sources</h2></div>
        <div class="panel">${data.sources.length ? data.sources.map(sourceCard)
          : html`<div class="empty sm"><h2>No sources yet</h2><p class="small">Connect a local Git repository to turn commits into evidence.</p></div>`}</div>
        ${ctx.canEdit ? html`<form class="panel panel-pad stack" id="src-form" autocomplete="off">
          <b class="small">${icon("commit", "sm")} Connect a local Git repository</b>
          <label class="field">Repository folder<input type="text" name="path" required placeholder="C:\\code\\fireground  or  /home/me/fireground (WSL)"></label>
          <label class="field">Branch (optional)<input type="text" name="branch" placeholder="current branch"></label>
          <label class="row small" style="gap:6px"><input type="checkbox" name="wsl"> Repository lives inside WSL2 (use WSL's git)</label>
          <p class="small muted" style="margin:0">Reads commit hash, date, author, branch, message and line counts only. No diffs or file contents. The first scan takes at most the 30 most recent commits.</p>
          <div><button class="btn accent" type="submit">${icon("plus", "sm")}Add source</button></div>
        </form>` : ""}
        <p class="small muted" style="margin:0">${icon("shield", "sm")} A commit can verify that a change was recorded, never that tests pass or hardware works.</p>
      </div>
      <div class="stack">
        <div class="section-head" style="margin:0"><h2>Waiting for review</h2><span class="right mono small muted">${pending.length}</span></div>
        <div id="inbox-status"></div>
        <div class="panel">${pending.length ? html`
          <div class="toolbar small">${ctx.canEdit ? html`<label class="row" style="gap:6px"><input type="checkbox" id="sel-all"> Select all</label>` : ""}
            ${ctx.canWrite ? html`<button class="btn sm primary" data-bulk="accept" style="margin-left:auto">${icon("check", "sm")}Accept selected</button>`
              : html`<span class="small muted" style="margin-left:auto">Accepting needs the model connection</span>`}
            ${ctx.canEdit ? html`<button class="btn sm" data-bulk="skip">Skip selected</button>` : ""}</div>
          ${pending.map((i) => itemRow(i, ctx.canEdit))}`
          : html`<div class="empty sm"><h2>Nothing waiting</h2><p class="small">${data.sources.length ? "Scan a source to check for new commits." : "Add a source on the left."}</p></div>`}</div>
        ${failed.length ? html`<div class="section-head" style="margin:8px 0 0"><h2>Saved but not applied</h2>
            ${ctx.canWrite ? html`<button class="btn sm right" data-bulk="retry">${icon("retry", "sm")}Retry all</button>` : ""}</div>
          <div class="panel">${failed.map((i) => itemRow(i, false))}</div>` : ""}
        ${accepted.length ? html`<div class="section-head" style="margin:8px 0 0"><h2>Recently accepted</h2></div><div class="panel">${accepted.map((i) => itemRow(i, false))}</div>` : ""}
        ${skipped.length ? html`<details><summary class="small muted">${skipped.length} skipped</summary><div class="panel" style="margin-top:8px">${skipped.map((i) => itemRow(i, false))}</div></details>` : ""}
      </div>
    </div>`;
}

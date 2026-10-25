// Settings: assistant & autonomy, companion & quit, display, reminders, sources, trust rules.
import { api } from "../api.js";
import { ctx, loadWorkspace } from "../ctx.js";
import { prefs as display, setLayout, setTextSize } from "../prefs.js";
import { ago, html, icon, mount, srcLabel, toast } from "../ui.js";

export async function renderSettings(r) {
  r.setCrumbs([{ label: "Settings" }]);
  const m = ctx.meta;
  const theme = (() => { try { return localStorage.getItem("tm.theme") || "system"; } catch { return "system"; } })();
  const live = api.mode === "live";
  const ws = await loadWorkspace().catch(() => ({ projects: [] }));
  const [rprefs, comp, asst, sync, srcLists] = live ? await Promise.all([
    api.notificationPrefs().catch(() => null),
    api.companionSettings().catch(() => null),
    api.assistantSettings().catch(() => null),
    api.sync().catch(() => null),
    Promise.all(ws.projects.map((p) => api.sources(p.id).then((x) => x.sources.map((s) => ({ ...s, project_name: p.name }))).catch(() => []))),
  ]) : [null, null, null, null, []];
  const sources = srcLists.flat();
  const editable = ctx.canEdit;
  const access = asst?.assistant?.access || "off";
  const chosen = new Set(asst?.assistant?.projects || []);

  r.after = () => {
    const q = (sel) => document.querySelectorAll(sel);
    q("[data-theme-set]").forEach((b) => b.onclick = () => {
      const t = b.dataset.themeSet;
      try { t === "system" ? localStorage.removeItem("tm.theme") : localStorage.setItem("tm.theme", t); } catch {}
      if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
      q("[data-theme-set]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
    q("[data-text-size]").forEach((b) => b.onclick = () => { setTextSize(b.dataset.textSize); ctx.rerender(); });
    q("[data-layout-set]").forEach((b) => b.onclick = () => { setLayout(b.dataset.layoutSet); location.reload(); });
    // autonomy
    const saveAccess = async () => {
      const level = document.querySelector("input[name=access]:checked")?.value || "off";
      const projects = [...q("input[name=access-project]:checked")].map((x) => x.value);
      try {
        await api.setAssistantSettings({ access: level, projects });
        toast(level === "off" ? "Autonomy off: Nemotron works only when you ask" : `Autonomy: ${level === "all" ? "all projects" : projects.length + " selected project(s)"}`);
        ctx.rerender();
      } catch (err) { toast(err.message, "err"); }
    };
    q("input[name=access], input[name=access-project]").forEach((el) => el.onchange = saveAccess);
    const sn = document.getElementById("sync-now");
    if (sn) sn.onclick = async () => {
      sn.disabled = true;
      try { const s = await api.syncNow(); toast(s.queued_total ? "Nemotron still unreachable; updates stay queued." : "All waiting updates applied."); ctx.rerender(); }
      catch (err) { toast(err.message, "err"); sn.disabled = false; }
    };
    // companion
    const setComp = async (body, msg) => {
      try { await api.setCompanionSettings(body); if (msg) toast(msg); ctx.rerender(); }
      catch (err) { toast(err.message, "err"); }
    };
    q("[data-comp]").forEach((el) => {
      const k = el.dataset.comp;
      if (k === "hotkey") el.onchange = () => setComp({ hotkey: el.value.trim() }, "Hotkey saved. Restart the companion to use it.");
      else if (el.type === "checkbox") el.onchange = () => setComp({ [k]: el.checked }, null);
      else if (el.tagName === "BUTTON") el.onclick = () => setComp({ paused: el.dataset.value === "1" },
        el.dataset.value === "1" ? "All background activity paused" : "Background activity resumed");
      else el.onchange = () => setComp({ interval_minutes: +el.value }, "Scan interval saved");
    });
    const tn = document.getElementById("test-notif");
    if (tn) tn.onclick = async () => {
      try { await api.testNotification(); toast("Test queued: the companion shows it within 30 seconds if it's running."); }
      catch (err) { toast(err.message, "err"); }
    };
    const quit = document.getElementById("quit");
    if (quit) quit.onclick = async () => {
      if (!confirm("Quit TaskMaster? The server (and the companion, if it's hosting it) will stop. Your data is saved.")) return;
      try {
        await api.shutdown();
        mount(document.getElementById("main"), html`<div class="empty"><div class="glyph"></div><h2>TaskMaster has stopped</h2>
          <p>Everything is saved. You can close this tab. To start again, double-click <span class="mono">scripts\\TaskMaster-Companion.cmd</span>
          or run <span class="mono">python -m statetrace --db demo.db companion</span>.</p></div>`);
      } catch (err) { toast(err.message, "err"); }
    };
    // reminders
    const form = document.getElementById("notif-form");
    if (form) form.onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api.setNotificationPrefs({
          enabled: form.enabled.checked, stale_alerts: form.stale.checked,
          quiet_start: form.qs.value, quiet_end: form.qe.value,
          default_reminders: form.rem.value.split(",").map((x) => x.trim()).filter(Boolean).map(Number),
        });
        toast("Reminder settings saved");
      } catch (err) { toast(err.message, "err"); }
    };
    q("[data-src-toggle]").forEach((b) => b.onclick = async () => {
      try { await api.updateSource({ id: +b.dataset.srcToggle, enabled: b.dataset.on === "1" }); ctx.rerender(); }
      catch (err) { toast(err.message, "err"); }
    });
  };

  const dis = editable ? "" : "disabled";
  const cp = comp?.prefs, st = comp?.status;
  return html`
    <div class="page-head"><div><h1>Settings</h1><div class="sub">What Nemotron may do on its own, how TaskMaster reaches you, and how it looks.</div></div></div>
    <div class="settings-col">

      <section class="set-card">
        <h2 class="set-title">${icon("zap")} Assistant (Nemotron)</h2>
        <div class="row" style="gap:8px">
          ${m.assistant ? html`<span class="badge b-accent">${icon("zap")}${m.model}</span>` : html`<span class="badge b-warm">${icon("alert")}Not connected: ${m.model_error || "no model"}</span>`}
          <span class="muted small">via Nebius Token Factory · key read from <span class="mono">.env</span> by the local server only</span>
        </div>
        ${sync?.queued_total ? html`<div class="banner info" style="margin:10px 0 0"><span class="ic">${icon("clock")}</span><div class="body">
          <div class="title">${sync.queued_total} update${sync.queued_total > 1 ? "s" : ""} waiting for Nemotron</div>
          <div class="small dim">Saved while Nebius was unreachable. They're applied automatically (checked every minute) or now.</div></div>
          <div class="actions">${editable ? html`<button class="btn sm" id="sync-now">Sync now</button>` : ""}</div></div>` : ""}
        <h3 class="set-sub">Autonomy: what Nemotron may do without being asked</h3>
        <div class="radio-list" role="radiogroup" aria-label="Autonomy">
          <label class="radio"><input type="radio" name="access" value="off" ${access === "off" ? "checked" : ""} ${dis}>
            <span><b>Off</b>: Nemotron works only when you ask (Add update, Ask, Review). Nothing runs in the background.</span></label>
          <label class="radio"><input type="radio" name="access" value="selected" ${access === "selected" ? "checked" : ""} ${dis}>
            <span><b>Selected projects</b>: for the projects you tick, Nemotron reviews progress after every new update, and the companion watches their Git sources.</span></label>
          ${access === "selected" ? html`<div class="project-picks">${ws.projects.map((p) => html`<label class="check small"><input type="checkbox" name="access-project" value="${p.id}" ${chosen.has(p.id) ? "checked" : ""} ${dis}><span>${p.name}</span></label>`)}</div>` : ""}
          <label class="radio"><input type="radio" name="access" value="all" ${access === "all" ? "checked" : ""} ${dis}>
            <span><b>All projects</b>: the same, for every project.</span></label>
        </div>
        <p class="small muted" style="margin:6px 0 0">${icon("shield", "sm")} At every level Nemotron only <b>thinks and suggests</b>. It never changes a project, accepts commits or creates deadlines on its own. You decide with <i>Use as update</i> / <i>Make milestone</i>.</p>
      </section>

      <section class="set-card">
        <h2 class="set-title">${icon("overview")} Desktop companion & quitting</h2>
        ${comp ? html`
          <div class="row small" style="gap:8px">
            <span class="badge ${st.alive ? "b-ok" : "b-muted"}">${icon(st.alive ? "check" : "clock")}${st.alive ? "Companion running" : "Companion not running"}</span>
            ${st.alive ? html`<span class="badge ${st.hotkey === "registered" ? "b-ok" : "b-warm"}" title="${st.hotkey_error || ""}">${st.hotkey === "registered" ? `${st.hotkey_label || "Hotkey"} active` : st.hotkey === "disabled" ? "Hotkey disabled" : "Hotkey not registered"}</span>` : ""}
            <span class="badge ${cp.monitoring && !cp.paused && st.alive ? "b-accent" : "b-muted"}">${icon("eye")}Background ${cp.monitoring ? (cp.paused ? "paused" : st.alive ? "active" : "on (companion not running)") : "off (Autonomy off)"}</span>
          </div>
          ${st.last_error ? html`<div class="small" style="color:var(--warm)">Last problem: ${st.last_error}</div>` : ""}
          <label class="check"><input type="checkbox" data-comp="notifications" ${cp.notifications ? "checked" : ""} ${dis}>
            <span><b>Windows notifications</b>: deadlines, stale projects, commits waiting for review. Once per issue; quiet hours apply. Needs Autonomy on.</span></label>
          <label class="check"><input type="checkbox" data-comp="hotkey_enabled" ${cp.hotkey_enabled ? "checked" : ""} ${dis}>
            <span><b>Global hotkey</b> <input type="text" data-comp="hotkey" value="${cp.hotkey}" size="14" aria-label="Hotkey" ${dis}> opens the compact window from any app (applies at next start).</span></label>
          <label class="check"><span></span><span>Check Git sources every
            <select data-comp="interval" aria-label="Scan interval" ${dis}>${[5, 15, 30, 60, 240].map((n) => html`<option value="${n}" ${cp.interval_minutes === n ? "selected" : ""}>${n < 60 ? n + " min" : n / 60 + " h"}</option>`)}</select>
            (only for projects Autonomy allows; commits are staged, never accepted)</span></label>
          ${editable ? html`<div class="row">
            <button class="btn ${cp.paused ? "accent" : ""}" data-comp="paused" data-value="${cp.paused ? "0" : "1"}">${cp.paused ? "Resume background activity" : "Pause all background activity"}</button>
            <button class="btn ghost" id="test-notif" ${cp.notifications && cp.monitoring && !cp.paused ? "" : "disabled"}>Send test notification</button>
            <button class="btn danger" id="quit" style="margin-left:auto">${icon("x")}Quit TaskMaster</button></div>` : ""}
          <p class="small muted" style="margin:0">Closing the compact window does not quit TaskMaster. To quit: <span class="kbd">Ctrl</span> + <span class="kbd">Q</span>, the button above, <span class="mono">python -m statetrace stop</span>, Ctrl+C in the console that started it, or close that console window.</p>`
        : html`<p class="small muted">Not available in this read-only view.</p>`}
      </section>

      <section class="set-card">
        <h2 class="set-title">${icon("eye")} Display</h2>
        <div class="row" style="gap:16px">
          <span class="small muted">Text size</span>
          <div class="seg" role="group" aria-label="Text size">${[["normal", "Normal"], ["large", "Large"]].map(([v, l]) => html`<button data-text-size="${v}" aria-pressed="${display.textSize === v}">${l}</button>`)}</div>
          <span class="small muted">Layout</span>
          <div class="seg" role="group" aria-label="Layout">${[["simple", "Simple"], ["detailed", "Detailed"]].map(([v, l]) => html`<button data-layout-set="${v}" aria-pressed="${display.layout === v}">${l}</button>`)}</div>
          <span class="small muted">Theme</span>
          <div class="seg" role="group" aria-label="Theme">${["system", "dark", "light"].map((t) => html`<button data-theme-set="${t}" aria-pressed="${theme === t}">${t[0].toUpperCase() + t.slice(1)}</button>`)}</div>
        </div>
        <p class="small muted" style="margin:8px 0 0">Simple shows what matters; Detailed adds history, status tables, decisions, questions and health charts. Press <span class="kbd">D</span> to switch, <span class="kbd">?</span> for all shortcuts.</p>
      </section>

      <section class="set-card">
        <h2 class="set-title">${icon("clock")} Reminders</h2>
        ${rprefs ? html`<form class="stack" id="notif-form">
          <label class="check"><input type="checkbox" name="enabled" ${rprefs.enabled ? "checked" : ""} ${dis}><span>Show reminders for milestones I set</span></label>
          <label class="check"><input type="checkbox" name="stale" ${rprefs.stale_alerts ? "checked" : ""} ${dis}><span>Tell me when a project goes stale (7+ days without evidence)</span></label>
          <div class="row" style="gap:10px">
            <label class="field">Quiet from<input type="text" name="qs" value="${rprefs.quiet_start}" pattern="[0-2][0-9]:[0-5][0-9]" size="6" ${dis}></label>
            <label class="field">until<input type="text" name="qe" value="${rprefs.quiet_end}" pattern="[0-2][0-9]:[0-5][0-9]" size="6" ${dis}></label>
            <label class="field" style="flex:1;min-width:180px">Default reminders (minutes before due)<input type="text" name="rem" value="${rprefs.default_reminders.join(", ")}" ${dis}></label>
          </div>
          <p class="small muted" style="margin:0">Each reminder appears once: in the bell (top right) while TaskMaster is open, and as a Windows notification if enabled above. Quiet hours hold pop-ups back.</p>
          ${editable ? html`<div><button class="btn accent" type="submit">Save reminder settings</button></div>` : ""}
        </form>` : html`<p class="small muted">Not available in this read-only view.</p>`}
      </section>

      <section class="set-card">
        <h2 class="set-title">${icon("commit")} Evidence sources</h2>
        ${sources.length ? html`<div class="panel">${sources.map((s) => html`<div class="item">
          <div class="row small"><span class="badge ${s.enabled ? "b-ok" : "b-muted"}">${s.enabled ? "Active" : "Paused"}</span>
            <a href="#/p/${s.project}/inbox">${s.project_name}</a><span class="muted">${s.last_scan_at ? `scanned ${ago(s.last_scan_at)}` : "never scanned"}</span>
            ${editable ? html`<button class="btn ghost sm" style="margin-left:auto" data-src-toggle="${s.id}" data-on="${s.enabled ? "0" : "1"}">${s.enabled ? "Pause" : "Resume"}</button>` : ""}</div>
          <div class="mono small" style="overflow-wrap:anywhere">${s.config.path} @ ${s.config.branch}${s.config.wsl ? " (WSL)" : ""}</div></div>`)}</div>`
          : html`<p class="small muted">No sources yet. Connect a Git repository (Windows or WSL) from a project's Inbox.</p>`}
        <p class="small muted" style="margin:8px 0 0">${icon("eye", "sm")} TaskMaster reads only commit metadata and messages from repositories you add. It never watches keystrokes or your terminal, captures the screen, reads diffs or uploads code.</p>
      </section>

      <details class="set-card">
        <summary class="set-title" style="cursor:pointer">${icon("shield")} Trust rules (enforced in code)</summary>
        <div class="panel" style="margin-top:10px">
          ${[
            ["Verified needs an artifact", `Only ${m.verifiable_sources.map(srcLabel).join(", ").toLowerCase()} can make a claim verified. Notes and chats stay “reported”.`],
            ["A commit only proves a change", "A claim that something passes, fails, meets timing or works needs a test, simulation or report artifact."],
            ["Every claim cites real evidence", "Citations to evidence that doesn't exist are removed and counted."],
            ["Old evidence can't overwrite or contest new beliefs", "Late-arriving evidence is kept but can't replace or contradict newer claims."],
            ["Contradictions are surfaced", "They stay open until evidence settles them."],
            ["Nothing is deleted", "Beliefs are superseded or invalidated with the evidence that ended them."],
            ["Nemotron advises; the validator decides", "Nemotron proposes state changes and writes reviews, but only validated operations change the state, and reviews never do."],
            ["Priority", ctx.workspace?.priority_rules || ""],
            ["Confidence", m.rules.confidence],
          ].map(([t, d]) => html`<div class="item"><div style="font-weight:600">${t}</div><div class="small dim">${d}</div></div>`)}
        </div>
      </details>
    </div>`;
}

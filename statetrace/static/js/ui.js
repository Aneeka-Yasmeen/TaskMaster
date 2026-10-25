// Small rendering toolkit: auto-escaping templates, icons, formatting, toasts, overlays.

export class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const part = (v) => (v == null || v === false ? "" : v instanceof Raw ? v.s : Array.isArray(v) ? v.map(part).join("") : esc(v));
export function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => { out += part(v) + strings[i + 1]; });
  return new Raw(out);
}
export const mount = (el, view) => { el.innerHTML = part(view); };

// icons (lucide-style strokes) ------------------------------------------------------------
const P = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  projects: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  evidence: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
  decisions: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="10" r="2.5"/><path d="M6 8.5v7M8.3 7.2l7.4 2"/>',
  questions: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.6 2.6 0 0 1 5 .9c0 1.8-2.5 2.3-2.5 3.9"/><path d="M12 17.2h.01"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  ask: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M9 10h6M9 13.5h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  alert: '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  block: '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  commit: '<circle cx="12" cy="12" r="3.5"/><path d="M3 12h5.5M15.5 12H21"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12.5 15H17"/>',
  report: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  flask: '<path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7 15h10"/>',
  note: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
  issue: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.5"/>',
  ci: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.8"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-4.5"/>',
  half: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18" /><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/>',
  tilde: '<path d="M4 14c2-3 4-3 6-1.5S14 15 16 12s3-2.5 4-1"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  chev: '<path d="M8 10l4 4 4-4"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 8v4l3 2"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  retry: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  zap: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
};
export const icon = (name, cls = "") => raw(`<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || P.issue}</svg>`);

// evidence sources -------------------------------------------------------------------------
const SRC_ICON = {
  git_commit: "commit", sim_log: "terminal", test_output: "terminal", ci: "ci", synthesis_report: "report",
  implementation_report: "report", timing_report: "report", experiment_log: "flask", report: "report",
  note: "note", chat: "chat", meeting: "users", email: "mail", issue: "issue",
};
const SRC_LABEL = {
  git_commit: "Git commit", sim_log: "Simulation log", test_output: "Test output", ci: "CI run",
  synthesis_report: "Synthesis report", implementation_report: "Implementation report", timing_report: "Timing report",
  experiment_log: "Experiment log", report: "Report", note: "User update", chat: "Chat message", meeting: "Meeting note",
  email: "Email", issue: "Issue",
};
let VERIFIABLE = new Set();
export const setVerifiable = (list) => { VERIFIABLE = new Set(list); };
export const isArtifact = (src) => VERIFIABLE.has(src);
export const srcIcon = (src) => icon(SRC_ICON[src] || "evidence", "sm");
export const srcLabel = (src) => SRC_LABEL[src] || src;

// time ---------------------------------------------------------------------------------------
let NOW = null; // fixed "now" for read-only snapshots
export const setNow = (iso) => { NOW = iso ? new Date(iso) : null; };
const now = () => NOW || new Date();
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function ago(iso) {
  if (!iso) return "never";
  const d = new Date(iso), s = (now() - d) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const days = Math.floor(s / 86400);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return fmtDate(iso);
}
export const daysSince = (iso) => (iso ? Math.floor((now() - new Date(iso)) / 86400000) : null);
export const fmtDate = (iso) => { const d = new Date(iso); return `${MON[d.getMonth()]} ${d.getDate()}${d.getFullYear() !== now().getFullYear() ? ", " + d.getFullYear() : ""}`; };
export const fmtTime = (iso) => { const d = new Date(iso); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
export const fmtFull = (iso) => `${fmtDate(iso)}, ${fmtTime(iso)}`;

// shared pieces -------------------------------------------------------------------------
export const HEALTH = {
  needs_review: { label: "Needs review", cls: "b-warm", icon: "alert" },
  blocked: { label: "Blocked", cls: "b-danger", icon: "block" },
  stale: { label: "Stale", cls: "b-muted", icon: "clock" },
  active: { label: "Active", cls: "b-ok", icon: "zap" },
  empty: { label: "No evidence", cls: "b-muted", icon: "evidence" },
};
export const sampleBadge = (p) => p?.sample
  ? html`<span class="badge b-violet sample-badge" title="Synthetic demo data, not a real project. Use it to see how TaskMaster works.">${icon("layers")}Sample data</span>` : "";
export const healthBadge = (h) => { const x = HEALTH[h] || HEALTH.active; return html`<span class="badge ${x.cls}">${icon(x.icon)}${x.label}</span>`; };

export function vmark(c) {
  if (!c) return "";
  if (c.contested) return html`<span class="vmark contested" title="Conflicting evidence exists">${icon("alert", "sm")}Contested</span>`;
  if (c.verification === "verified") return html`<span class="vmark verified" title="Supported by a machine artifact (report, log, commit)">${icon("shield", "sm")}Verified</span>`;
  if (c.verification === "inferred") return html`<span class="vmark inferred" title="Deduced, not stated in evidence">${icon("tilde", "sm")}Inferred</span>`;
  return html`<span class="vmark reported" title="Stated by a person; no artifact backs it yet">${icon("half", "sm")}Reported</span>`;
}

export function confMeter(level, support) {
  const tip = support ? `${support.verified} of ${support.total} current-state claims verified by artifacts` : "";
  return html`<span class="conf ${level}" title="${tip}"><span class="bars"><i></i><i></i><i></i></span><span>${level || "—"}</span></span>`;
}

export function spark(counts) {
  const max = Math.max(1, ...counts);
  return html`<span class="spark" aria-label="${counts.reduce((a, b) => a + b, 0)} updates in the last 14 days">${counts.map((n) =>
    raw(`<i class="${n ? "on" : ""}" style="height:${n ? 4 + Math.round((n / max) * 12) : 2}px"></i>`))}</span>`;
}

// evidence chip: id + source icon + short label; opens the evidence drawer
export function evChip(eid, events, opts = {}) {
  const e = events && events[eid];
  const kind = e ? (isArtifact(e.source) ? "artifact" : "report") : "";
  const label = e ? (e.ref || srcLabel(e.source)) : "";
  return html`<button class="ev-chip ${kind}" data-ev="${eid}" title="${e ? srcLabel(e.source) + " · " + fmtFull(e.occurred_at) : eid}">
    ${e ? html`<span class="src">${srcIcon(e.source)}</span>` : ""}<span class="id">${eid}</span>${opts.short || !label ? "" : html`<span class="lbl">${label}</span>`}</button>`;
}
export const evChips = (ids, events, opts) => html`<span class="chips">${(ids || []).map((e) => evChip(e, events, opts))}</span>`;

// toasts / overlays --------------------------------------------------------------------
export function toast(msg, kind = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = part(html`${icon(kind === "ok" ? "check" : "alert")}<span>${msg}</span>`);
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

let lastFocus = null;
function openLayer(wrapId, contentId, view) {
  lastFocus = document.activeElement;
  const wrap = document.getElementById(wrapId);
  mount(document.getElementById(contentId), view);
  wrap.hidden = false;
  document.body.style.overflow = "hidden";
  const f = wrap.querySelector("[autofocus], textarea, input, button.x, button");
  setTimeout(() => f && f.focus(), 30);
  return document.getElementById(contentId);
}
function closeLayer(wrapId) {
  const wrap = document.getElementById(wrapId);
  if (wrap.hidden) return;
  wrap.hidden = true;
  if (document.getElementById("sheet-wrap").hidden && document.getElementById("drawer-wrap").hidden) document.body.style.overflow = "";
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
export const openSheet = (view) => openLayer("sheet-wrap", "sheet", view);
export const closeSheet = () => closeLayer("sheet-wrap");
export const openDrawer = (view) => openLayer("drawer-wrap", "drawer", view);
export const closeDrawer = () => closeLayer("drawer-wrap");
export const sheetOpen = () => !document.getElementById("sheet-wrap").hidden;
export const drawerOpen = () => !document.getElementById("drawer-wrap").hidden;

// trap Tab inside an open overlay
document.addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const wrap = sheetOpen() ? document.getElementById("sheet") : drawerOpen() ? document.getElementById("drawer") : null;
  if (!wrap) return;
  const f = [...wrap.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter((x) => !x.disabled && x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
  else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
});

// render "[E3, E4]" citations inside rendered answers as clickable chips
export function withCitations(text, events) {
  const out = [];
  let last = 0;
  const re = /\[((?:E\d+)(?:,\s*E\d+)*)\]/g;
  let m;
  while ((m = re.exec(text))) {
    out.push(esc(text.slice(last, m.index)));
    out.push(part(evChips(m[1].split(/,\s*/), events, { short: true })));
    last = m.index + m[0].length;
  }
  out.push(esc(text.slice(last)));
  return raw(out.join(""));
}

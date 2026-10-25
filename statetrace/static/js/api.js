// Service layer. LiveService talks to the Python server; SnapshotService reads a static export
// (read-only demo hosting). Views only ever call `api.*`, so neither mode leaks into the UI code.

const UNREACHABLE = "Can't reach the TaskMaster server. Is `python -m statetrace serve` still running?";

async function parse(r) {
  let j;
  try { j = await r.json(); } catch { throw new Error(r.ok ? "The server sent an unexpected response." : `Request failed (${r.status}).`); }
  if (!r.ok) throw Object.assign(new Error(j.error || `Request failed (${r.status}).`), { status: r.status, diagnostics: j.diagnostics });
  return j;
}

class LiveService {
  mode = "live";
  async get(path, params = {}) {
    let r;
    try { r = await fetch(`/api/${path}?${new URLSearchParams(params)}`); } catch { throw new Error(UNREACHABLE); }
    return parse(r);
  }
  async post(path, body) {
    let r;
    try { r = await fetch(`/api/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
    catch { throw new Error(UNREACHABLE); }
    return parse(r);
  }
  meta() { return this.get("meta"); }
  workspace() { return this.get("workspace"); }
  project(id) { return this.get("project", { project: id }); }
  state(id, version) { return this.get("state", { project: id, version }); }
  events(id) { return this.get("events", { project: id }); }
  evidence(id) { return this.get("evidence", { project: id }); }
  transition(id, event) { return this.get("transition", { project: id, event }); }
  why(id, q) { return this.get("why", { project: id, q }); }
  activity() { return this.get("activity"); }
  ask(id, question) { return this.post("ask", { project: id, question }); }
  createProject(name) { return this.post("projects", { name }); }
  loadSample() { return this.post("sample", {}); }
  addEvent(body) { return this.post("events", body); }
  retry(id) { return this.post("retry", { project: id }); }
  // evidence sources (staged imports)
  sources(id) { return this.get("sources", { project: id }); }
  addSource(body) { return this.post("sources/add", body); }
  updateSource(body) { return this.post("sources/update", body); }
  removeSource(id) { return this.post("sources/remove", { id }); }
  scan(project, id) { return this.post("sources/scan", { project, id }); }
  acceptImports(project, ids) { return this.post("imports/accept", { project, ids }); }
  retryImports(project, ids) { return this.post("imports/retry", { project, ids }); }
  skipImports(project, ids, restore = false) { return this.post("imports/skip", { project, ids, restore }); }
  // milestones, reminders, notification settings
  milestones(project) { return this.get("milestones", project ? { project } : {}); }
  addMilestone(body) { return this.post("milestones/add", body); }
  updateMilestone(body) { return this.post("milestones/update", body); }
  deleteMilestone(id) { return this.post("milestones/delete", { id }); }
  notices() { return this.get("notices"); }
  dismissNotice(id) { return this.post("notices/dismiss", { id }); }
  notificationPrefs() { return this.get("settings/notifications"); }
  setNotificationPrefs(body) { return this.post("settings/notifications", body); }
  // desktop companion
  brief(id) { return this.get("companion/brief", { project: id }); }
  companionSettings() { return this.get("settings/companion"); }
  setCompanionSettings(body) { return this.post("settings/companion", body); }
  testNotification() { return this.post("companion/test-notification", {}); }
  openDashboard(path) { return this.post("open", { path }); }
  // assistant (Nemotron), autonomy, priority, offline sync, quit
  latestReview(id) { return this.get("review", { project: id }); }
  review(id, force = false) { return this.post("review", { project: id, force }); }
  catchUp(id) { return this.get("catchup", { project: id }); }
  runCatchUp(id, force = false) { return this.post("catchup", { project: id, force }); }
  assistantSettings() { return this.get("settings/assistant"); }
  setAssistantSettings(body) { return this.post("settings/assistant", body); }
  setPriority(project, priority) { return this.post("projects/priority", { project, priority }); }
  sync() { return this.get("sync"); }
  syncNow() { return this.post("sync", {}); }
  shutdown() { return this.post("shutdown", {}); }
  // Yosys synthesis skill
  synth(project) { return this.get("synth", { project }); }
  synthImport(project, filename, content) { return this.post("synth/import", { project, filename, content }); }
  synthCompare(project, run, baseline) { return this.post("synth/compare", { project, run, baseline }); }
  synthExplain(project, analysis) { return this.post("synth/explain", { project, analysis }); }
  synthConstraints(project, constraints) { return this.post("synth/constraints", { project, constraints }); }
  synthExcerpt(project, run) { return this.get("synth/excerpt", { project, run }); }
  proposals(project) { return this.get("proposals", { project }); }
  applyProposal(project, event) { return this.post("proposals/apply", { project, event }); }
  discardProposal(project, event, reason = "") { return this.post("proposals/discard", { project, event, reason }); }
}

class SnapshotService {
  mode = "snapshot";
  constructor(base) { this.base = base.replace(/\/$/, ""); this.cache = new Map(); }
  async file(path) {
    if (!this.cache.has(path)) {
      this.cache.set(path, fetch(`${this.base}/${path}`).then((r) => {
        if (!r.ok) throw new Error("This part of the demo snapshot is not available.");
        return r.json();
      }));
    }
    return this.cache.get(path);
  }
  readOnly() { return Promise.reject(new Error("This is a read-only demo snapshot. Run TaskMaster locally to record updates.")); }
  meta() { return this.file("meta.json"); }
  workspace() { return this.file("workspace.json"); }
  project(id) { return this.file(`p/${id}/project.json`); }
  state(id, v) { return this.file(`p/${id}/state/${v}.json`); }
  events(id) { return this.file(`p/${id}/events.json`); }
  evidence(id) { return this.file(`p/${id}/evidence.json`); }
  transition(id, e) { return this.file(`p/${id}/transition/${e}.json`); }
  activity() { return this.file("activity.json"); }
  async why(id, q) {
    const all = await this.file(`p/${id}/why.json`);
    return { text: all[q] || "Explanations for free-text queries need the live app. Click a claim to see its evidence." };
  }
  async ask(id, question) {
    const all = await this.file(`p/${id}/ask.json`);
    const hit = Object.keys(all).find((k) => k.toLowerCase() === question.trim().toLowerCase());
    if (hit) return all[hit];
    return { intent: "free", mode: "read-only snapshot", headline: "Only the suggested questions are available here",
      text: "This hosted demo is a read-only snapshot without a model connection. Pick one of the suggested questions, or run TaskMaster locally with Nemotron to ask anything.",
      citations: [], next_step: null };
  }
  async milestones(project) {
    const ws = await this.workspace();
    const ids = project ? [project] : ws.projects.map((p) => p.id);
    const all = await Promise.all(ids.map((id) => this.project(id).then((p) => p.milestones || []).catch(() => [])));
    return { milestones: all.flat(), rules: {} };
  }
  sources() { return Promise.resolve({ sources: [], items: [], counts: {}, can_accept: false, snapshot: true }); }
  notices() { return Promise.resolve({ notices: [], quiet: true, prefs: null }); }
  notificationPrefs() { return Promise.resolve(null); }
  createProject() { return this.readOnly(); }
  loadSample() { return this.readOnly(); }
  addEvent() { return this.readOnly(); }
  retry() { return this.readOnly(); }
  addSource() { return this.readOnly(); }
  updateSource() { return this.readOnly(); }
  removeSource() { return this.readOnly(); }
  scan() { return this.readOnly(); }
  acceptImports() { return this.readOnly(); }
  retryImports() { return this.readOnly(); }
  skipImports() { return this.readOnly(); }
  addMilestone() { return this.readOnly(); }
  updateMilestone() { return this.readOnly(); }
  deleteMilestone() { return this.readOnly(); }
  dismissNotice() { return this.readOnly(); }
  setNotificationPrefs() { return this.readOnly(); }
  brief() { return Promise.reject(new Error("The companion needs the local TaskMaster server.")); }
  companionSettings() { return Promise.resolve(null); }
  setCompanionSettings() { return this.readOnly(); }
  testNotification() { return this.readOnly(); }
  openDashboard() { return this.readOnly(); }
  latestReview() { return Promise.resolve({ review: null }); }
  review() { return this.readOnly(); }
  catchUp(id) { return this.file(`p/${id}/catchup.json`); }
  runCatchUp() { return this.readOnly(); }
  assistantSettings() { return Promise.resolve(null); }
  setAssistantSettings() { return this.readOnly(); }
  setPriority() { return this.readOnly(); }
  sync() { return Promise.resolve({ queued_total: 0, assistant: false }); }
  syncNow() { return this.readOnly(); }
  shutdown() { return this.readOnly(); }
  synth() { return Promise.resolve({ runs: [], analyses: [], constraints: {}, constraint_keys: {}, snapshot: true }); }
  synthImport() { return this.readOnly(); }
  synthCompare() { return this.readOnly(); }
  synthExplain() { return this.readOnly(); }
  synthConstraints() { return this.readOnly(); }
  synthExcerpt() { return this.readOnly(); }
  proposals() { return Promise.resolve({ proposals: [] }); }
  applyProposal() { return this.readOnly(); }
  discardProposal() { return this.readOnly(); }
}

export const api = window.TM_SNAPSHOT ? new SnapshotService(window.TM_SNAPSHOT) : new LiveService();

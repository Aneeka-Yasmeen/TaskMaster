// Shared application state + data loading with a small cache.
import { api } from "./api.js";

export const ctx = {
  meta: null,
  workspace: null,
  project: null,          // current project id (sidebar context)
  rerender: () => {},     // set by the router
  canWrite: false,
};

const cache = new Map();

export function setCurrentProject(id) {
  if (!id) return;
  ctx.project = id;
  try { localStorage.setItem("tm.project", id); } catch {}
}
export function savedProject() {
  try { return localStorage.getItem("tm.project"); } catch { return null; }
}

export async function loadWorkspace(force = false) {
  if (!ctx.workspace || force) ctx.workspace = await api.workspace();
  return ctx.workspace;
}

// Everything a project screen needs, fetched once and shared across screens.
export async function projectBundle(id, force = false) {
  if (!force && cache.has(id)) return cache.get(id);
  const p = Promise.all([api.project(id), api.events(id)]).then(([proj, ev]) => {
    const events = Object.fromEntries(ev.events.map((e) => [e.id, e]));
    const transitions = Object.fromEntries(ev.transitions.map((t) => [t.event_id, t]));
    return { ...proj, events, eventList: ev.events, transitions };
  });
  cache.set(id, p);
  p.catch(() => cache.delete(id));
  return p;
}

export async function evidenceIndex(id) {
  const key = `ev:${id}`;
  if (!cache.has(key)) {
    const p = api.evidence(id).then((r) => Object.fromEntries(r.evidence.map((e) => [e.id, e])));
    cache.set(key, p);
    p.catch(() => cache.delete(key));
  }
  return cache.get(key);
}

export function invalidate(id) {
  for (const k of [...cache.keys()]) if (k === id || k === `ev:${id}`) cache.delete(k);
  ctx.workspace = null;
}

export const projectName = (id) => (ctx.workspace?.projects.find((p) => p.id === id)?.name) || id;

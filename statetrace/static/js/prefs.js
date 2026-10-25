// Display preferences (per browser): text size and Simple/Detailed layout. Large + Simple by default.
const get = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const set = (k, v) => { try { localStorage.setItem(k, v); } catch {} };

export const prefs = {
  get textSize() { return get("tm.text", "large"); },
  get layout() { return get("tm.layout", "simple"); },
};

export function applyPrefs() {
  document.body.classList.toggle("large-text", prefs.textSize === "large");
  document.body.classList.toggle("simple", prefs.layout === "simple");
}

export function setTextSize(v) { set("tm.text", v); applyPrefs(); }
export function setLayout(v) { set("tm.layout", v); applyPrefs(); }
export function toggleLayout() { setLayout(prefs.layout === "simple" ? "detailed" : "simple"); return prefs.layout; }

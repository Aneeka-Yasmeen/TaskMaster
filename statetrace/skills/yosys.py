"""Yosys synthesis-statistics skill: parsing, classification, comparison, constraints.

Pure and deterministic: no model, no I/O. Report text is treated as data only.

Supported input
  * text output of Yosys `stat` (classic "Number of cells:" format, incl. `=== design hierarchy ===`,
    and the newer "<count> cells" layout), optionally with "Chip area" lines from `stat -liberty`;
  * JSON output of `stat -json` (Yosys 0.10+): {"modules": {...}, "design": {...}}.

Only metrics present in the report are returned. Counts derived from cell-type names (flip-flops,
LUTs, DSP and memory primitives) are computed by documented name rules and labelled as derived.
"""

import hashlib
import json
import re

MAX_BYTES = 2_000_000          # reject larger files
MAX_CELL_TYPES = 500           # bounded representation
SAFE_TYPE = re.compile(r"^[A-Za-z0-9_$\\.:\[\]/<>-]{1,80}$")

# metric key -> (label, unit/notes)
METRICS = {
    "cells": "Total cells",
    "wires": "Wires",
    "wire_bits": "Wire bits",
    "public_wires": "Public wires",
    "public_wire_bits": "Public wire bits",
    "memories": "Memories",
    "memory_bits": "Memory bits",
    "processes": "Processes",
    "chip_area": "Chip area (liberty estimate)",
    "transistors": "Estimated transistors",
}
DERIVED = {
    "flip_flops": "Flip-flops (from cell names)",
    "latches": "Latches (from cell names)",
    "luts": "LUTs (from cell names)",
    "dsp": "DSP / multiplier primitives (from cell names)",
    "memory_primitives": "Memory primitives (from cell names)",
}
TEXT_KEYS = {
    "number of wires": "wires", "number of wire bits": "wire_bits", "number of public wires": "public_wires",
    "number of public wire bits": "public_wire_bits", "number of memories": "memories",
    "number of memory bits": "memory_bits", "number of processes": "processes", "number of cells": "cells",
    # newer layout: "<n> wires"
    "wires": "wires", "wire bits": "wire_bits", "public wires": "public_wires", "public wire bits": "public_wire_bits",
    "memories": "memories", "memory bits": "memory_bits", "processes": "processes", "cells": "cells",
}
JSON_KEYS = {"num_wires": "wires", "num_wire_bits": "wire_bits", "num_pub_wires": "public_wires",
             "num_pub_wire_bits": "public_wire_bits", "num_memories": "memories", "num_memory_bits": "memory_bits",
             "num_processes": "processes", "num_cells": "cells", "area": "chip_area"}

# Classification rules (case-insensitive regex on the cell type name). Documented in the UI.
CLASS_RULES = {
    "flip_flops": r"^\$_(s?dff|dffe|sdffe|sdffce|aldff|aldffe|dffsr|dffsre)|^\$(a|s|al)?dffe?$|^\$dffsr$|^fd[rcsp]e?$|^fd[rcsp]_?\d*$|dff|df[a-z]*tp|dfrtp|dfstp|dfbbp|^sb_dff",
    "latches": r"^\$_dlatch|^\$dlatch|dlxtp|dlxbp|^ld[cp]e?$|latch",
    "luts": r"^lut[1-6]$|^sb_lut4$|^\$lut$|^lut4$",
    "dsp": r"^dsp48|^dsp58|^sb_mac16$|^mult18x18|^mult9x9|^alu54|^dsp_|^mac_",
    "memory_primitives": r"^ramb(18|36)|^sb_(sp)?ram|^dp16kd|^pdpw16kd|^\$mem(_v2)?$|^ram(32|64|128|256)[xm]|^bram",
}
_CLASS_RE = {k: re.compile(v, re.I) for k, v in CLASS_RULES.items()}


class ReportError(ValueError):
    """The input can't be used; .diagnostics says what was found."""

    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes):
    if len(data) > MAX_BYTES:
        raise ReportError(f"File is {len(data):,} bytes; the limit is {MAX_BYTES:,}. Export only the `stat` output.",
                          {"size": len(data)})
    if b"\x00" in data[:4096]:
        raise ReportError("This looks like a binary file, not a Yosys text or JSON report.", {"size": len(data)})
    return data.decode("utf-8", errors="replace")


def classify(cell_types):
    """Derived counts from cell-type names. Only computed when a breakdown is present."""
    out = {k: 0 for k in CLASS_RULES}
    matched = {k: [] for k in CLASS_RULES}
    for name, n in cell_types.items():
        bare = name.lstrip("\\")
        for k, rx in _CLASS_RE.items():
            if rx.search(bare):
                out[k] += n
                matched[k].append(name)
                break
    return out, matched


def _num(s):
    s = s.strip().replace(",", "")
    return float(s) if "." in s or "e" in s.lower() else int(s)


def _parse_text(text):
    lines = text.splitlines()
    sections = []  # (name, metrics, cell_types, warnings)
    cur = None
    in_cells = False
    for raw in lines:
        line = raw.rstrip()
        m = re.match(r"^\s*===\s*(.+?)\s*===\s*$", line)
        if m:
            cur = {"name": m.group(1).strip(), "metrics": {}, "cell_types": {}, "warnings": [], "skipped": []}
            sections.append(cur)
            in_cells = False
            continue
        if cur is None:
            continue
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(Number of [a-z ]+):\s*([0-9][0-9,]*)$", s, re.I)            # classic layout
        if m and m.group(1).lower() in TEXT_KEYS:
            key = TEXT_KEYS[m.group(1).lower()]
            cur["metrics"][key] = _num(m.group(2))
            in_cells = key == "cells"
            continue
        m = re.match(r"^([0-9][0-9,]*)\s+(wires|wire bits|public wires|public wire bits|memories|memory bits|processes|cells)$", s, re.I)
        if m:                                                                        # newer layout
            key = TEXT_KEYS[m.group(2).lower()]
            cur["metrics"][key] = _num(m.group(1))
            in_cells = key == "cells"
            continue
        m = re.match(r"^Chip area for (?:module|top module)\s+'?\\?([^':]+)'?:\s*([0-9.eE+-]+)$", s)
        if m:
            cur["metrics"]["chip_area"] = _num(m.group(2))
            in_cells = False
            continue
        m = re.match(r"^Estimated number of transistors:\s*([0-9][0-9,]*)\+?$", s)
        if m:
            cur["metrics"]["transistors"] = _num(m.group(1))
            in_cells = False
            continue
        if in_cells:
            m = re.match(r"^(\S+)\s+([0-9][0-9,]*)$", s) or re.match(r"^([0-9][0-9,]*)\s+(\S+)$", s)
            if m:
                a, b = m.group(1), m.group(2)
                name, n = (a, b) if not a.replace(",", "").isdigit() else (b, a)
                if SAFE_TYPE.match(name):
                    cur["cell_types"][name] = cur["cell_types"].get(name, 0) + _num(n)
                else:
                    # never echo raw report text into warnings (they feed the evidence text the model reads)
                    cur["skipped"].append(s[:80])
                continue
            in_cells = False
    return [x for x in sections if x["metrics"] or x["cell_types"]]


def _parse_json(obj):
    def conv(d):
        metrics = {JSON_KEYS[k]: v for k, v in d.items() if k in JSON_KEYS and isinstance(v, (int, float))}
        types = {k: v for k, v in (d.get("num_cells_by_type") or {}).items()
                 if isinstance(v, (int, float)) and SAFE_TYPE.match(str(k))}
        return metrics, types
    sections = []
    for name, d in (obj.get("modules") or {}).items():
        if isinstance(d, dict):
            m, t = conv(d)
            sections.append({"name": str(name).lstrip("\\"), "metrics": m, "cell_types": t, "warnings": [], "skipped": []})
    if isinstance(obj.get("design"), dict):
        m, t = conv(obj["design"])
        sections.append({"name": "design hierarchy", "metrics": m, "cell_types": t, "warnings": [], "skipped": []})
    return [x for x in sections if x["metrics"] or x["cell_types"]]


def parse(data: bytes, filename="report"):
    """Parse a Yosys stat report. Returns a dict; raises ReportError when nothing usable is found."""
    text = decode(data)
    stripped = text.lstrip()
    fmt = "text"
    sections = []
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise ReportError(f"The file starts like JSON but isn't valid JSON ({e.msg} at line {e.lineno}).",
                              {"preview": stripped[:300]})
        if not isinstance(obj, dict) or not ("modules" in obj or "design" in obj):
            raise ReportError("This JSON doesn't look like Yosys `stat -json` output (no \"modules\" or \"design\").",
                              {"keys": sorted(obj)[:20] if isinstance(obj, dict) else type(obj).__name__})
        fmt = "json"
        sections = _parse_json(obj)
    else:
        sections = _parse_text(text)
    if not sections:
        found = [ln.strip() for ln in text.splitlines() if ln.strip()][:8]
        raise ReportError(
            "No Yosys statistics found. Expected a `=== module ===` section with lines like "
            "'Number of cells: 478' (run `tee -o report.rpt stat` after synthesis).",
            {"first_lines": found, "size": len(data)})

    warnings = [w for s in sections for w in s["warnings"]]
    skipped = [x for s in sections for x in s.get("skipped", [])]
    if skipped:
        warnings.append(f"skipped {len(skipped)} cell-type line(s) that don't look like Yosys cell names "
                        "(shown under diagnostics; not used).")
    hier = next((s for s in sections if s["name"].lower() == "design hierarchy"), None)
    modules = [s for s in sections if s is not hier]
    if hier:
        design, scope = hier, "design hierarchy summary"
    elif len(modules) == 1:
        design, scope = modules[0], f"module {modules[0]['name']}"
    else:
        design, scope = None, None
        warnings.append(f"{len(modules)} modules but no design hierarchy summary: design totals were NOT inferred "
                        "(re-run `stat -top <top>` to get them). Per-module numbers are kept.")
    metrics = dict(design["metrics"]) if design else {}
    cell_types = dict(design["cell_types"]) if design else {}
    if len(cell_types) > MAX_CELL_TYPES:
        warnings.append(f"{len(cell_types)} cell types; kept the {MAX_CELL_TYPES} largest.")
        cell_types = dict(sorted(cell_types.items(), key=lambda kv: -kv[1])[:MAX_CELL_TYPES])
    derived, matched = ({}, {})
    if cell_types:
        derived, matched = classify(cell_types)
        # cells that are submodule instances aren't primitives; note them rather than guess
        insts = [t for t in cell_types if t in {m["name"] for m in modules}]
        if insts:
            warnings.append(f"cell types {', '.join(insts)} are submodule instances (counted as 1 cell each by Yosys).")
    if "cells" in metrics and cell_types and sum(cell_types.values()) != metrics["cells"]:
        warnings.append(f"cell-type breakdown sums to {sum(cell_types.values())}, but 'Number of cells' is "
                        f"{metrics['cells']}; both kept as reported.")
    if design and "cells" not in metrics:
        warnings.append("The report has no total cell count.")
    top = next((m["name"] for m in modules if hier is None or m["name"] in _hier_top(text)), None) if modules else None
    return {
        "format": fmt,
        "filename": filename,
        "scope": scope,
        "top": top if hier else (modules[0]["name"] if len(modules) == 1 else None),
        "modules": {m["name"]: {"metrics": m["metrics"], "cells": m["metrics"].get("cells")} for m in modules},
        "metrics": metrics,
        "cell_types": cell_types,
        "derived": derived if cell_types else {},
        "derived_types": {k: v for k, v in matched.items() if v} if cell_types else {},
        "library": library_family(cell_types),
        "warnings": warnings,
        "skipped_lines": skipped[:10],
    }


def _hier_top(text):
    m = re.search(r"===\s*design hierarchy\s*===\s*\n\s*\n?\s*(\S+)\s+\d+", text)
    return {m.group(1)} if m else set()


def library_family(cell_types):
    """Rough family of cell names, used only to warn when comparing unlike runs."""
    if not cell_types:
        return None
    names = [t.lstrip("\\").lower() for t in cell_types]
    if all(n.startswith("$") for n in names):
        return "yosys generic gates"
    if any(re.match(r"^(lut[1-6]|fd[rcsp]e|muxcy|xorcy|carry4|ramb|dsp48)", n) for n in names):
        return "xilinx primitives"
    if any(n.startswith("sb_") for n in names):
        return "ice40 primitives"
    if any("__" in n for n in names):
        return "standard-cell liberty (" + names[0].split("__")[0] + ")"
    return "mixed / unknown"


# comparison ---------------------------------------------------------------------------------------
def _delta(b, c):
    if b is None or c is None:
        return {"baseline": b, "current": c, "abs": None, "pct": None,
                "note": "missing in baseline" if b is None else "missing in current run"}
    d = c - b
    if b == 0:
        return {"baseline": b, "current": c, "abs": d, "pct": None,
                "note": "baseline is 0: percentage undefined" if c != 0 else None}
    return {"baseline": b, "current": c, "abs": d, "pct": round(d / b * 100, 2), "note": None}


def compare(base, cur):
    """Deterministic comparison of two parsed runs. No judgement of 'better' or 'worse'."""
    rows = []
    for key, label in METRICS.items():
        if key in base["metrics"] or key in cur["metrics"]:
            rows.append({"key": key, "label": label, "derived": False,
                         **_delta(base["metrics"].get(key), cur["metrics"].get(key))})
    for key, label in DERIVED.items():
        b, c = base.get("derived", {}).get(key), cur.get("derived", {}).get(key)
        if (b or c):  # only show derived classes that occur in at least one run
            rows.append({"key": key, "label": label, "derived": True, **_delta(b, c)})
    bt, ct = base.get("cell_types", {}), cur.get("cell_types", {})
    types = []
    for t in sorted(set(bt) | set(ct)):
        d = _delta(bt.get(t), ct.get(t))
        d["type"] = t
        d["status"] = "new" if t not in bt else "gone" if t not in ct else "changed" if bt[t] != ct[t] else "same"
        types.append(d)
    types.sort(key=lambda r: (-abs((r["current"] or 0) - (r["baseline"] or 0)), r["type"]))
    limitations = [
        "Cell counts describe the synthesized netlist only. They are not timing, power or physical area; "
        "no conclusion about those is drawn from this comparison.",
    ]
    if base.get("library") != cur.get("library"):
        limitations.append(f"Different cell libraries ({base.get('library')} vs {cur.get('library')}): "
                           "cell counts and types are not directly comparable.")
    if base.get("top") and cur.get("top") and base["top"] != cur["top"]:
        limitations.append(f"Different top modules ({base['top']} vs {cur['top']}).")
    if base.get("scope") != cur.get("scope"):
        limitations.append(f"Different report scopes ({base.get('scope')} vs {cur.get('scope')}).")
    for r in rows:
        if r["note"] and r["note"].startswith("missing"):
            limitations.append(f"{r['label']}: {r['note']}; not compared.")
    if not bt or not ct:
        limitations.append("One run has no cell-type breakdown; type-level comparison is incomplete.")
    return {"metrics": rows, "cell_types": types,
            "new_types": [t["type"] for t in types if t["status"] == "new"],
            "gone_types": [t["type"] for t in types if t["status"] == "gone"],
            "limitations": limitations}


CONSTRAINT_KEYS = {"max_cells": ("cells", "Total cells"), "max_flip_flops": ("flip_flops", "Flip-flops"),
                   "max_luts": ("luts", "LUTs"), "max_chip_area": ("chip_area", "Chip area")}


def check_constraints(run, constraints):
    """Flag violations only when the measurement exists."""
    out = []
    for ck, limit in (constraints or {}).items():
        if ck not in CONSTRAINT_KEYS or limit in (None, ""):
            continue
        key, label = CONSTRAINT_KEYS[ck]
        value = run["metrics"].get(key, run.get("derived", {}).get(key) if run.get("cell_types") else None)
        if key in DERIVED and not value:
            # zero cells of a class usually means the library doesn't use it (e.g. LUTs in a generic-gate
            # netlist); that is not evidence the limit is met
            out.append({"constraint": ck, "label": label, "limit": limit, "value": None, "status": "unknown",
                        "note": f"No {label.lower()} cells in this report (library: {run.get('library')}); can't check."})
            continue
        if value is None:
            out.append({"constraint": ck, "label": label, "limit": limit, "value": None, "status": "unknown",
                        "note": f"{label} is not in this report; can't check."})
        else:
            ok = value <= limit
            out.append({"constraint": ck, "label": label, "limit": limit, "value": value,
                        "status": "ok" if ok else "violated",
                        "note": None if ok else f"{label} {value} exceeds the limit {limit} by {value - limit}."})
    return out


def evidence_text(run, sha, filename):
    """Bounded, sanitized summary used as the evidence event text (the raw report is not sent to the model)."""
    m, d = run["metrics"], run.get("derived", {})
    parts = [f"Yosys synthesis statistics from {filename} ({run['format']}, {run['scope'] or 'per-module only'}"
             f"{', top ' + run['top'] if run.get('top') else ''}; sha256 {sha[:12]})."]
    if m:
        parts.append("Measured: " + "; ".join(f"{METRICS[k]} {m[k]}" for k in METRICS if k in m) + ".")
    if run.get("cell_types"):
        top = sorted(run["cell_types"].items(), key=lambda kv: -kv[1])[:15]
        parts.append("Cell types: " + ", ".join(f"{t} {n}" for t, n in top)
                     + (f" (+{len(run['cell_types']) - 15} more)" if len(run["cell_types"]) > 15 else "") + ".")
        dd = {k: v for k, v in d.items() if v}
        if dd:
            parts.append("Derived from cell names: " + "; ".join(f"{DERIVED[k]} {v}" for k, v in dd.items()) + ".")
    if not m and run.get("modules"):
        parts.append("Per-module cells: " + ", ".join(f"{n} {v['cells']}" for n, v in run["modules"].items()) + ".")
    if run.get("warnings"):
        parts.append("Parser notes: " + " ".join(run["warnings"])[:400])
    return " ".join(parts)[:3000]

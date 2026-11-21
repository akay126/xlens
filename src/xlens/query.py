"""Pure, size-capped queries over an Analysis. Outputs are JSON-safe dicts.

Every result carries ``focus`` (node ids to highlight on the map) and ``mode``. Every list is in a
stable order (workbook sheet order, then row, then column) so repeated calls return identical JSON.
"""
from __future__ import annotations

import difflib
import json
import math
import re

import networkx as nx

from xlens.rows import row_model, split_ref

MAX_BYTES = 8000
MAX_TEXT = 120          # longest label/string value returned (labels are data, never markup)
MAX_GROUP_CELLS = 12    # cells listed per row group in a trace
MAX_FOCUS = 150
MAX_PATHS = 1000        # path counts are capped here (drivers)
MAX_SCENARIOS = 12
_SEVERITY = {"error": 0, "warning": 1, "info": 2}
_REF_IN = re.compile(r"^\s*(?:(?:'(?P<q>(?:[^']|'')+)'|(?P<u>[^'!]+))!)?"
                     r"\$?(?P<col>[A-Za-z]{1,3})\$?(?P<row>\d+)\s*$")


# Finance abbreviations, matched in both directions by `find` (compared as lowercase word lists).
ABBREVIATIONS = {
    "noi": "net operating income",
    "egi": "effective gross income",
    "gpr": "gross potential rent",
    "dscr": "debt service coverage",
    "cfads": "cash flow after debt service",
    "ltv": "loan to value",
    "coc": "cash on cash",
    "irr": "internal rate of return",
    "em": "equity multiple",
    "opex": "operating expenses",
    "capex": "capital expenditures",
    "t12": "trailing twelve",
}
_WORDS = re.compile(r"[a-z0-9]+")


def _tokens(text) -> list:
    return _WORDS.findall(str(text).lower())


def _variants(query: str) -> list:
    """The query as words, plus each abbreviation/expansion swapped for its counterpart (one swap each)."""
    base = _tokens(query)
    out = [base]
    for ab, ex in sorted(ABBREVIATIONS.items()):
        for src, dst in ((_tokens(ab), _tokens(ex)), (_tokens(ex), _tokens(ab))):
            n = len(src)
            for i in range(len(base) - n + 1):
                if base[i:i + n] == src:
                    v = base[:i] + dst + base[i + n:]
                    if v not in out:
                        out.append(v)
    return out


def _word_hit(w: str, label_words: list) -> bool:
    return any(w == lw or (len(w) >= 4 and lw.startswith(w)) for lw in label_words)


def _label_matches(variants: list, label: str) -> bool:
    words = _tokens(label)
    return any(v and all(_word_hit(w, words) for w in v) for v in variants)


class XlensInputError(ValueError):
    """A caller passed an argument Xlens rejects; the message is safe to show to users and agents."""


class CellNotFound(XlensInputError):
    pass


def _val(v):
    if isinstance(v, float):
        return round(v, 6) if math.isfinite(v) else None
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXT else v[:MAX_TEXT] + "..."
    if isinstance(v, (int, bool)) or v is None:
        return v
    return str(v)


def _sheet_rank(a) -> dict:
    return {s: i for i, s in enumerate(a.results["metadata"]["sheet_names"])}


def _order_key(a):
    rank = _sheet_rank(a)

    def key(node: str):
        sheet, r, n, _ = split_ref(node)
        return (rank.get(sheet, len(rank)), sheet, r, n, node)
    return key


def resolve(a, ref: str) -> str:
    """Normalise 'cash flow'!$c$11 -> 'Cash Flow!C11'; raise CellNotFound with suggestions."""
    ref = ref if isinstance(ref, str) else str(ref)
    m = _REF_IN.match(ref)
    sheets = a.results["metadata"]["sheet_names"]
    if m:
        sheet = (m["q"].replace("''", "'") if m["q"] else m["u"]) or ""
        match = next((s for s in sheets if s.lower() == sheet.strip().lower()), None) if sheet else None
        if sheet and match is None:
            raise CellNotFound(f"No sheet named '{_val(sheet)}'. Sheets: {', '.join(sheets)}")
        found = [n for n in (f"{s}!{m['col'].upper()}{m['row']}" for s in ([match] if match else sheets))
                 if n in a.graph]
        if len(found) > 1:
            raise CellNotFound(f"'{ref}' is ambiguous: {', '.join(found)}. Qualify it with a sheet name.")
        if found:
            return found[0]
    near = difflib.get_close_matches(ref, sorted(a.graph.nodes), n=5, cutoff=0.4)
    hint = f" Did you mean: {', '.join(near)}?" if near else " Try find() with a label instead."
    raise CellNotFound(f"Cell '{ref}' is not in the model's formula graph.{hint}")


def _text(v):
    """Truncate to MAX_TEXT; returns (text, was_truncated)."""
    v = v if isinstance(v, str) else ("" if v is None else str(v))
    return (v[:MAX_TEXT] + "...", True) if len(v) > MAX_TEXT else (v, False)


def _cell(a, node: str) -> dict:
    d = a.graph.nodes[node]
    label, lt = _text((d.get("row_label") or "").strip())
    formula, ft = _text(d.get("formula") or "")
    out = {"id": node, "label": label, "formula": formula,
           "value": _val(d.get("cached_value", d.get("value"))), "kind": d.get("classification") or ""}
    out = {k: v for k, v in out.items() if v not in (None, "")}
    if lt:
        out["label_truncated"] = True
    if ft:
        out["formula_truncated"] = True
    return out


def _group(a, nodes) -> list:
    """Group cells by sheet row, groups in (workbook sheet order, row) order."""
    rm = row_model(a)
    groups: dict = {}
    for n in sorted(nodes, key=_order_key(a)):
        key = rm.row_of.get(n, f"cell:{n}")
        row = rm.rows.get(key)
        g = groups.get(key)
        if g is None:
            label, lt = _text(row.label if row else n)
            g = groups[key] = {"row": key, "label": label, "sheet": split_ref(n)[0], "cell_count": len(row.cells) if row else 1, "cells": []}
            if lt:
                g["label_truncated"] = True
        if len(g["cells"]) < MAX_GROUP_CELLS:
            g["cells"].append(_cell(a, n))
    for g in groups.values():
        if len(g["cells"]) < g["cell_count"]:
            g["cells_shown"] = len(g["cells"])
    return list(groups.values())


def _size(result: dict) -> int:
    return len(json.dumps(result, default=str))


def _cap(result: dict, *list_keys: str, last_resort: tuple = (), final: tuple = (), drop: tuple = (), refocus=None) -> dict:
    """Shrink `result` until its JSON fits MAX_BYTES, and mark truncation.

    Order: pop from the longest of `list_keys`; then `last_resort` lists; then `final` lists; then `focus`; finally
    delete the optional fields in `drop`. `refocus(result)` rebuilds `focus` after each trim.
    """
    def trim() -> bool:
        for keys in (list_keys, last_resort, final):
            live = [k for k in keys if result.get(k)]
            if live:
                result[max(live, key=lambda k: len(result[k]))].pop()
                if refocus:
                    result["focus"] = refocus(result)
                return True
        if len(result.get("focus", ())) > 1:
            result["focus"].pop()
            return True
        for k in drop:
            if k in result:
                del result[k]
                return True
        return False

    while _size(result) > MAX_BYTES:
        if not trim():
            break
        result["truncated"] = True
        result["hint"] = "Result trimmed to fit. Ask about a narrower cell or lower depth."
    return result


def _hardcode_items(a) -> list:
    key = _order_key(a)
    hc = sorted(a.results["hardcodes"], key=lambda h: (_SEVERITY.get(h["severity"], 3), key(h["cell_ref"])))
    return [{"kind": "hardcode", "cell": h["cell_ref"], "severity": h["severity"],
             "label": _text(h.get("label_context", ""))[0], "value": _val(h["value"]),
             "advice": _text(h.get("recommendation", ""))[0]} for h in hc]


def overview(a) -> dict:
    r = a.results
    md = r["metadata"]
    t = lambda x: _text(x)[0]  # noqa: E731
    kpis = [{"name": t(k["name"]), "cell": k["cell_ref"], "value": _val(k["value"]), "display": t(k["formatted_value"]),
             "scenarios": [{"cell": s["cell_ref"], "header": t(s["header"]), "display": t(s["formatted_value"])}
                           for s in k.get("scenarios", [])[:MAX_SCENARIOS]]} for k in r["kpis"]]
    top = [{k: v for k, v in f.items() if k != "advice"} for f in _hardcode_items(a)[:10]]
    out = {
        "model": t(md["model_name"]),
        "sheets": [{"name": t(s), "role": md["sheet_roles"].get(s, "calc")} for s in md["sheet_names"]],
        "counts": {"cells": r["cells_summary"]["total"], "formulas": r["cells_summary"]["formula_count"],
                   "rows": len(row_model(a).rows), "hardcodes": len(r["hardcodes"]),
                   "circular_refs": r["graph_stats"].get("circular_ref_count", 0)},
        "flow": [{"name": t(b["name"]), "sheet": t(b["sheet"]), "connects_to": [t(c) for c in b["connects_to"]]}
                 for b in r["flow_blocks"]],
        "kpis": kpis, "top_findings": top,
        "focus": [k["cell"] for k in kpis][:MAX_FOCUS], "mode": "overview",
    }
    return _cap(out, "top_findings", last_resort=("flow", "sheets"), final=("kpis",), drop=("counts", "flow", "sheets"),
                refocus=lambda o: [k["cell"] for k in o["kpis"]][:MAX_FOCUS])


def _render_trace(a, base: dict, picked: dict) -> dict:
    out = dict(base)
    for direction, nodes in picked.items():
        out[direction] = _group(a, nodes)
    return out


def trace(a, cell: str, direction: str = "up", depth: int = 1) -> dict:
    """Upstream/downstream cells grouped by row. When the result must be trimmed, the cells farthest
    from `cell` go first (so direct precedents/dependents survive) and `focus` is rebuilt from what is kept."""
    if direction not in ("up", "down", "both"):
        raise XlensInputError("direction must be 'up', 'down' or 'both'")
    node = resolve(a, cell)
    depth = max(1, min(int(depth), 5))
    key = _order_key(a)
    base = {"cell": _cell(a, node), "direction": direction, "depth": depth, "mode": "trace"}
    names = {"up": ("upstream",), "down": ("downstream",), "both": ("upstream", "downstream")}[direction]
    cand = []  # (distance, direction name, order key, node)
    for name, g, want in (("upstream", a.graph.reverse(copy=False), ("up", "both")), ("downstream", a.graph, ("down", "both"))):
        if direction in want:
            dist = nx.single_source_shortest_path_length(g, node, cutoff=depth)
            dist.pop(node, None)
            cand += [(d, name, key(n), n) for n, d in dist.items()]
    cand.sort()

    def build(k: int) -> dict:
        picked = {nm: [] for nm in names}
        for _, nm, _, n in cand[:k]:
            picked[nm].append(n)
        out = _render_trace(a, base, picked)
        out["focus"] = [node] + sorted((n for _, _, _, n in cand[:k]), key=key)[:MAX_FOCUS]
        if k < len(cand):
            out["truncated"] = True
            out["hint"] = "Result trimmed to fit. Ask about a narrower cell or lower depth."
        return out

    out = build(len(cand))
    if _size(out) > MAX_BYTES:
        lo, hi = 0, len(cand) - 1  # largest k that fits (k=0 always kept as fallback)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _size(build(mid)) <= MAX_BYTES:
                lo = mid
            else:
                hi = mid - 1
        out = build(lo)
    return _cap(out, "upstream", "downstream")


def find(a, text: str, limit: int = 20) -> dict:
    t = (text or "").strip()
    limit = max(1, min(int(limit), 50))
    rm = row_model(a)
    matches = []
    variants = _variants(t)
    if t:
        try:
            node = resolve(a, t)
            matches.append({**_cell(a, node), "row": rm.row_of.get(node)})
        except CellNotFound:
            pass
        rank = {s: i for i, s in enumerate(rm.sheet_order)}
        for row in sorted(rm.rows.values(), key=lambda r: (rank.get(r.sheet, len(rank)), r.row, r.key)):
            if len(matches) >= limit:
                break
            if _label_matches(variants, row.label):
                label, lt = _text(row.label)
                m = {"id": row.cells[-1], "row": row.key, "label": label, "sheet": row.sheet, "cells": len(row.cells)}
                if lt:
                    m["label_truncated"] = True
                matches.append(m)
    out = {"query": _text(t)[0], "matches": matches, "focus": [m["id"] for m in matches], "mode": "find"}
    return _cap(out, "matches", refocus=lambda o: [m["id"] for m in o["matches"]])


def drivers(a, cell: str, limit: int = 25) -> dict:
    """Rank the hard inputs (no formula, nothing upstream) that feed `cell`.

    `paths` is the exact number of distinct input-to-cell routes, capped at MAX_PATHS (1000). It is
    computed by dynamic programming over the ancestor subgraph in reverse topological order
    (paths[target] = 1, paths[n] = sum over its successors), so cost is linear in edges. Cycles are
    collapsed first (nx.condensation), so a looping model cannot hang or recurse. Order is (-paths, id).
    """
    node = resolve(a, cell)
    limit = max(1, min(int(limit), 100))
    anc = nx.ancestors(a.graph, node)
    anc.discard(node)
    inputs = sorted(n for n in anc if a.graph.in_degree(n) == 0 and not a.graph.nodes[n].get("formula"))
    cond = nx.condensation(a.graph.subgraph(anc | {node}))
    scc_of = cond.graph["mapping"]
    paths = {}
    for c in reversed(list(nx.topological_sort(cond))):
        paths[c] = 1 if c == scc_of[node] else min(MAX_PATHS, sum(paths[s] for s in cond.successors(c)))
    counts = {n: paths[scc_of[n]] for n in inputs}
    ranked = sorted(inputs, key=lambda n: (-counts[n], n))[:limit]
    out = {"cell": _cell(a, node), "drivers": [{**_cell(a, n), "paths": counts[n]} for n in ranked],
           "input_count": len(inputs), "focus": [node] + ranked, "mode": "drivers"}
    return _cap(out, "drivers", refocus=lambda o: [node] + [d["id"] for d in o["drivers"]])


def _findings_focus(o: dict) -> list:
    focus = []
    for i in o["items"]:
        focus += [i["cell"]] if "cell" in i else i["cells"]
    return focus[:MAX_FOCUS]


def findings(a, kind: str = "all", cap: bool = True) -> dict:
    if kind not in ("hardcodes", "circular", "all"):
        raise XlensInputError("kind must be 'hardcodes', 'circular' or 'all'")
    items = []
    if kind in ("hardcodes", "all"):
        items += _hardcode_items(a)
    if kind in ("circular", "all"):
        for c in a.results["graph_stats"].get("circular_references", []):
            items.append({"kind": "circular", "cells": c["cycle"][:10], "length": c.get("length", len(c["cycle"])),
                          "severity": "error", "advice": "These cells depend on each other in a loop."})
    out = {"kind": kind, "items": items, "mode": "findings"}
    out["focus"] = _findings_focus(out)
    return _cap(out, "items", refocus=_findings_focus) if cap else out


def show(a, cells: list) -> dict:
    nodes = list(dict.fromkeys(resolve(a, c) for c in cells))
    return {"ok": True, "focus": nodes[:MAX_FOCUS], "mode": "show"}

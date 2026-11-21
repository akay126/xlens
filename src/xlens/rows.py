"""Row model: one row = one sheet row with its columns folded together (the map's unit)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from xlens.kpi_identifier import _column_header

_REF = re.compile(r"^([A-Z]+)(\d+)$")


def split_ref(node_id: str) -> tuple:
    """Split a node id into (sheet, row, column number, column letters).

    Anything that is not a plain A1 reference (named ranges, ranges) gets row 0 and column number 0.
    """
    sheet, _, coord = node_id.rpartition("!")
    coord = coord.replace("$", "")
    m = _REF.match(coord)
    if not m:
        return sheet, 0, 0, coord
    col, row = m.group(1), int(m.group(2))
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return sheet, row, n, col


@dataclass(frozen=True)
class Row:
    """One sheet row with its columns folded together.

    `rolls` is True when the row builds on earlier columns of the same row (e.g. growth from prior year).
    `pre`/`suc` are keys of rows this row reads from / feeds, in workbook order.
    """
    key: str
    sheet: str
    row: int
    label: str
    cells: tuple
    headers: tuple
    pre: tuple = ()
    suc: tuple = ()
    rolls: bool = False


@dataclass(frozen=True)
class RowModel:
    rows: dict      # key -> Row, in workbook order
    row_of: dict    # node id -> row key
    sheet_order: tuple


def row_model(analysis) -> RowModel:
    if "rows" in analysis._cache:
        return analysis._cache["rows"]
    g, cells = analysis.graph, analysis.cells
    sheet_order = tuple(analysis.results["metadata"].get("sheet_names", []))
    rank = {s: i for i, s in enumerate(sheet_order)}

    def order(node):
        sheet, r, n, _ = split_ref(node)
        return (rank.get(sheet, len(rank)), sheet, r, n, node)

    info, row_of = {}, {}
    for node in sorted(g.nodes, key=order):
        if g.degree(node) == 0:
            continue
        sheet, r, _, _ = split_ref(node)
        key = f"{sheet}!{r}" if r else f"cell:{node}"
        d = info.setdefault(key, {"sheet": sheet, "row": r, "label": "", "cells": [], "headers": [],
                                  "pre": set(), "suc": set(), "rolls": False})
        if not d["label"]:
            d["label"] = (g.nodes[node].get("row_label") or "").strip()
        d["cells"].append(node)
        d["headers"].append(_column_header(cells, sheet, node.rpartition("!")[2].replace("$", "")) if r else "")
        row_of[node] = key
    for u, v in g.edges():
        ru, rv = row_of.get(u), row_of.get(v)
        if ru is None or rv is None:
            continue
        if ru == rv:
            if split_ref(u)[2] < split_ref(v)[2]:
                info[ru]["rolls"] = True
        else:
            info[rv]["pre"].add(ru)
            info[ru]["suc"].add(rv)
    idx = {k: i for i, k in enumerate(info)}
    rows = {}
    for k, d in info.items():
        rows[k] = Row(key=k, sheet=d["sheet"], row=d["row"], label=d["label"] or d["cells"][0],
                      cells=tuple(d["cells"]), headers=tuple(d["headers"]),
                      pre=tuple(sorted(d["pre"], key=idx.__getitem__)),
                      suc=tuple(sorted(d["suc"], key=idx.__getitem__)), rolls=d["rolls"])
    rm = RowModel(rows=rows, row_of=row_of, sheet_order=sheet_order)
    analysis._cache["rows"] = rm
    return rm

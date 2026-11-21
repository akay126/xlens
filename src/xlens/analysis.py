"""Run the pipeline once per workbook and cache the result by path + mtime + size.

Thread-safe: the MCP server runs tools in worker threads, so concurrent loads of one file share a
single pipeline run, and the cache is a small LRU.
"""
from __future__ import annotations

import os
import threading
import zipfile
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import networkx as nx

from xlens.assumption_analyzer import analyze_assumptions
from xlens.complexity_scorer import score_complexity
from xlens.extractor import extract_cells
from xlens.flow_builder import build_flow
from xlens.graph_builder import build_graph, export_graph_json
from xlens.hardcode_detector import detect_hardcodes
from xlens.kpi_identifier import identify_kpis


def _extract_property_name(cells: dict) -> str:
    """Try to extract property name from the workbook title cells."""
    for (_sheet, coord), cd in cells.items():
        if coord == "A1" and isinstance(cd.get("raw_value"), str):
            name = cd["raw_value"]
            for suffix in [
                " - Underwriting Model",
                " -- Underwriting Model",
                " UNDERWRITING ASSUMPTIONS",
                " APARTMENTS",
            ]:
                if suffix.upper() in name.upper():
                    idx = name.upper().index(suffix.upper())
                    name = name[:idx].strip(" -\u2014")
            if name and len(name) < 80:
                return name
    return "Unknown Property"


_UNSUPPORTED = {".xls", ".xlsb", ".xlsm", ".ods", ".csv"}


class AnalysisError(Exception):
    """A workbook could not be analysed; the message is safe to show to users and agents."""


@dataclass
class Analysis:
    path: str
    cells: dict
    graph: nx.DiGraph
    context: dict
    results: dict = field(default_factory=dict)
    _cache: dict = field(default_factory=dict, repr=False)  # per-analysis memo for derived views


CACHE_SIZE = 4
_CACHE: OrderedDict = OrderedDict()  # key -> Analysis, least recently used first
_INFLIGHT: dict = {}  # key -> Future of the pipeline run another thread is doing
_LOCK = threading.Lock()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _check(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise AnalysisError(f"File not found: {path}")
    if p.suffix.lower() in _UNSUPPORTED:
        raise AnalysisError(f"{p.name} is a {p.suffix} file. Xlens reads .xlsx only; save it as .xlsx and try again.")
    if not zipfile.is_zipfile(p):
        raise AnalysisError(f"{p.name} could not be read as .xlsx. It may be password-protected or corrupt; "
                            "remove the password or re-save it as .xlsx.")
    return p


def run_pipeline(path: str) -> Analysis:
    p = _check(path)
    try:
        cells, ctx = extract_cells(str(p))
    except Exception as exc:  # openpyxl raises many types for bad files
        raise AnalysisError(f"{p.name} could not be read as .xlsx ({type(exc).__name__}).") from exc
    graph, stats = build_graph(cells, named_range_map=ctx.get("named_range_map"))
    formula_count, dist = 0, {}
    for cd in cells.values():
        cls = cd.get("classification", "unknown")
        dist[cls] = dist.get(cls, 0) + 1
        formula_count += bool(cd.get("formula"))
    sheet_names = list(ctx.get("sheet_roles", {}))
    results = {
        "metadata": {"model_name": p.stem, "display_name": p.stem.replace(" - ", " -- "),
                     "property_name": _extract_property_name(cells), "date_analyzed": datetime.now().strftime("%Y-%m-%d %H:%M"),
                     "source_file": str(p), "sheet_count": len(sheet_names), "sheet_names": sheet_names,
                     "sheet_roles": ctx.get("sheet_roles", {})},
        "cells": cells,
        "cells_summary": {"total": len(cells), "formula_count": formula_count, "classification_dist": dist},
        "graph_stats": stats,
        "graph_json": export_graph_json(graph),
        "assumptions": analyze_assumptions(cells, graph),
        "hardcodes": detect_hardcodes(cells, graph),
        "kpis": identify_kpis(cells, graph),
        "flow_blocks": build_flow(cells, graph),
        "complexity": score_complexity(cells, graph),
        "pro_forma": {},
    }
    return Analysis(path=str(p), cells=cells, graph=graph, context=ctx, results=results)


def load(path: str) -> Analysis:
    p = _check(path)
    st = p.stat()
    key = (os.path.realpath(p), st.st_mtime_ns, st.st_size)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
        fut = _INFLIGHT.get(key)
        owner = fut is None
        if owner:
            fut = _INFLIGHT[key] = Future()
    if not owner:
        return fut.result()  # another thread is running this pipeline: wait for it (re-raises its error)
    try:
        a = run_pipeline(str(p))
    except BaseException as exc:
        with _LOCK:
            _INFLIGHT.pop(key, None)
        fut.set_exception(exc)
        raise
    with _LOCK:
        for k in [k for k in _CACHE if k[0] == key[0]]:  # an older version of this file
            del _CACHE[k]
        _CACHE[key] = a
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
        _INFLIGHT.pop(key, None)
    fut.set_result(a)
    return a

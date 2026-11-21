"""Compute a composite complexity score for an Excel model's dependency graph.

Produces a 0-100 score from 8 graph-theoretic and formula-based metrics,
plus a letter grade (A-F), critical path, and bottleneck cells.
"""

import random
from typing import Any

import networkx as nx

# ---------------------------------------------------------------------------
# Metric weights (sum to 1.0)
# ---------------------------------------------------------------------------
_WEIGHTS = {
    "critical_path": 0.15,
    "avg_path_length": 0.10,
    "cross_sheet_ratio": 0.15,
    "max_fan_in": 0.10,
    "max_fan_out": 0.10,
    "cyclomatic": 0.15,
    "formula_complexity": 0.10,
    "unique_formula_ratio": 0.15,
}

# Grade thresholds (upper-bound inclusive)
_GRADES = [(20, "A"), (40, "B"), (60, "C"), (80, "D"), (100, "F")]


def score_complexity(cells: dict, graph: nx.DiGraph) -> dict:
    """Score the structural complexity of an Excel model.

    Parameters
    ----------
    cells : dict
        Cell data keyed by ``(sheet_name, cell_ref)`` tuples.
    graph : nx.DiGraph
        Dependency graph where edges go from dependency to dependent.
        Node attributes should include ``sheet``.

    Returns
    -------
    dict with keys:
        score          – int 0-100
        grade          – str one of A, B, C, D, F
        metrics        – dict of metric dicts each with ``raw`` and ``normalized``
        critical_path  – list[str] node IDs on the longest DAG path
        bottleneck_cells – list[dict] top-5 by betweenness centrality
    """
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()

    # Count formulas — zero-formula files are data tables, not models
    formula_count = sum(
        1 for c in cells.values()
        if c.get("formula") and str(c["formula"]).startswith("=")
    )
    if formula_count == 0:
        return {
            "score": 0,
            "grade": "A",
            "model_type": "data_table",
            "metrics": {name: {"raw": 0, "normalized": 0.0} for name in _WEIGHTS},
            "critical_path": [],
            "bottleneck_cells": [],
        }

    # Detect if graph is a DAG
    is_dag = nx.is_directed_acyclic_graph(graph) if n_nodes > 0 else True

    metrics: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 1. DAG critical path length
    # ------------------------------------------------------------------
    if is_dag and n_edges > 0:
        try:
            crit_path_len = nx.dag_longest_path_length(graph)
        except (nx.NetworkXError, nx.NetworkXUnfeasible):
            crit_path_len = 0
    else:
        crit_path_len = 0
    metrics["critical_path"] = {
        "raw": crit_path_len,
        "normalized": min(crit_path_len / 50, 1.0),
    }

    # ------------------------------------------------------------------
    # 2. Average root-to-terminal path length
    # ------------------------------------------------------------------
    avg_path = _avg_root_terminal_path(graph, n_edges)
    metrics["avg_path_length"] = {
        "raw": avg_path,
        "normalized": min(avg_path / 30, 1.0),
    }

    # ------------------------------------------------------------------
    # 3. Cross-sheet edge ratio
    # ------------------------------------------------------------------
    cross_ratio = _cross_sheet_edge_ratio(graph, n_edges)
    metrics["cross_sheet_ratio"] = {
        "raw": cross_ratio,
        "normalized": cross_ratio,
    }

    # ------------------------------------------------------------------
    # 4. Max fan-in
    # ------------------------------------------------------------------
    max_in = max((d for _, d in graph.in_degree()), default=0)
    metrics["max_fan_in"] = {
        "raw": max_in,
        "normalized": min(max_in / 50, 1.0),
    }

    # ------------------------------------------------------------------
    # 5. Max fan-out
    # ------------------------------------------------------------------
    max_out = max((d for _, d in graph.out_degree()), default=0)
    metrics["max_fan_out"] = {
        "raw": max_out,
        "normalized": min(max_out / 100, 1.0),
    }

    # ------------------------------------------------------------------
    # 6. Cyclomatic complexity  (E - N + 2P)
    # ------------------------------------------------------------------
    if n_nodes > 0:
        n_components = nx.number_weakly_connected_components(graph)
        cyclo = n_edges - n_nodes + 2 * n_components
        cyclo = max(cyclo, 0)
    else:
        cyclo = 0
    metrics["cyclomatic"] = {
        "raw": cyclo,
        "normalized": min(cyclo / 500, 1.0),
    }

    # ------------------------------------------------------------------
    # 7. Formula complexity (avg max-paren nesting depth)
    # ------------------------------------------------------------------
    formula_cplx = _avg_formula_nesting(cells)
    metrics["formula_complexity"] = {
        "raw": formula_cplx,
        "normalized": min(formula_cplx / 8, 1.0),
    }

    # ------------------------------------------------------------------
    # 8. Unique formula ratio (inverse: high uniqueness = high complexity)
    # ------------------------------------------------------------------
    uniq_ratio = _unique_formula_ratio(cells)
    metrics["unique_formula_ratio"] = {
        "raw": uniq_ratio,
        "normalized": uniq_ratio,
    }

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------
    weighted_sum = sum(
        metrics[name]["normalized"] * weight
        for name, weight in _WEIGHTS.items()
    )
    score = max(0, min(100, round(weighted_sum * 100)))

    grade = "A"
    for threshold, g in _GRADES:
        if score <= threshold:
            grade = g
            break

    # ------------------------------------------------------------------
    # Critical path (list of node IDs)
    # ------------------------------------------------------------------
    if is_dag and n_edges > 0:
        try:
            critical_path = nx.dag_longest_path(graph)
        except (nx.NetworkXError, nx.NetworkXUnfeasible):
            critical_path = []
    else:
        critical_path = []

    # ------------------------------------------------------------------
    # Bottleneck cells (top-5 by betweenness centrality)
    # ------------------------------------------------------------------
    bottleneck_cells = _top_bottlenecks(graph, k=5)

    # Classify model type by formula density
    formula_ratio = formula_count / max(n_nodes, 1)
    if formula_ratio > 0.3:
        model_type = "financial_model"
    elif formula_ratio > 0.05:
        model_type = "mixed"
    else:
        model_type = "light_formulas"

    return {
        "score": score,
        "grade": grade,
        "model_type": model_type,
        "metrics": metrics,
        "critical_path": critical_path,
        "bottleneck_cells": bottleneck_cells,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _avg_root_terminal_path(graph: nx.DiGraph, n_edges: int) -> float:
    """Sample up to 100 root->terminal pairs and return avg shortest path."""
    if n_edges == 0:
        return 0.0

    roots = [n for n, d in graph.in_degree() if d == 0 and graph.out_degree(n) > 0]
    terminals = [n for n, d in graph.out_degree() if d == 0 and graph.in_degree(n) > 0]

    if not roots or not terminals:
        return 0.0

    # Sample pairs
    pairs = [(r, t) for r in roots for t in terminals]
    if len(pairs) > 100:
        random.seed(42)
        pairs = random.sample(pairs, 100)

    lengths = []
    for r, t in pairs:
        try:
            length = nx.shortest_path_length(graph, r, t)
            lengths.append(length)
        except nx.NetworkXNoPath:
            continue

    return sum(lengths) / len(lengths) if lengths else 0.0


def _cross_sheet_edge_ratio(graph: nx.DiGraph, n_edges: int) -> float:
    """Fraction of edges crossing sheet boundaries."""
    if n_edges == 0:
        return 0.0

    cross = 0
    for u, v in graph.edges():
        sheet_u = graph.nodes[u].get("sheet", "")
        sheet_v = graph.nodes[v].get("sheet", "")
        if sheet_u != sheet_v:
            cross += 1

    return cross / n_edges


def _avg_formula_nesting(cells: dict) -> float:
    """Average max-parenthesis nesting depth across formula cells."""
    depths = []
    for cell_data in cells.values():
        formula = cell_data.get("formula") if isinstance(cell_data, dict) else None
        if not formula:
            continue
        max_depth = 0
        current = 0
        for ch in formula:
            if ch == "(":
                current += 1
                if current > max_depth:
                    max_depth = current
            elif ch == ")":
                current -= 1
        depths.append(max_depth)

    return sum(depths) / len(depths) if depths else 0.0


def _unique_formula_ratio(cells: dict) -> float:
    """Ratio of distinct formula strings to total formula count."""
    formulas = []
    for cell_data in cells.values():
        formula = cell_data.get("formula") if isinstance(cell_data, dict) else None
        if formula:
            formulas.append(formula)

    if not formulas:
        return 0.0

    return len(set(formulas)) / len(formulas)


def _top_bottlenecks(graph: nx.DiGraph, k: int = 5) -> list[dict]:
    """Return top-k nodes by betweenness centrality."""
    if graph.number_of_nodes() < 2 or graph.number_of_edges() == 0:
        return []

    sample_k = min(100, graph.number_of_nodes())
    centrality = nx.betweenness_centrality(graph, k=sample_k)

    sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
    return [
        {"node": node, "centrality": round(cent, 6)}
        for node, cent in sorted_nodes[:k]
        if cent > 0
    ]

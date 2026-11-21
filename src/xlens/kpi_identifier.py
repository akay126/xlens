"""Identify key performance indicators (KPIs) from the model."""

import re

import networkx as nx

_KPI_KEYWORDS = re.compile(
    r"NOI|Net Operating Income|DSCR|Debt Service Coverage|"
    r"Cash[\s-]*on[\s-]*Cash|IRR|Internal Rate|"
    r"Equity Multiple|Net\s*Proceeds|"
    r"Cumulative\s*Cash\s*Flow|Cumulative\s*CF|"
    r"Cap\s*Rate|Total\s*Return|Profit",
    re.IGNORECASE,
)


def identify_kpis(cells: dict, graph: nx.DiGraph) -> list:
    """Identify KPIs using terminal node analysis and label matching.

    Returns list of dicts: name, cell_ref, value, formula, chain_depth,
    upstream_count, top_assumptions.
    """
    kpis = {}  # grouped by (name, sheet, row)

    out_degrees = dict(graph.out_degree())
    in_degrees = dict(graph.in_degree())

    # Strategy 1: Terminal formula nodes that also match KPI keywords
    # (pure terminal-node strategy produces too many false positives from
    # year-by-year cash flow rows in IRR tables)
    terminal_kpis = set()
    for node_id, out_deg in out_degrees.items():
        if out_deg == 0 and in_degrees.get(node_id, 0) > 0:
            data = graph.nodes[node_id]
            if data.get("formula"):
                label = data.get("row_label", "")
                if _KPI_KEYWORDS.search(label):
                    terminal_kpis.add(node_id)

    # Strategy 2: Label matching on all formula cells
    label_matched = set()
    for (sheet, coord), cell_data in cells.items():
        label = cell_data.get("row_label", "")
        if _KPI_KEYWORDS.search(label) and cell_data.get("formula"):
            label_matched.add(f"{sheet}!{coord}")

    # Merge candidates
    candidates = terminal_kpis | label_matched

    # Filter: skip IRR helper rows (Year 0-10 cash flow entries, individual
    # amortization years, etc.)  These have labels like "Year 1", "1", "2" etc.
    _SKIP_LABELS = re.compile(
        r"^(Year\s+\d+|\d{1,2}|Total|---.*|Note:.*)$", re.IGNORECASE
    )

    for node_id in sorted(candidates, key=_node_sort_key):
        data = graph.nodes.get(node_id, {})
        if not data:
            continue

        sheet = data.get("sheet", "")
        coord = data.get("cell_ref", "")
        formula = data.get("formula", "")
        cached = data.get("cached_value")
        label = data.get("row_label", "").strip()

        if not label or _SKIP_LABELS.match(label):
            continue

        # Skip Sources & Uses summary rows (not KPIs)
        if any(kw in label.lower() for kw in ["total sources", "total uses",
                "closing costs", "acquisition fee", "purchase price",
                "assumed loan", "equity required", "price per"]):
            continue

        # For label-matched but non-terminal nodes, only keep the last year
        # (rightmost column) to avoid 10 copies of the same KPI
        # Pick the cell with the highest column number for this row label + sheet

        # Compute upstream count (lightweight - no path enumeration yet)
        try:
            ancestors = nx.ancestors(graph, node_id)
        except nx.NetworkXError:
            ancestors = set()

        # Determine KPI display name
        kpi_name = _clean_kpi_name(label)

        # Group the same KPI on the same row (one cell per scenario / year column)
        row_key = (kpi_name, sheet, int("".join(c for c in coord if c.isdigit()) or 0))
        group = kpis.setdefault(row_key, {"name": kpi_name, "sheet": sheet, "cells": [],
                                          "_ancestor_count": 0})
        group["cells"].append({"cell_ref": node_id, "coord": coord,
                               "value": cached, "formula": formula})
        group["_ancestor_count"] = max(group["_ancestor_count"], len(ancestors))

    # Keep one row group per KPI name: most ancestors, ties by position
    best = {}
    for group in kpis.values():
        key = _node_sort_key(group["cells"][0]["cell_ref"])
        cur = best.get(group["name"])
        if cur is None or (-group["_ancestor_count"], key) < (
                -cur["_ancestor_count"], _node_sort_key(cur["cells"][0]["cell_ref"])):
            best[group["name"]] = group

    # Now compute expensive metrics only for deduplicated KPIs
    result = []
    for kpi_data in best.values():
        cells_in_row = kpi_data["cells"]
        headers = [_column_header(cells, kpi_data["sheet"], c["coord"]) for c in cells_in_row]
        primary = cells_in_row[-1] if all(_is_year_header(h) for h in headers) else cells_in_row[0]
        node_id = primary["cell_ref"]
        try:
            ancestors = nx.ancestors(graph, node_id)
        except nx.NetworkXError:
            ancestors = set()
        ancestors = sorted(ancestors, key=_node_sort_key)

        # Find assumption nodes in ancestors
        assumption_nodes = []
        for anc in ancestors:
            anc_data = graph.nodes.get(anc, {})
            cls = anc_data.get("classification", "")
            if cls in ("deal_input", "structural_assumption"):
                assumption_nodes.append(anc)

        # Chain depth: estimate from longest shortest path from roots
        chain_depth = 0
        roots_checked = 0
        for anc in ancestors:
            if in_degrees.get(anc, 0) == 0:
                roots_checked += 1
                try:
                    sp = nx.shortest_path_length(graph, anc, node_id)
                    chain_depth = max(chain_depth, sp)
                except nx.NetworkXError:
                    pass
                if roots_checked >= 20:
                    break

        # Top assumptions by out-degree (impact proxy, avoids expensive path enum)
        assumption_impact = {}
        for anc in assumption_nodes:
            anc_label = graph.nodes[anc].get("row_label", anc)
            assumption_impact[anc_label] = out_degrees.get(anc, 0)

        top_assumptions = sorted(assumption_impact.items(), key=lambda x: (-x[1], x[0]))[:5]

        formatted_value = _format_kpi_value(kpi_data["name"], primary["value"])
        scenarios = [
            {"cell_ref": c["cell_ref"], "header": h, "value": c["value"],
             "formatted_value": _format_kpi_value(kpi_data["name"], c["value"])}
            for c, h in zip(cells_in_row, headers, strict=False)
        ]

        result.append({
            "name": kpi_data["name"],
            "cell_ref": node_id,
            "value": primary["value"],
            "formatted_value": formatted_value,
            "formula": primary["formula"],
            "chain_depth": chain_depth,
            "upstream_count": len(ancestors),
            "top_assumptions": top_assumptions,
            "sheet": kpi_data["sheet"],
            "scenarios": scenarios,
        })

    result.sort(key=lambda k: (-k["upstream_count"], k["name"]))
    return result


def _node_sort_key(node_id: str):
    sheet, _, coord = node_id.partition("!")
    col = "".join(ch for ch in coord if ch.isalpha())
    row = int("".join(ch for ch in coord if ch.isdigit()) or 0)
    return (sheet, row, len(col), col)


_YEAR_HEADER = re.compile(r"^(year|yr)\s*\d+", re.IGNORECASE)


def _is_year_header(header: str) -> bool:
    return bool(_YEAR_HEADER.match(header)) or header.isdigit()


def _column_header(cells: dict, sheet: str, coord: str) -> str:
    """First non-empty text cell above `coord` in the same column (up to 30 rows)."""
    col = "".join(ch for ch in coord if ch.isalpha())
    row = int("".join(ch for ch in coord if ch.isdigit()) or 0)
    for r in range(row - 1, max(0, row - 30), -1):
        cd = cells.get((sheet, f"{col}{r}"))
        if not cd or cd.get("formula"):
            continue
        v = cd.get("raw_value")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and 1900 <= v <= 2100:
            return str(int(v))
    return col


def _clean_kpi_name(label: str) -> str:
    """Clean up a KPI label for display."""
    # Remove leading whitespace, dashes, numbering
    name = label.strip().lstrip("-").strip()
    return name


def _format_kpi_value(name: str, value) -> str:
    """Format a KPI value for display based on its type."""
    if value is None:
        return "N/A"

    name_lower = name.lower()

    if isinstance(value, str):
        return value

    if not isinstance(value, (int, float)):
        return str(value)

    # Percentages: IRR, Cash-on-Cash, DSCR (displayed as ratio), Cap Rate
    if any(kw in name_lower for kw in ["irr", "cash-on-cash", "cash on cash", "cap rate"]):
        return f"{value:.1%}" if abs(value) < 10 else f"{value:.2f}"

    if "dscr" in name_lower or "coverage" in name_lower:
        return f"{value:.2f}x"

    if "multiple" in name_lower:
        return f"{value:.2f}x"

    # Currency
    if isinstance(value, float) and abs(value) > 100:
        return f"${value:,.0f}"
    if isinstance(value, int):
        return f"${value:,}"

    return f"{value:,.2f}"

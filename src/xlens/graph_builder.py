"""Build a networkx dependency graph from extracted cells."""

import json

import networkx as nx

from xlens.formula_parser import extract_references, resolve_named_ranges


def build_graph(cells: dict, named_range_map: dict = None) -> tuple:
    """Build a directed dependency graph from cells.

    Nodes are "Sheet!Cell" strings. Edges go from dependency -> dependent.
    Returns (DiGraph, stats_dict).

    Args:
        cells: Dict keyed by (sheet, coord) from extract_cells.
        named_range_map: Optional dict from build_named_range_map for resolving
            named range references to cell refs.
    """
    G = nx.DiGraph()

    # Add all cells as nodes
    for (sheet, coord), cell_data in cells.items():
        node_id = f"{sheet}!{coord}"
        G.add_node(
            node_id,
            sheet=sheet,
            cell_ref=coord,
            value=cell_data.get("raw_value"),
            formula=cell_data.get("formula"),
            classification=cell_data.get("classification"),
            cached_value=cell_data.get("cached_value"),
            row_label=cell_data.get("row_label", ""),
        )

    # Add edges based on formula references
    all_warnings = []

    for (sheet, coord), cell_data in cells.items():
        formula = cell_data.get("formula")
        if not formula:
            continue

        target_node = f"{sheet}!{coord}"
        cell_refs, named_refs, warnings = extract_references(formula, sheet)
        all_warnings.extend(warnings)

        # Resolve named ranges if map provided
        if named_refs and named_range_map:
            resolved = resolve_named_ranges(named_refs, named_range_map, sheet)
            cell_refs = cell_refs | resolved

        for ref_sheet, ref_coord in cell_refs:
            source_node = f"{ref_sheet}!{ref_coord}"
            # Add source node even if not in cells (handles references to empty cells)
            if not G.has_node(source_node):
                G.add_node(source_node, sheet=ref_sheet, cell_ref=ref_coord,
                           value=None, formula=None, classification="external_ref",
                           cached_value=None, row_label="")
            G.add_edge(source_node, target_node)

    # Detect cycles
    cycles = []
    circular_ref_cells = set()

    if nx.is_directed_acyclic_graph(G):
        # Fast path: no cycles
        pass
    else:
        # Enumerate cycles, limit to 100 to prevent hangs
        cycle_count = 0
        for cycle in nx.simple_cycles(G):
            cycles.append({"cycle": list(cycle), "length": len(cycle)})
            circular_ref_cells.update(cycle)
            cycle_count += 1
            if cycle_count >= 100:
                break

    # Compute stats
    in_degrees = dict(G.in_degree())
    out_degrees = dict(G.out_degree())

    root_nodes = [n for n, d in in_degrees.items() if d == 0 and out_degrees.get(n, 0) > 0]
    terminal_nodes = [n for n, d in out_degrees.items() if d == 0 and in_degrees.get(n, 0) > 0]

    hub_nodes = sorted(out_degrees.items(), key=lambda x: x[1], reverse=True)[:10]

    stats = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "root_nodes": root_nodes,
        "terminal_nodes": terminal_nodes,
        "hub_nodes": hub_nodes,
        "root_count": len(root_nodes),
        "terminal_count": len(terminal_nodes),
        "circular_references": cycles,
        "has_circular_refs": len(cycles) > 0,
        "circular_ref_count": len(cycles),
        "circular_ref_cells": sorted(circular_ref_cells),
        "parser_warnings": all_warnings,
    }

    return G, stats


def export_graph_json(G: nx.DiGraph) -> str:
    """Export graph as JSON string in node-link format for the interactive visualization.

    Returns a JSON string with {nodes: [...], links: [...]} structure.
    Each node has: id, sheet, cell_ref, value, formula, classification, row_label, out_degree, in_degree.
    Each link has: source, target.
    """
    nodes = []
    for node_id, data in G.nodes(data=True):
        val = data.get("value")
        cached = data.get("cached_value")
        # Use cached_value for display if available
        display_val = cached if cached is not None else val
        # Truncate long values
        if isinstance(display_val, str) and len(display_val) > 60:
            display_val = display_val[:57] + "..."
        nodes.append({
            "id": node_id,
            "sheet": data.get("sheet", ""),
            "cell_ref": data.get("cell_ref", ""),
            "value": str(display_val) if display_val is not None else "",
            "formula": data.get("formula", "") or "",
            "classification": data.get("classification", ""),
            "row_label": data.get("row_label", ""),
            "out_degree": G.out_degree(node_id),
            "in_degree": G.in_degree(node_id),
        })

    links = []
    for source, target in G.edges():
        links.append({"source": source, "target": target})

    return json.dumps({"nodes": nodes, "links": links})

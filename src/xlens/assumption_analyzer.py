"""Analyze and categorize assumptions from extracted cells."""

import re

import networkx as nx

# Category patterns for matching row labels
_CATEGORY_PATTERNS = {
    "Property Details": re.compile(
        r"unit|sf|sq\s*ft|year\s*built|reac|hap|bedroom|rentable|type|qct|tax|exempt",
        re.IGNORECASE,
    ),
    "Acquisition": re.compile(
        r"price|purchase|closing|acquisition|per\s+unit|per\s+sf",
        re.IGNORECASE,
    ),
    "Debt Terms": re.compile(
        r"loan|balance|rate|maturity|amort|interest|mortgage|ltv|debt|mip|pmt",
        re.IGNORECASE,
    ),
    "Partnership": re.compile(
        r"split|partner|equity|contribution|gp|lp|share|promote|waterfall",
        re.IGNORECASE,
    ),
    "Growth": re.compile(
        r"escalation|growth|vacancy|reserve|inflation|bump|cpi",
        re.IGNORECASE,
    ),
    "Exit": re.compile(
        r"hold\s*period|disposition|cap\s*rate|exit|reversion",
        re.IGNORECASE,
    ),
}

_DEAL_SPECIFIC_CATEGORIES = {"Property Details", "Acquisition"}


def analyze_assumptions(cells: dict, graph: nx.DiGraph) -> list:
    """Analyze and categorize assumption cells.

    Returns list of dicts with: name, cell_ref, value, category,
    deal_specific, downstream_count, sheet.
    """
    assumptions = []

    for (sheet, coord), cell_data in cells.items():
        classification = cell_data.get("classification", "")
        if classification not in ("deal_input", "structural_assumption"):
            continue

        node_id = f"{sheet}!{coord}"
        # Count downstream dependents
        try:
            descendants = nx.descendants(graph, node_id)
            downstream_count = len(descendants)
        except nx.NetworkXError:
            downstream_count = 0

        # Get name from row label
        name = cell_data.get("row_label", "").strip()
        if not name or name == str(cell_data.get("raw_value")):
            name = f"Cell {coord}"

        # Categorize
        category = _categorize(name, cell_data)

        # Determine value to display
        value = cell_data.get("raw_value")
        if value is None:
            value = cell_data.get("cached_value")

        assumptions.append({
            "name": name,
            "cell_ref": f"{sheet}!{coord}",
            "value": value,
            "category": category,
            "classification": classification,
            "deal_specific": category in _DEAL_SPECIFIC_CATEGORIES,
            "downstream_count": downstream_count,
            "sheet": sheet,
        })

    # Sort by category then downstream impact
    assumptions.sort(key=lambda a: (a["category"], -a["downstream_count"]))

    return assumptions


def _categorize(name: str, cell_data: dict) -> str:
    """Categorize an assumption by its label."""
    for category, pattern in _CATEGORY_PATTERNS.items():
        if pattern.search(name):
            return category
    return "Other"

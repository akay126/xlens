"""Detect hardcoded values in calculation sheets."""

import re

import networkx as nx

# Embedded constants in formulas that are meaningful business values
_EMBEDDED_CONST_PATTERN = re.compile(
    r"[\*\/\+\-](\d+\.?\d*)"
)
_TRIVIAL_CONSTANTS = {0, 1, -1, 12, 100}  # identity, months, percentage base


def detect_hardcodes(cells: dict, graph: nx.DiGraph) -> list:
    """Detect hardcoded values and embedded constants in calculation sheets.

    Returns list of dicts: cell_ref, value, label_context, severity,
    recommendation, sheet, source_type.
    """
    flagged = []

    # 1. Hardcoded numeric cells in calculation sheets
    for (sheet, coord), cell_data in cells.items():
        if cell_data.get("sheet_role") != "calc":
            continue
        if cell_data.get("formula"):
            continue

        raw = cell_data.get("raw_value")
        if not isinstance(raw, (int, float)):
            continue

        row = cell_data.get("row", 0)
        col = cell_data.get("col", 0)

        # Skip headers (row <=3) and label column (col 1)
        if row <= 3 or col == 1:
            continue

        label = cell_data.get("row_label", "").strip()
        severity = _determine_severity(cell_data, cells, sheet)

        recommendation = _recommend(severity, label, raw)

        flagged.append({
            "cell_ref": f"{sheet}!{coord}",
            "value": raw,
            "label_context": label,
            "severity": severity,
            "recommendation": recommendation,
            "sheet": sheet,
            "source_type": "hardcoded_cell",
        })

    # 2. Embedded constants in formulas
    for (sheet, coord), cell_data in cells.items():
        if cell_data.get("sheet_role") != "calc":
            continue
        formula = cell_data.get("formula")
        if not formula:
            continue

        embedded = _find_embedded_constants(formula)
        for const_val, context in embedded:
            label = cell_data.get("row_label", "").strip()
            severity = "warning"
            if 0.01 <= const_val <= 0.99:
                severity = "error"  # Looks like a rate - should be an assumption

            flagged.append({
                "cell_ref": f"{sheet}!{coord}",
                "value": const_val,
                "label_context": label,
                "severity": severity,
                "recommendation": f"Move constant {const_val} to Assumptions sheet ({context})",
                "sheet": sheet,
                "source_type": "embedded_constant",
            })

    # Sort: errors first, then warnings, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    flagged.sort(key=lambda f: (severity_order.get(f["severity"], 3), f["sheet"]))

    return flagged


def _determine_severity(cell_data: dict, cells: dict, sheet: str) -> str:
    """Determine hardcode severity level."""
    col = cell_data.get("col", 0)
    row = cell_data.get("row", 0)
    label = cell_data.get("row_label", "").strip()

    # Base-year seed values: first data column (B or C)
    if col <= 3:
        return "info"

    # Check if adjacent cells are formulas (suggesting this should be too)
    has_formula_neighbor = False
    for (s, _c), cd in cells.items():
        if s == sheet and cd.get("row") == row and cd.get("col") != col:
            if cd.get("formula"):
                has_formula_neighbor = True
                break

    if has_formula_neighbor:
        return "warning"

    # No label context = magic number
    if not label:
        return "error"

    return "warning"


def _recommend(severity: str, label: str, value) -> str:
    """Generate a recommendation for a hardcoded value."""
    if severity == "info":
        return f"Base-year seed value for '{label}' - acceptable if intentional"
    if severity == "error":
        return f"Magic number {value} has no label context - move to Assumptions or add documentation"
    return "Consider moving to Assumptions sheet and referencing with formula"


def _find_embedded_constants(formula: str) -> list:
    """Find meaningful embedded numeric constants in a formula."""
    results = []

    # Match numeric literals that are multiplied, divided, etc.
    for m in re.finditer(r"(?:[\*\/])(\d+\.?\d*)", formula):
        try:
            val = float(m.group(1))
        except ValueError:
            continue

        if val in _TRIVIAL_CONSTANTS:
            continue

        # Check if it's a meaningful business constant
        if 0.001 <= val <= 0.99:
            results.append((val, "embedded rate in formula"))
        elif val > 1 and val not in _TRIVIAL_CONSTANTS:
            # Skip common divisors that are structural
            if val in {12, 100, 1000, 10000}:
                continue
            results.append((val, "embedded constant in formula"))

    return results

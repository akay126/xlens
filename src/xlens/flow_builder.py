"""Build an ordered model flow from the dependency graph, for any workbook layout."""
import re

import networkx as nx

# Categories are matched first-hit in this order, so specific ones precede broad ones
# (e.g. "Net Operating Income" must be checked before Revenue's "income").
_CATEGORIES = [
    ("Net Operating Income", re.compile(r"\bnoi\b|\bnet operating income\b|\breserves?\b", re.I)),
    ("Cash Flow", re.compile(r"\bcash flows?\b|\bcf\b|\bdistributions?\b|\bafter debt\b", re.I)),
    ("Revenue", re.compile(r"\brents?\b|\brevenues?\b|\bincome\b|\bvacancy\b|\bgross\b|\begi\b|\bloss to lease\b", re.I)),
    ("Debt Service", re.compile(r"\bdebt\b|\bloans?\b|\binterest\b|\bprincipal\b|\bamort|\bmortgage\b|\bdscr\b|\bbalance\b|\bpayments?\b", re.I)),
    ("Operating Expenses", re.compile(r"\bexpenses?\b|\bopex\b|\butilit|\binsurance\b|\btaxes\b|\btax\b|\bpayroll\b|\bpersonnel\b|\brepairs?\b|\bmaint|\bmanagement\b|\badmin", re.I)),
    ("Exit", re.compile(r"\bexit\b|\bsale\b|\breversion\b|\bdisposition\b|\bcap rate\b|\bterminal\b", re.I)),
    ("Returns", re.compile(r"\birr\b|\bmultiple\b|\bprofit\b|\breturns?\b|\bequity\b|\bnpv\b|\bcash[- ]on[- ]cash\b", re.I)),
]
# Display order: upstream first.
_ORDER = ["Inputs", "Revenue", "Operating Expenses", "Net Operating Income", "Debt Service",
          "Cash Flow", "Exit", "Returns", "Other"]


def _category(cell_data: dict) -> str:
    if cell_data.get("sheet_role") == "input":
        return "Inputs"
    label = cell_data.get("row_label", "") or ""
    for name, rx in _CATEGORIES:
        if rx.search(label):
            return name
    return "Other"


def build_flow(cells: dict, graph: nx.DiGraph) -> list:
    """Group cells into blocks by category, order them upstream-first, link them by real edges.

    Returns the same dict shape as before: name, sheet, description, key_formulas,
    driving_assumptions, connects_to, cell_count, formula_count.
    """
    groups: dict = {}
    for key, cd in cells.items():
        if cd.get("classification") in ("metadata", "label"):
            continue
        groups.setdefault(_category(cd), {})[key] = cd
    block_of = {f"{s}!{c}": name for name, members in groups.items() for (s, c) in members}

    links: dict = {name: set() for name in groups}
    for u, v in graph.edges():
        bu, bv = block_of.get(u), block_of.get(v)
        if bu and bv and bu != bv:
            links[bu].add(bv)

    input_sheets = frozenset(
        s for (s, _), cd in cells.items() if cd.get("sheet_role") == "input"
    )
    blocks = []
    for name in sorted(groups, key=_ORDER.index):
        members = groups[name]
        sheets = sorted({s for s, _ in members})
        labels = []
        for _, cd in sorted(members.items(), key=lambda kv: (kv[0][0], kv[1].get("row", 0))):
            lbl = (cd.get("row_label") or "").strip()
            if lbl and lbl not in labels:
                labels.append(lbl)
        noun = "row" if len(labels) == 1 else "rows"
        shown = ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")
        blocks.append({
            "name": name,
            "sheet": ", ".join(sheets),
            "description": f"{len(labels)} {noun} on {', '.join(sheets)}: {shown}." if labels else f"Cells on {', '.join(sheets)}.",
            "key_formulas": _extract_key_formulas(members, input_sheets),
            "driving_assumptions": _find_driving_assumptions(members, graph),
            "connects_to": sorted(links[name], key=_ORDER.index),
            "cell_count": len(members),
            "formula_count": sum(1 for c in members.values() if c.get("formula")),
        })
    return blocks


def _extract_key_formulas(block_cells: dict, input_sheets: frozenset = frozenset()) -> list:
    """Extract up to 3 representative formulas, translated to readable form."""
    formulas = []

    for (s, coord), cell_data in block_cells.items():
        f = cell_data.get("formula")
        if not f:
            continue
        label = cell_data.get("row_label", "").strip()
        readable = _formula_to_readable(f, label, input_sheets)
        formulas.append({
            "cell": f"{s}!{coord}",
            "label": label,
            "formula": f,
            "readable": readable,
        })

    # Pick diverse formulas: prefer ones with cross-sheet refs and different rows
    seen_rows = set()
    selected = []
    # Prioritize formulas with cross-sheet references
    formulas.sort(key=lambda x: ("!" not in x["formula"], x["cell"]))

    for f in formulas:
        row = f["cell"].split("!")[1] if "!" in f["cell"] else ""
        # Extract row number
        row_num = "".join(c for c in row if c.isdigit())
        if row_num in seen_rows and len(selected) >= 1:
            continue
        seen_rows.add(row_num)
        selected.append(f)
        if len(selected) >= 3:
            break

    return selected


def _refs_input(f: str, input_sheets) -> bool:
    return any(f"{n}!" in f or f"'{n}'!" in f for n in input_sheets)


def _formula_to_readable(formula: str, label: str, input_sheets=frozenset()) -> str:
    """Translate an Excel formula to a more readable description."""
    f = formula.lstrip("=")
    from_inputs = _refs_input(f, input_sheets)

    # Common patterns
    if f.startswith("ROUND(") and "*(1+" in f:
        return f"{label} = prior year * (1 + growth rate)"

    if f.startswith("-") and "*" in f and from_inputs:
        return f"{label} = -(base * assumption rate)"

    if "SUM(" in f:
        return f"{label} = sum of components"

    if f.count("+") >= 2 and "!" not in f:
        return f"{label} = sum of line items"

    if "/" in f and from_inputs:
        return f"{label} = value / assumption"

    if "*" in f and from_inputs:
        return f"{label} = value * assumption rate"

    if "-" in f and f.count("-") == 1 and "!" not in f:
        return f"{label} = income - expenses"

    if "PMT(" in f:
        return f"{label} = mortgage payment calculation"

    if "IRR(" in f:
        return f"{label} = internal rate of return on cash flows"

    if "FV(" in f:
        return f"{label} = future value (remaining balance)"

    if "CUMIPMT(" in f:
        return f"{label} = cumulative interest for period"

    if "CUMPRINC(" in f:
        return f"{label} = cumulative principal for period"

    if "IFERROR(" in f:
        return f"{label} = calculated with error handling"

    return f"{label} = {f[:60]}"


def _find_driving_assumptions(block_cells: dict, graph: nx.DiGraph) -> list:
    """Find assumption nodes that drive this block."""
    assumption_names = set()

    for (sheet, coord), _cell_data in block_cells.items():
        node_id = f"{sheet}!{coord}"
        if not graph.has_node(node_id):
            continue

        # Look at predecessors (direct inputs to this block)
        try:
            for pred in nx.ancestors(graph, node_id):
                pred_data = graph.nodes.get(pred, {})
                cls = pred_data.get("classification", "")
                if cls in ("deal_input", "structural_assumption"):
                    label = pred_data.get("row_label", pred).strip()
                    if label:
                        assumption_names.add(label)
        except nx.NetworkXError:
            pass

    return sorted(assumption_names)[:8]  # Limit to top 8

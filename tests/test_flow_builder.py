import networkx as nx
import pytest

import xlens.flow_builder as fb
from xlens.extractor import extract_cells
from xlens.flow_builder import build_flow
from xlens.graph_builder import build_graph


def _flow(path):
    cells, ctx = extract_cells(str(path))
    g, _ = build_graph(cells, named_range_map=ctx["named_range_map"])
    return build_flow(cells, g)


def test_blocks_follow_model_order(models):
    names = [b["name"] for b in _flow(models["sample"])]
    assert names.index("Inputs") < names.index("Revenue") < names.index("Net Operating Income")
    assert names.index("Net Operating Income") < names.index("Debt Service") < names.index("Returns")


def test_block_shape_unchanged(models):
    b = _flow(models["sample"])[0]
    assert set(b) >= {"name", "sheet", "description", "key_formulas", "driving_assumptions",
                      "connects_to", "cell_count", "formula_count"}


def test_connects_to_uses_real_edges(models):
    blocks = {b["name"]: b for b in _flow(models["sample"])}
    assert "Net Operating Income" in blocks["Revenue"]["connects_to"]


def test_no_sheet_name_literals():
    src = open(fb.__file__).read()
    assert "Assumptions!" not in src and "Pro Forma" not in src


def test_readable_is_sheet_name_independent():
    f = "=Inputs!B3*Inputs!B5*12"
    out = fb._formula_to_readable(f, "Rent", frozenset({"Inputs"}))
    assert "assumption" in out
    out2 = fb._formula_to_readable("=Drivers!B3*C4", "Rent", frozenset({"Drivers"}))
    assert "assumption" in out2
    assert "assumption" not in fb._formula_to_readable(f, "Rent", frozenset())


def test_readable_via_sample_model(models):
    blocks = _flow(models["sample"])
    assert all(isinstance(k["readable"], str) for b in blocks for k in b["key_formulas"])


@pytest.mark.parametrize("label,expected", [
    ("Current Assets", "Other"),
    ("Wholesale Value", "Other"),
    ("Syntax Notes", "Other"),
    ("Irrigation", "Other"),
    ("Parent Entity", "Other"),
    ("Interest Expense", "Debt Service"),
    ("Net Operating Income", "Net Operating Income"),
    ("Effective Gross Income", "Revenue"),
    ("Cash Flow After Debt Service", "Cash Flow"),
    ("DSCR", "Debt Service"),
    ("Equity Multiple", "Returns"),
    ("Exit Cap Rate", "Exit"),
])
def test_category(label, expected):
    assert fb._category({"row_label": label, "sheet_role": "calc"}) == expected


def test_order_covers_all_categories():
    names = {n for n, _ in fb._CATEGORIES} | {"Inputs", "Other"}
    assert names <= set(fb._ORDER)


def test_connects_to_names_existing_blocks(models):
    blocks = _flow(models["sample"])
    names = {b["name"] for b in blocks}
    for b in blocks:
        assert set(b["connects_to"]) <= names


def test_singular_description():
    cells = {("S", "A1"): {"row_label": "Rent", "row": 1, "sheet_role": "calc",
                           "classification": "calc", "formula": None}}
    d = build_flow(cells, nx.DiGraph())[0]["description"]
    assert d.startswith("1 row on")

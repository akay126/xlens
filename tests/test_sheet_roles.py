from xlens.extractor import extract_cells
from xlens.graph_builder import build_graph
from xlens.hardcode_detector import detect_hardcodes
from xlens.sheet_roles import classify_sheets


def _cell(formula=None, raw=1.0):
    return {"formula": formula, "raw_value": raw}


def test_name_hint_makes_input():
    roles = classify_sheets({"Deal Inputs": [_cell(formula="=1+1")] * 5, "Calc": [_cell(formula="=A1")] * 5})
    assert roles == {"Deal Inputs": "input", "Calc": "calc"}


def test_mostly_constants_makes_input():
    sheet = [_cell(raw=v) for v in range(10)] + [_cell(formula="=B1")]
    assert classify_sheets({"Drivers2": sheet}) == {"Drivers2": "input"}


def test_sample_model_roles(models):
    cells, ctx = extract_cells(str(models["sample"]))
    assert ctx["sheet_roles"] == {"Inputs": "input", "Cash Flow": "calc", "Returns": "calc"}
    assert list(ctx["sheet_roles"]) == ["Inputs", "Cash Flow", "Returns"]
    assert cells[("Inputs", "B4")]["classification"] == "deal_input"
    assert cells[("Inputs", "B4")]["sheet_role"] == "input"


def test_hardcode_found_without_sheet_names(models):
    cells, ctx = extract_cells(str(models["sample"]))
    g, _ = build_graph(cells, named_range_map=ctx["named_range_map"])
    refs = {h["cell_ref"] for h in detect_hardcodes(cells, g)}
    assert "Cash Flow!F9" in refs

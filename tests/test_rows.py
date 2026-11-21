import json
import subprocess
import sys
from pathlib import Path

import networkx as nx
import openpyxl
import pytest

from xlens.analysis import Analysis, load
from xlens.rows import row_model, split_ref


def test_rows_fold_columns(models):
    rm = row_model(load(str(models["sample"])))
    noi = rm.rows[rm.row_of["Cash Flow!C11"]]
    assert noi.label == "Net Operating Income"
    assert noi.cells == ("Cash Flow!C11", "Cash Flow!D11", "Cash Flow!E11", "Cash Flow!F11", "Cash Flow!G11")
    assert noi.headers == ("Year 1", "Year 2", "Year 3", "Year 4", "Year 5")
    assert rm.row_of["Cash Flow!C7"] in noi.pre and rm.row_of["Cash Flow!C12"] not in noi.pre


def test_rolls_forward_flag(models):
    rm = row_model(load(str(models["sample"])))
    assert rm.rows[rm.row_of["Cash Flow!D5"]].rolls is True  # D5 = C5*(1+g)


def test_row_model_is_memoised(models):
    a = load(str(models["sample"]))
    assert row_model(a) is row_model(a)


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("ref,expected", [
    ("S!$C$11", ("S", 11, 3, "C")),
    ("S!AA10", ("S", 10, 27, "AA")),
    ("S!Rate", ("S", 0, 0, "Rate")),
    ("S!A1:B2", ("S", 0, 0, "A1:B2")),
])
def test_split_ref(ref, expected):
    assert split_ref(ref) == expected


def test_isolated_constant_excluded(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"], ws["B1"] = "Rent", 100
    ws["A2"], ws["B2"] = "Double", "=B1*2"
    ws["A5"], ws["B5"] = "Unused", 7
    path = tmp_path / "m.xlsx"
    wb.save(path)
    from xlens.analysis import load
    rm = row_model(load(str(path)))
    assert "S!1" in rm.rows and "S!2" in rm.rows and "S!5" not in rm.rows
    assert "S!B5" not in rm.row_of


def test_non_a1_node_gets_unique_cell_key():
    g = nx.DiGraph()
    g.add_node("S!B1", row_label="Base")
    g.add_node("S!Rate", row_label="")
    g.add_node("S!Other", row_label="")
    g.add_edge("S!B1", "S!Rate")
    g.add_edge("S!B1", "S!Other")
    a = Analysis(path="x", cells={}, graph=g, context={}, results={"metadata": {"sheet_names": ["S"]}})
    rm = row_model(a)
    assert rm.row_of["S!Rate"] == "cell:S!Rate"
    assert rm.row_of["S!Other"] == "cell:S!Other"
    assert rm.rows["cell:S!Rate"].headers == ("",)
    assert rm.rows["cell:S!Rate"].label == "S!Rate"
    assert rm.rows["S!1"].suc == ("cell:S!Other", "cell:S!Rate")


def test_rolls_only_for_earlier_columns_of_same_row():
    g = nx.DiGraph()
    g.add_edge("S!B1", "S!A1")  # later column feeding earlier one: not a roll
    g.add_edge("S!B2", "S!C2")
    a = Analysis(path="x", cells={}, graph=g, context={}, results={"metadata": {"sheet_names": ["S"]}})
    rm = row_model(a)
    assert rm.rows["S!1"].rolls is False and rm.rows["S!2"].rolls is True


def test_label_is_first_non_empty_across_cells():
    g = nx.DiGraph()
    g.add_node("S!B1", row_label="")
    g.add_node("S!C1", row_label="Revenue")
    g.add_edge("S!B1", "S!C1")
    a = Analysis(path="x", cells={}, graph=g, context={}, results={"metadata": {"sheet_names": ["S"]}})
    assert row_model(a).rows["S!1"].label == "Revenue"


def test_links_deterministic_across_hash_seeds(models):
    code = (
        "import json,sys;from xlens.analysis import load;from xlens.rows import row_model;"
        "rm=row_model(load(sys.argv[1]));"
        "print(json.dumps({k:[list(r.pre),list(r.suc)] for k,r in rm.rows.items()}))"
    )
    outs = []
    for seed in ("1", "2", "3"):
        r = subprocess.run([sys.executable, "-c", code, str(models["sample"])], cwd=ROOT, check=True,
                           capture_output=True, text=True, env={**__import__("os").environ, "PYTHONHASHSEED": seed})
        outs.append(json.loads(r.stdout))
    assert outs[0] == outs[1] == outs[2] and outs[0]

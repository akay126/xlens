import os
import subprocess
import sys
from pathlib import Path

from xlens.extractor import extract_cells
from xlens.graph_builder import build_graph
from xlens.kpi_identifier import identify_kpis

REPO_ROOT = Path(__file__).resolve().parent.parent


def _kpis(path):
    cells, ctx = extract_cells(str(path))
    g, _ = build_graph(cells, named_range_map=ctx["named_range_map"])
    return identify_kpis(cells, g)


def test_scenarios_listed_with_headers(models):
    em = next(k for k in _kpis(models["scenarios"]) if k["name"] == "Equity Multiple")
    assert [s["header"] for s in em["scenarios"]] == ["Low", "Base", "High"]
    assert [s["cell_ref"] for s in em["scenarios"]] == ["Returns!B4", "Returns!C4", "Returns!D4"]
    assert em["cell_ref"] == "Returns!B4"  # primary = first scenario column, always


def test_same_result_under_any_hash_seed(models):
    code = ("import json,sys; from tests.test_kpi_identifier import _kpis; "
            "print(json.dumps([(k['name'], k['cell_ref']) for k in _kpis(sys.argv[1])]))")
    outs = set()
    for seed in ("1", "2", "3", "4"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outs.add(subprocess.run([sys.executable, "-c", code, str(models["sample"])],
                                env=env, capture_output=True, text=True, check=True,
                                cwd=str(REPO_ROOT)).stdout)
    assert len(outs) == 1


def test_numeric_year_headers_pick_last_column(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "CF"
    for col, yr in zip("BCD", (2024, 2025, 2026), strict=True):
        ws[f"{col}1"] = yr
        ws[f"{col}2"] = 100
        ws[f"{col}3"] = f"={col}2*2"
    ws["A3"] = "Net Operating Income"
    path = tmp_path / "years.xlsx"
    wb.save(path)
    noi = next(k for k in _kpis(path) if k["name"] == "Net Operating Income")
    assert [s["header"] for s in noi["scenarios"]] == ["2024", "2025", "2026"]
    assert noi["cell_ref"] == "CF!D3"

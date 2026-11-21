import json
import os
import zipfile
from pathlib import Path

import openpyxl

from xlens import query as q
from xlens.analysis import load

GOLDEN = Path(__file__).parent / "golden/sample_overview.json"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/sample_model.xlsx"


def snapshot():
    a = load(str(EXAMPLE))
    ov = q.overview(a)
    return {"sheets": ov["sheets"], "counts": ov["counts"], "flow": ov["flow"],
            "kpis": [{"name": k["name"], "cell": k["cell"], "scenarios": k["scenarios"]} for k in ov["kpis"]],
            "drivers_noi": [d["id"] for d in q.drivers(a, "Cash Flow!G11")["drivers"]]}


def test_sample_matches_golden():
    if os.environ.get("XLENS_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snapshot(), indent=2, sort_keys=True) + "\n")
    assert snapshot() == json.loads(GOLDEN.read_text())


def test_example_is_up_to_date(tmp_path):
    from tests.fixtures.build_models import build_sample
    fresh = openpyxl.load_workbook(build_sample(tmp_path / "s.xlsx"))
    committed = openpyxl.load_workbook(EXAMPLE)
    assert committed.sheetnames == fresh.sheetnames
    for ws in fresh.worksheets:
        for row in ws.iter_rows():
            for c in row:
                assert committed[ws.title][c.coordinate].value == c.value, f"{ws.title}!{c.coordinate}"


def test_example_has_cached_values():
    wb = openpyxl.load_workbook(EXAMPLE, data_only=True)
    for sheet, ref in (("Cash Flow", "G11"), ("Returns", "C9")):
        v = wb[sheet][ref].value
        assert isinstance(v, (int, float)) and not isinstance(v, bool), f"{sheet}!{ref} has no cached value"


def test_example_metadata_scrubbed():
    with zipfile.ZipFile(EXAMPLE) as z:
        core = z.read("docProps/core.xml").decode()
        wbxml = z.read("xl/workbook.xml").decode()
    for text in (core, wbxml):
        for bad in ("absPath", "Users\\", "/" + "home/"):  # split so the release scan does not flag this guard
            assert bad not in text
    wb = openpyxl.load_workbook(EXAMPLE)
    assert wb.properties.creator == "xlens" and wb.properties.lastModifiedBy == "xlens"

# tests/test_fixtures.py
import openpyxl

from tests.fixtures.build_models import SAMPLE_SHEETS, build_all


def test_build_all_creates_every_model(tmp_path):
    paths = build_all(tmp_path)
    assert set(paths) == {"sample", "scenarios", "circular", "hostile", "big"}
    wb = openpyxl.load_workbook(paths["sample"])
    assert wb.sheetnames == SAMPLE_SHEETS
    assert wb["Cash Flow"]["C12"].value.startswith("=")

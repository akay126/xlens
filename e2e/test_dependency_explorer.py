"""E2E: Row map -> Dig in -> Trace flow in a generated report.

Run with: pytest e2e/ --browser chromium
"""

import subprocess
import sys

import openpyxl
import pytest


def _analyze(xlsx, out):
    subprocess.run(
        [sys.executable, "-c", "import sys; from xlens.cli import main; sys.exit(main())",
         "analyze", str(xlsx), "--output", str(out)],
        check=True, capture_output=True,
    )


@pytest.fixture(scope="module")
def report_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("explorer")
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "Assumptions"
    a["A2"], a["B2"] = "Monthly Rent", 1000
    a["A3"], a["B3"] = "Rent Growth", 0.03
    pf = wb.create_sheet("Pro Forma")
    pf["A5"], pf["C5"], pf["D5"] = "Revenue", "=Assumptions!B2*12", "=C5*(1+Assumptions!B3)"
    pf["A6"], pf["C6"], pf["D6"] = "Net Operating Income", "=C5*0.6", "=D5*0.6"
    xlsx = tmp / "tiny_model.xlsx"
    wb.save(xlsx)
    out = tmp / "report.html"
    _analyze(xlsx, out)
    return out.as_uri()


def test_map_then_trace(page, report_url):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(report_url)

    # Row map draws one box per row: 2 assumption rows + 2 pro forma rows
    page.locator("#xe-root").scroll_into_view_if_needed()
    assert page.locator(".xe-node").count() == 4

    # Find a row by label, then dig in to trace a cell
    page.fill("#xe-q", "Net Operating")
    page.keyboard.press("Enter")
    assert page.locator("#xe-side h5").inner_text() == "Net Operating Income"
    page.click("#xe-side .xe-primary")
    assert page.locator("#xe-trace").is_visible()
    assert page.locator(".xe-ftitle").inner_text() == "Net Operating Income"

    # Walk one step upstream, then back to the map
    page.locator("#xe-upl .xe-gmain").first.click()
    assert page.locator(".xe-ftitle").inner_text() == "Revenue"
    page.click(".xe-back")
    assert page.locator("#xe-map").is_visible()
    assert errors == []


def test_hostile_labels_do_not_run(page, tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws["A2"], ws["B2"] = "</SCRIPT><img src=x onerror=window.__pwned=1>", 5
    ws["A3"], ws["B3"] = "<img src=x onerror=window.__pwned=2><!--<script>", "=B2*2"
    xlsx = tmp_path / "hostile.xlsx"
    wb.save(xlsx)
    out = tmp_path / "hostile.html"
    _analyze(xlsx, out)
    page.goto(out.as_uri())
    page.wait_for_timeout(500)
    assert page.evaluate("window.__pwned") is None
    assert page.locator(".xe-node").count() == 2  # explorer still renders after the hostile labels


def test_dblclick_and_column_pick(page, report_url):
    page.goto(report_url)
    page.locator("#xe-root").scroll_into_view_if_needed()
    node = page.locator(".xe-node", has_text="Revenue")
    node.dblclick()
    assert page.locator("#xe-trace").is_visible()
    assert "D5" in page.locator(".xe-ftop").inner_text()
    # jump to the first year column from the focus card
    page.locator(".xe-focus .xe-gcells button", has_text="C5").click()
    assert "C5" in page.locator(".xe-ftop").inner_text()


def test_plain_scroll_scrolls_page_ctrl_scroll_zooms(page, report_url):
    page.goto(report_url)
    stage = page.locator("#xe-stage")
    stage.scroll_into_view_if_needed()
    box = stage.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    before = page.get_attribute("#xe-g", "transform")
    y0 = page.evaluate("window.scrollY")
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(200)
    assert page.get_attribute("#xe-g", "transform") == before
    assert page.evaluate("window.scrollY") > y0
    stage.scroll_into_view_if_needed()
    box = stage.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.keyboard.down("Control")
    page.mouse.wheel(0, -200)
    page.keyboard.up("Control")
    page.wait_for_timeout(200)
    assert page.get_attribute("#xe-g", "transform") != before


def test_large_model_falls_back_to_trace(page, tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws["A1"], ws["B1"] = "Seed", 1
    for r in range(2, 1302):
        ws.cell(row=r, column=1, value=f"Step {r}")
        ws.cell(row=r, column=2, value=f"=B{r - 1}+1")
    xlsx = tmp_path / "big.xlsx"
    wb.save(xlsx)
    out = tmp_path / "big.html"
    _analyze(xlsx, out)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(out.as_uri())
    page.wait_for_timeout(800)
    assert page.locator(".xe-tab[data-view=map]").is_disabled()
    assert page.locator("#xe-trace").is_visible()
    page.fill("#xe-q", "Calc!B700")
    page.keyboard.press("Enter")
    assert "B700" in page.locator(".xe-ftop").inner_text()
    assert errors == []

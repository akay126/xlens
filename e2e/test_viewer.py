"""E2E: the Viewer's live map tab (and the inline MCP App page opened top-level, with no host)."""

import openpyxl
import pytest
from playwright.sync_api import expect

from tests.fixtures.build_models import build_big, build_hostile, build_sample
from xlens.analysis import load
from xlens.viewer.page import render_page
from xlens.viewer.payload import build_payload
from xlens.viewer.server import Viewer


def _viewer(path):
    v = Viewer(page_html=lambda: render_page(None, mode="tab"))
    v.start()
    v.set_model(build_payload(load(str(path))))
    return v


@pytest.fixture
def viewer(tmp_path):
    v = _viewer(build_sample(tmp_path / "s.xlsx"))
    yield v
    v.stop()


@pytest.fixture
def errors(page):
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    return errs


def test_map_follows_focus(page, viewer, errors):
    page.goto(viewer.url)
    page.wait_for_selector(".xe-node")
    viewer.publish({"mode": "trace", "focus": ["Cash Flow!C11", "Cash Flow!C7"]})
    page.wait_for_selector(".xe-ftitle")
    assert page.locator(".xe-ftitle").inner_text() == "Net Operating Income"
    # the other focused cell is highlighted among the inputs it feeds
    assert page.locator("#xe-upl .xe-group.xe-ai").count() >= 1
    assert errors == []


def test_kpi_strip_and_markers(page, viewer, errors):
    page.goto(viewer.url)
    page.wait_for_selector(".xe-kpis")
    assert "Low" in page.locator(".xe-kpis").inner_text()
    assert page.locator(".xe-node.xe-flag").count() >= 1
    assert errors == []


def test_token_kept_across_reload(page, viewer):
    page.goto(viewer.url)
    page.wait_for_selector(".xe-node")
    page.reload()
    page.wait_for_selector(".xe-node")
    assert page.evaluate("location.search") == f"?k={viewer.token}"
    # the stream reconnects after the reload
    viewer.publish({"mode": "show", "focus": ["Cash Flow!G13"]})
    page.wait_for_selector(".xe-node.xe-ai")
    assert page.locator("#xe-side h5").inner_text() == "Cash Flow After Debt Service"


def test_prototype_ids_in_focus_are_ignored(page, viewer, errors):
    page.goto(viewer.url)
    page.wait_for_selector(".xe-node")
    viewer.publish({"mode": "show", "focus": ["Cash Flow!C11"]})
    expect(page.locator("#xe-side h5")).to_have_text("Net Operating Income")
    for mode in ("show", "trace"):
        viewer.publish({"mode": mode, "focus": ["constructor", "__proto__", "toString", "hasOwnProperty"]})
        page.wait_for_timeout(300)
        assert page.locator("#xe-map").is_visible()
        assert page.locator("#xe-side h5").inner_text() == "Net Operating Income"
        assert page.locator(".xe-node.xe-ai").count() == 0
    assert errors == []


def test_prototype_named_workbook_text(page, tmp_path, errors):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "__proto__"
    ws["A2"], ws["B2"] = "constructor", 5
    ws["A3"], ws["B3"] = "__proto__", "=B2*2"
    ws["A4"], ws["B4"] = "toString", "=B3+1"
    path = tmp_path / "proto.xlsx"
    wb.save(path)
    v = _viewer(path)
    try:
        page.goto(v.url)
        expect(page.locator(".xe-node")).to_have_count(3)
        v.publish({"mode": "trace", "focus": ["__proto__!B3"]})
        expect(page.locator(".xe-ftitle")).to_have_text("__proto__")
        page.fill("#xe-q", "constructor")
        page.keyboard.press("Enter")
        expect(page.locator(".xe-ftitle")).to_have_text("constructor")
        assert errors == []
    finally:
        v.stop()


def test_focus_before_load_is_applied(page, viewer):
    viewer.publish({"mode": "trace", "focus": ["Returns!C9"]})  # replayed on connect, maybe before /model.json
    page.goto(viewer.url)
    page.wait_for_selector(".xe-ftitle")
    assert page.locator(".xe-ftitle").inner_text() == "Equity Multiple"
    assert "C9" in page.locator(".xe-ftop").inner_text()


def test_model_reload_keeps_working(page, viewer, tmp_path):
    page.goto(viewer.url)
    page.wait_for_selector(".xe-node")
    viewer.set_model(build_payload(load(str(build_hostile(tmp_path / "h.xlsx")))))
    expect(page.locator(".xe-node")).to_have_count(2)  # (wait_for_function would need eval, which the CSP blocks)
    assert page.evaluate("window.__pwned") is None
    assert page.locator(".xe-kpis").count() <= 1


def test_kpi_click_digs_in(page, viewer):
    page.goto(viewer.url)
    page.wait_for_selector(".xe-kpis")
    page.locator(".xe-kpis button", has_text="High").first.click()
    assert page.locator("#xe-trace").is_visible()
    assert "D9" in page.locator(".xe-ftop").inner_text() or "D8" in page.locator(".xe-ftop").inner_text()


def test_ask_button_copies_question(page, viewer):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(viewer.url)
    page.wait_for_selector(".xe-node")
    viewer.publish({"mode": "show", "focus": ["Cash Flow!C11"]})
    page.wait_for_selector("#xe-side .xe-ask")
    page.click("#xe-side .xe-ask")
    expect(page.locator("#xe-side .xe-ask")).not_to_have_text("Copy question")
    label = page.locator("#xe-side .xe-ask").inner_text()
    text = page.evaluate("navigator.clipboard.readText()") if label == "Copied" else page.input_value(".xe-askbox")
    assert text == 'Explain Cash Flow!C11:G11 (row "Net Operating Income") in this model.'


def test_big_model_tab_falls_back_to_trace(page, tmp_path, errors):
    v = _viewer(build_big(tmp_path / "big.xlsx"))
    try:
        page.goto(v.url)
        page.wait_for_selector("#xe-trace:not([hidden])")
        assert page.locator(".xe-tab[data-view=map]").is_disabled()
        v.publish({"mode": "show", "focus": ["Calc!B700"]})
        expect(page.locator(".xe-ftop")).to_contain_text("B700")
        assert errors == []
    finally:
        v.stop()


def test_inline_page_without_host(page, tmp_path, errors):
    html = render_page(build_payload(load(str(build_sample(tmp_path / "s.xlsx")))), mode="inline")
    f = tmp_path / "inline.html"
    f.write_text(html, encoding="utf-8")
    page.goto(f.as_uri())
    page.wait_for_selector(".xe-node")
    assert page.locator("#xe-title").inner_text() == "s"
    assert page.locator(".xe-kpis").count() == 1
    assert errors == []


def test_hostile_kpi_and_finding_text_is_escaped(page, viewer, errors, tmp_path):
    bad = "<img src=x onerror=window.__pwned=1>"
    p = build_payload(load(str(build_hostile(tmp_path / "h.xlsx"))))
    cell = p["nodes"][0]["id"]
    p["model"] = bad
    p["kpis"] = [{"name": bad, "cell": cell, "display": bad,
                  "scenarios": [{"cell": cell, "header": bad, "display": bad}]}]
    p["findings"] = [{"cell": cell, "kind": bad, "severity": bad}]
    viewer.set_model(p)
    page.goto(viewer.url)
    page.wait_for_selector(".xe-kpis")
    page.locator(".xe-node.xe-flag").first.click()
    page.wait_for_selector("#xe-side .xe-flags")
    page.locator(".xe-kpis .xe-kname").click()
    page.wait_for_selector(".xe-ftitle")
    assert page.locator("#xe-root img").count() == 0
    assert page.locator("#xe-title").inner_text() == bad
    assert page.evaluate("window.__pwned") is None
    assert errors == []

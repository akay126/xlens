import json

import pytest

from xlens import query as q
from xlens.analysis import load


@pytest.fixture
def a(models):
    return load(str(models["sample"]))


def test_overview(a):
    o = q.overview(a)
    assert o["sheets"] == [{"name": "Inputs", "role": "input"}, {"name": "Cash Flow", "role": "calc"},
                           {"name": "Returns", "role": "calc"}]
    em = next(k for k in o["kpis"] if k["name"] == "Equity Multiple")
    assert [s["header"] for s in em["scenarios"]] == ["Low", "Base", "High"]
    assert any(f["cell"] == "Cash Flow!F9" for f in o["top_findings"])
    assert o["mode"] == "overview"


def test_trace_up_groups_by_row(a):
    t = q.trace(a, "'cash flow'!$c$11", direction="up", depth=1)
    assert t["cell"]["id"] == "Cash Flow!C11"
    assert t["cell"]["formula"] == "=C7-C9"
    labels = [g["label"] for g in t["upstream"]]
    assert labels == ["Effective Gross Income", "Operating Expenses"]
    assert "downstream" not in t


def test_trace_unknown_cell_suggests(a):
    with pytest.raises(q.CellNotFound) as e:
        q.trace(a, "Cash Flow!Z99")
    assert "Cash Flow!C11" in str(e.value) or "Did you mean" in str(e.value)


def test_trace_bad_direction(a):
    with pytest.raises(ValueError):
        q.trace(a, "Cash Flow!C11", direction="sideways")


def test_find_by_label_and_ref(a):
    assert q.find(a, "net operating")["matches"][0]["label"] == "Net Operating Income"
    assert q.find(a, "Inputs!B4")["matches"][0]["id"] == "Inputs!B4"


def test_drivers_ranked(a):
    d = q.drivers(a, "Returns!C9")
    ids = [x["id"] for x in d["drivers"]]
    assert "Inputs!B14" in ids and "Inputs!B13" not in ids  # base cap only, not low
    assert d["drivers"] == sorted(d["drivers"], key=lambda x: (-x["paths"], x["id"]))


def test_findings_kinds(models):
    assert q.findings(load(str(models["circular"])), "circular")["items"]
    assert all(i["kind"] == "hardcode" for i in q.findings(load(str(models["sample"])), "hardcodes")["items"])
    with pytest.raises(ValueError):
        q.findings(load(str(models["sample"])), "nonsense")


def test_show_dedupes(a):
    s = q.show(a, ["Cash Flow!C11", "'cash flow'!c11"])
    assert s["focus"] == ["Cash Flow!C11"] and s["mode"] == "show"


def test_deterministic(a):
    for fn in (lambda: q.overview(a), lambda: q.trace(a, "Returns!C9", "both", 3),
               lambda: q.drivers(a, "Returns!C9"), lambda: q.findings(a)):
        assert json.dumps(fn()) == json.dumps(fn())


def test_size_cap(models):
    t = q.trace(load(str(models["big"])), "Calc!B1300", direction="up", depth=5)
    assert len(json.dumps(t)) <= q.MAX_BYTES
    b = q.trace(load(str(models["big"])), "Calc!B650", direction="both", depth=5)
    assert len(json.dumps(b)) <= q.MAX_BYTES


def test_labels_are_data_not_markup(models):
    o = q.find(load(str(models["hostile"])), "SCRIPT")
    assert o["matches"][0]["label"].startswith("</SCRIPT>")  # returned verbatim as data


def test_drivers_exact_on_chain(models):
    d = q.drivers(load(str(models["big"])), "Calc!B1300")
    assert d["drivers"][0]["id"] == "Calc!B1" and d["drivers"][0]["paths"] == 1


def test_drivers_dense_grid_is_fast_and_capped(tmp_path):
    import time

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Grid"
    width, depth = 4, 30
    for c in range(1, width + 1):
        ws.cell(row=1, column=c, value=c)
    for r in range(2, depth + 2):
        for c in range(1, width + 1):
            refs = "+".join(f"{openpyxl.utils.get_column_letter(k)}{r - 1}" for k in range(1, width + 1))
            ws.cell(row=r, column=c, value=f"={refs}")
    ws.cell(row=depth + 3, column=1, value=f"=A{depth + 1}")
    p = tmp_path / "grid.xlsx"
    wb.save(p)
    a = load(str(p))
    t0 = time.time()
    d = q.drivers(a, f"Grid!A{depth + 3}")
    assert time.time() - t0 < 2
    assert {x["paths"] for x in d["drivers"]} == {q.MAX_PATHS}


def test_drivers_cycle_does_not_hang(models):
    d = q.drivers(load(str(models["circular"])), "Calc!B3")
    assert [x["id"] for x in d["drivers"]] == ["Calc!B1"]


def test_trace_trim_keeps_nearest(a, monkeypatch):
    full = q.trace(a, "Returns!B9", "up", 5)
    assert not full.get("truncated")
    monkeypatch.setattr(q, "MAX_BYTES", len(json.dumps(full)) // 2)
    t = q.trace(a, "Returns!B9", "up", 5)
    assert t["truncated"] and len(json.dumps(t)) <= q.MAX_BYTES
    ids = {c["id"] for g in t["upstream"] for c in g["cells"]}
    assert "Returns!B8" in ids
    assert set(t["focus"]) == {"Returns!B9"} | ids


def test_cap_always_fits(a, monkeypatch):
    monkeypatch.setattr(q, "MAX_BYTES", 600)
    o = q.overview(a)
    assert len(json.dumps(o)) <= 600 and o["truncated"]
    big = {"sheets": [{"name": "x" * 50}] * 500, "flow": [{"n": "y" * 50}] * 500, "focus": ["A!A1"] * 5, "counts": {"a": 1}}
    out = q._cap(big, "sheets", last_resort=("flow",), drop=("counts",))
    assert len(json.dumps(out)) <= q.MAX_BYTES


def test_bare_ref_ambiguous_and_quoted_apostrophe(a, tmp_path):
    with pytest.raises(q.CellNotFound) as e:
        q.resolve(a, "B3")
    assert "ambiguous" in str(e.value) and "!B3" in str(e.value)
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bob's Sheet"
    ws["A1"], ws["B1"] = "x", 2
    ws["B2"] = "=B1*2"
    p = tmp_path / "apos.xlsx"
    wb.save(p)
    assert q.resolve(load(str(p)), "'Bob''s Sheet'!b2") == "Bob's Sheet!B2"


def test_val_nonfinite_and_truncation_flags(a):
    assert q._val(float("nan")) is None and q._val(float("inf")) is None
    a.graph.nodes["Cash Flow!C11"]["row_label"] = "L" * 300
    a.graph.nodes["Cash Flow!C11"]["formula"] = "=" + "C7+" * 100 + "C9"
    c = q._cell(a, "Cash Flow!C11")
    assert c["label_truncated"] and c["formula_truncated"] and len(c["label"]) <= q.MAX_TEXT + 3


def test_findings_focus_follows_trim(models, monkeypatch):
    a = load(str(models["sample"]))
    monkeypatch.setattr(q, "MAX_BYTES", 300)
    f = q.findings(a, "hardcodes")
    assert len(json.dumps(f)) <= 300
    assert set(f["focus"]) <= {i["cell"] for i in f["items"]}


def test_all_fixtures_within_cap(models):
    for m in models.values():
        a = load(str(m))
        for o in (q.overview(a), q.findings(a), q.find(a, "a")):
            assert len(json.dumps(o)) <= q.MAX_BYTES


def test_overview_trim_keeps_kpis_over_sheets_and_flow(a, monkeypatch):
    full = q.overview(a)
    kpis_only = len(json.dumps({"kpis": full["kpis"], "focus": full["focus"], "mode": "overview", "truncated": True,
                                "hint": "x" * 80}))
    monkeypatch.setattr(q, "MAX_BYTES", kpis_only + 200)
    o = q.overview(a)
    assert o["truncated"] and len(json.dumps(o)) <= q.MAX_BYTES
    assert len(o["kpis"]) >= 1
    assert len(o.get("sheets", [])) < len(full["sheets"]) or len(o.get("flow", [])) < len(full["flow"])


def test_trace_group_cell_count_is_full_row(a):
    t = q.trace(a, "Returns!B9", "up", 5)
    from xlens.rows import row_model
    rm = row_model(a)
    for g in t["upstream"]:
        assert g["cell_count"] == len(rm.rows[g["row"]].cells)
        assert g["cell_count"] >= len(g["cells"])
        if len(g["cells"]) < g["cell_count"]:
            assert g["cells_shown"] == len(g["cells"])
        else:
            assert "cells_shown" not in g


def test_trace_cell_count_exceeds_cells_when_trimmed(a, monkeypatch):
    full = q.trace(a, "Cash Flow!C11", "up", 5)
    monkeypatch.setattr(q, "MAX_GROUP_CELLS", 1)
    t = q.trace(a, "Cash Flow!C11", "up", 5)
    assert any(g["cell_count"] > 1 and g["cells_shown"] == 1 for g in t["upstream"] + t.get("downstream", []))
    assert [g["cell_count"] for g in t["upstream"]] == [g["cell_count"] for g in full["upstream"]]


def _labels(a, text):
    return [m.get("label") for m in q.find(a, text)["matches"]]


def test_find_abbreviations_and_tokens(a):
    assert _labels(a, "NOI")[0] == "Net Operating Income"
    assert _labels(a, "operating income")[0] == "Net Operating Income"
    assert "DSCR" in _labels(a, "dscr")
    assert "DSCR" in _labels(a, "debt service coverage")
    assert _labels(a, "CFADS") == ["Cash Flow After Debt Service"]
    cap = _labels(a, "cap rate")
    assert cap and all("Cap Rate" in x for x in cap)
    assert "Exit Cap Rate" in _labels(a, "cap rate exit")
    assert _labels(a, "xyz") == []


def test_find_order_is_workbook_order_and_exact_ref_first(a):
    ms = q.find(a, "Exit Cap Rate")["matches"]
    ids = [m["row"] for m in ms]
    assert ids == sorted(ids, key=lambda r: [x["row"] for x in ms].index(r))
    assert ids[0].startswith("Inputs")
    assert q.find(a, "Inputs!B4")["matches"][0]["id"] == "Inputs!B4"

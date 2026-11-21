import json
import os
import subprocess
import sys

import openpyxl

from xlens.analysis import load
from xlens.viewer.page import render_page
from xlens.viewer.payload import build_payload


def test_payload_fields(models):
    p = build_payload(load(str(models["sample"])))
    assert {"nodes", "links", "kpis", "findings", "model"} <= set(p)
    assert any(f["cell"] == "Cash Flow!F9" for f in p["findings"])


def test_payload_shapes(models):
    p = build_payload(load(str(models["sample"])))
    assert all(n["in_degree"] or n["out_degree"] for n in p["nodes"])
    ids = {n["id"] for n in p["nodes"]}
    assert all(link["source"] in ids and link["target"] in ids for link in p["links"])
    k = next(k for k in p["kpis"] if k["scenarios"] and k["scenarios"][0]["header"] == "Low")
    assert {"name", "cell", "display", "scenarios"} <= set(k)
    assert {"cell", "header", "display"} == set(k["scenarios"][0])
    assert all({"cell", "kind", "severity"} == set(f) for f in p["findings"])


def test_payload_circular_findings_use_first_cell(models):
    p = build_payload(load(str(models["circular"])))
    circ = [f for f in p["findings"] if f["kind"] == "circular"]
    assert circ and all(f["cell"].startswith("Calc!") for f in circ)


def test_payload_deterministic_across_hash_seeds(models):
    code = ("import json,sys; from xlens.analysis import load; from xlens.viewer.payload import build_payload; "
            "sys.stdout.write(json.dumps(build_payload(load(sys.argv[1])), sort_keys=False))")
    outs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outs.append(subprocess.run([sys.executable, "-c", code, str(models["sample"])], env=env,
                                   capture_output=True, text=True, check=True).stdout)
    assert outs[0] == outs[1]


def test_page_escapes_and_embeds(models):
    html = render_page(build_payload(load(str(models["hostile"]))), mode="inline")
    assert "</SCRIPT><img" not in html
    assert "XlensExplorer" in html


def test_page_tab_mode_has_no_data_and_no_external_refs():
    html = render_page(None, mode="tab")
    assert "DATA = null" in html and 'MODE = "tab"' in html
    for bad in ("/*CSS*/", "/*EXPLORER*/", "/*BRIDGE*/", "/*DATA*/", "/*MODE*/"):
        assert bad not in html
    low = html.lower()
    assert "src=\"http" not in low and "@import" not in low and "url(" not in low
    assert "eval(" not in html and "new Function" not in html


def test_placeholder_text_in_workbook_is_not_substituted(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws["A2"], ws["B2"] = "/*MODE*/ /*DATA*/ /*EXPLORER*/ </script>", 5
    ws["A3"], ws["B3"] = "Twice", "=B2*2"
    path = tmp_path / "ph.xlsx"
    wb.save(path)
    payload = build_payload(load(str(path)))
    html = render_page(payload, mode="inline")
    start = html.index("DATA = ") + len("DATA = ")
    end = html.index(", root = document")
    embedded = json.loads(html[start:end])
    assert any(n["row_label"].startswith("/*MODE*/ /*DATA*/") for n in embedded["nodes"])
    assert "</script> " not in html.split("DATA = ", 1)[1].split(", root", 1)[0]

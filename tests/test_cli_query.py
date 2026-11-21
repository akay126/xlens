import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    return subprocess.run([sys.executable, "-m", "xlens.cli", *args], capture_output=True, text=True)


def test_query_trace_json(models):
    r = run("query", "trace", str(models["sample"]), "--cell", "Cash Flow!C11")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["cell"]["id"] == "Cash Flow!C11"


def test_query_error_is_json_and_exit_2(models):
    r = run("query", "trace", str(models["sample"]), "--cell", "Nope!A1")
    assert r.returncode == 2 and "error" in json.loads(r.stdout)


def test_query_missing_cell_is_json_error(models):
    for tool in ("trace", "drivers"):
        r = run("query", tool, str(models["sample"]))
        assert r.returncode == 2 and "--cell" in json.loads(r.stdout)["error"]


def test_query_bad_file_is_json_error(tmp_path):
    r = run("query", "overview", str(tmp_path / "missing.xlsx"))
    assert r.returncode == 2 and "error" in json.loads(r.stdout)


def test_query_find_text(models):
    r = run("query", "find", str(models["sample"]), "--text", "NOI")
    assert r.returncode == 0, r.stderr
    assert isinstance(json.loads(r.stdout), dict)


def test_query_bad_direction_exits_nonzero(models):
    r = run("query", "trace", str(models["sample"]), "--cell", "Cash Flow!C11", "--direction", "sideways")
    assert r.returncode == 2  # argparse rejects it


@pytest.mark.parametrize("extra", [
    ["overview"], ["trace", "--cell", "Cash Flow!C11", "--direction", "both", "--depth", "2"],
    ["find", "--text", "NOI"], ["drivers", "--cell", "Returns!B9"],
    ["findings"], ["findings", "--kind", "hardcodes"],
])
def test_query_every_tool_prints_only_json_on_sample(extra):
    sample = ROOT / "examples" / "sample_model.xlsx"
    if not sample.exists():
        pytest.skip("examples/sample_model.xlsx missing")
    tool, rest = extra[0], extra[1:]
    r = run("query", tool, str(sample), *rest)
    assert r.returncode == 0, r.stderr
    json.loads(r.stdout)  # whole stdout is one JSON document


def test_query_find_without_text_is_json_error(models):
    r = run("query", "find", str(models["sample"]))
    assert r.returncode == 2 and "--text" in json.loads(r.stdout)["error"]


def test_query_find_abbreviation(models):
    r = run("query", "find", str(models["sample"]), "--text", "NOI")
    assert json.loads(r.stdout)["matches"][0]["label"] == "Net Operating Income"

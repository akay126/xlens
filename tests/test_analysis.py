import os
import time

import pytest

from xlens.analysis import AnalysisError, clear_cache, load, run_pipeline


def test_load_caches_until_file_changes(models, tmp_path):
    p = tmp_path / "m.xlsx"
    p.write_bytes(models["sample"].read_bytes())
    clear_cache()
    a1, a2 = load(str(p)), load(str(p))
    assert a1 is a2
    os.utime(p, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert load(str(p)) is not a1


def test_results_shape(models):
    a = run_pipeline(str(models["sample"]))
    assert a.results["metadata"]["sheet_names"] == ["Inputs", "Cash Flow", "Returns"]
    assert a.graph.number_of_nodes() > 0 and a.cells


@pytest.mark.parametrize("name,msg", [("missing.xlsx", "File not found"), ("model.xls", "save it as .xlsx"),
                                      ("model.xlsb", "save it as .xlsx"), ("broken.xlsx", "could not be read")])
def test_clear_errors(tmp_path, name, msg):
    p = tmp_path / name
    if name != "missing.xlsx":
        p.write_bytes(b"not a workbook")
    with pytest.raises(AnalysisError, match=msg):
        load(str(p))


def test_bad_zip_is_wrapped(tmp_path):
    import zipfile
    p = tmp_path / "bad.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(AnalysisError, match="could not be read"):
        load(str(p))


def test_batch_reports_bad_file_without_traceback(models, tmp_path, capsys):
    from types import SimpleNamespace

    from xlens.cli import cmd_batch
    d = tmp_path / "in"
    d.mkdir()
    (d / "good.xlsx").write_bytes(models["sample"].read_bytes())
    (d / "bad.xlsx").write_bytes(b"not a workbook")
    cmd_batch(SimpleNamespace(directory=str(d), output_dir=str(tmp_path / "out")))
    cap = capsys.readouterr()
    assert "FAILED:" in cap.out
    assert "Traceback" not in cap.out + cap.err
    assert "1 succeeded, 1 failed" in cap.out


def test_metadata_has_property_and_display_name(models):
    md = run_pipeline(str(models["sample"])).results["metadata"]
    assert md["property_name"] and md["display_name"] == md["model_name"].replace(" - ", " -- ")


def test_concurrent_loads_run_pipeline_once(models, tmp_path, monkeypatch):
    import threading

    import xlens.analysis as an
    p = tmp_path / "c.xlsx"
    p.write_bytes(models["sample"].read_bytes())
    clear_cache()
    calls, real = [], an.run_pipeline
    def slow(path):
        calls.append(path)
        time.sleep(0.3)  # long enough that every thread arrives while the first run is in flight
        return real(path)
    monkeypatch.setattr(an, "run_pipeline", slow)
    out, errs, start = [], [], threading.Barrier(8)
    def worker():
        try:
            start.wait()
            out.append(load(str(p)))
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errs == [] and len(calls) == 1 and len(out) == 8
    assert all(a is out[0] for a in out)


def test_concurrent_load_failure_reaches_every_waiter(tmp_path, monkeypatch):
    import threading

    import xlens.analysis as an
    p = tmp_path / "f.xlsx"
    import zipfile
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("x.txt", "x")
    clear_cache()
    def boom(path):
        time.sleep(0.2)
        raise AnalysisError("nope")
    monkeypatch.setattr(an, "run_pipeline", boom)
    errs, start = [], threading.Barrier(4)
    def worker():
        start.wait()
        try:
            load(str(p))
        except AnalysisError as exc:
            errs.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(errs) == 4 and an._INFLIGHT == {}


def test_cache_is_lru_of_four(models, tmp_path, monkeypatch):
    import xlens.analysis as an
    clear_cache()
    monkeypatch.setattr(an, "run_pipeline", lambda path: object())
    paths = []
    for i in range(5):
        p = tmp_path / f"m{i}.xlsx"
        p.write_bytes(models["sample"].read_bytes())
        paths.append(str(p))
    first = load(paths[0])
    for p in paths[1:4]:
        load(p)
    assert load(paths[0]) is first  # touch m0: m1 is now the oldest
    load(paths[4])
    assert len(an._CACHE) == an.CACHE_SIZE == 4
    cached = {k[0] for k in an._CACHE}
    assert os.path.realpath(paths[1]) not in cached and os.path.realpath(paths[0]) in cached
    clear_cache()

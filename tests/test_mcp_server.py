import asyncio
import json
import os
import subprocess
import sys
import threading

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOLS = {"analyze_model", "trace", "find", "drivers", "findings", "show"}


def call(models, steps):
    async def go():
        env = {**os.environ, "XLENS_NO_BROWSER": "1"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "xlens.cli", "mcp", "--no-browser"], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await steps(s)
    return asyncio.run(go())


def test_tools_listed_with_ui_on_analyze(models):
    async def steps(s):
        return {t.name: t for t in (await s.list_tools()).tools}
    tools = call(models, steps)
    assert set(tools) == TOOLS
    assert tools["analyze_model"].meta["ui"]["resourceUri"] == "ui://xlens/map.html"
    for t in tools.values():
        assert "path" in t.input_schema["properties"] and "path" in t.input_schema["required"]


def test_analyze_then_trace(models):
    path = str(models["sample"])
    async def steps(s):
        a = await s.call_tool("analyze_model", {"path": path})
        t = await s.call_tool("trace", {"path": path, "cell": "Cash Flow!C11"})
        return a, t
    a, t = call(models, steps)
    ov, tr = json.loads(a.content[0].text), json.loads(t.content[0].text)
    assert ov["model"] == "sample_model" and ov["viewer_url"].startswith("http://127.0.0.1:")
    assert tr["cell"]["id"] == "Cash Flow!C11"
    assert a.structured_content == ov and t.structured_content == tr
    # the map payload goes to the app via _meta only, never into model-visible text
    assert a.meta["xlens/payload"]["nodes"]
    assert "payload" not in ov and '"links"' not in a.content[0].text


def test_ui_resource_served_with_bridge(models):
    async def steps(s):
        return await s.read_resource("ui://xlens/map.html")
    res = call(models, steps)
    html = res.contents[0].text
    assert res.contents[0].mime_type == "text/html;profile=mcp-app"
    assert "ui/initialize" in html and "ui/notifications/tool-result" in html


def test_errors_are_tool_errors(models):
    async def steps(s):
        return await s.call_tool("trace", {"path": str(models["sample"]), "cell": "Nope!A1"})
    res = call(models, steps)
    assert res.is_error and "Nope" in res.content[0].text


def test_every_tool_validates_path(models):
    args = {"analyze_model": {}, "trace": {"cell": "A1"}, "find": {"text": "NOI"}, "drivers": {"cell": "A1"},
            "findings": {}, "show": {"cells": ["A1"]}}
    async def steps(s):
        return {n: await s.call_tool(n, {"path": "no/such/model.xlsx", **extra}) for n, extra in args.items()}
    res = call(models, steps)
    for name, r in res.items():
        assert r.is_error, name
        assert "relative path" in r.content[0].text and "absolute" in r.content[0].text, name
        assert "Traceback" not in r.content[0].text


# -- raw protocol: nothing but JSON-RPC on stdout, no tracebacks on stderr -------------------------

def _rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def _read_until(proc, ids, timeout=60):
    """Read stdout lines (in a thread, so a hung server fails the test) until every id has a response."""
    got, want = [], set(ids)
    def run():
        for line in proc.stdout:
            got.append(line)
            try:
                want.discard(json.loads(line).get("id"))
            except ValueError:
                return  # non-JSON on stdout: stop and let the assertions report it
            if not want:
                return
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"no response for ids {sorted(want)}"
    return got


def test_stdout_is_protocol_only(models):
    env = {**os.environ, "XLENS_NO_BROWSER": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "xlens.cli", "mcp", "--no-browser"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
        first = json.loads(proc.stdout.readline())
        assert first["id"] == 1 and "result" in first
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        path = str(models["sample"])
        _rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "analyze_model", "arguments": {"path": path}}})
        _rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "trace", "arguments": {"path": path, "cell": "Nope!A1"}}})
        lines = [ln for ln in _read_until(proc, {2, 3, 4}) if ln.strip()]
        out, err = proc.communicate(timeout=30)  # closing stdin ends the server
    finally:
        if proc.poll() is None:
            proc.kill()
    lines += [ln for ln in out.splitlines() if ln.strip()]
    msgs = [json.loads(ln) for ln in lines]  # every stdout line must be JSON
    assert all(m.get("jsonrpc") == "2.0" for m in msgs)
    by_id = {m.get("id"): m for m in msgs}
    assert {t["name"] for t in by_id[2]["result"]["tools"]} == TOOLS
    assert by_id[3]["result"]["isError"] is False
    assert by_id[4]["result"]["isError"] is True
    assert "Traceback" not in err
    assert proc.returncode == 0


# -- in-process: viewer failure, unexpected errors, browser gating ---------------------------------

@pytest.fixture
def srv(monkeypatch):
    import xlens.mcp_server as m
    monkeypatch.setattr(m._State, "viewer", None)
    monkeypatch.setattr(m._State, "shown", None)
    monkeypatch.setattr(m._State, "opened", False)
    monkeypatch.setattr(m._State, "open_browser", False)
    monkeypatch.setattr(m._State, "use_viewer", True)
    yield m
    if m._State.viewer is not None:
        m._State.viewer.stop()


def test_viewer_start_failure_keeps_tools_working(srv, models, monkeypatch):
    def boom(self):
        raise OSError("no sockets here")
    monkeypatch.setattr(srv.Viewer, "start", boom)
    res = srv.analyze_model(str(models["sample"]))
    assert not res.is_error
    assert res.structured_content["viewer_url"] is None
    assert "map unavailable" in res.structured_content["note"]
    assert not srv.trace(str(models["sample"]), "Cash Flow!C11").is_error


def test_unexpected_error_message(srv, models, monkeypatch, capsys):
    def broken(a):
        raise RuntimeError("kaput")
    monkeypatch.setattr(srv.q, "overview", broken)
    res = srv.analyze_model(str(models["sample"]))
    assert res.is_error and res.content[0].text == "Unexpected error: RuntimeError: kaput"
    cap = capsys.readouterr()
    assert "Traceback" in cap.err and cap.out == ""


def test_foreign_value_error_is_unexpected(srv, models, monkeypatch, capsys):
    def broken(a):
        raise ValueError("internal slip")
    monkeypatch.setattr(srv.q, "overview", broken)
    res = srv.analyze_model(str(models["sample"]))
    assert res.is_error and res.content[0].text == "Unexpected error: ValueError: internal slip"
    assert "Traceback" in capsys.readouterr().err


def test_own_validation_errors_are_plain(srv, models, capsys):
    res = srv.trace(str(models["sample"]), "Cash Flow!C11", direction="sideways")
    assert res.is_error and res.content[0].text.startswith("direction must")
    res = srv.findings(str(models["sample"]), kind="nope")
    assert res.is_error and res.content[0].text.startswith("kind must")
    assert "Traceback" not in capsys.readouterr().err


def test_user_path_expanded(srv, models, monkeypatch):
    home = models["sample"].parent
    monkeypatch.setenv("HOME", str(home))
    res = srv.find("~/" + models["sample"].name, "NOI")
    assert not res.is_error


def test_browser_opened_once_and_gated(srv, models, monkeypatch):
    opened = []
    monkeypatch.setattr(srv.webbrowser, "open", lambda url, new=0: opened.append(url))
    monkeypatch.setattr(srv._State, "open_browser", True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("XLENS_NO_BROWSER", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    srv.analyze_model(str(models["sample"]))
    srv.analyze_model(str(models["sample"]))
    assert len(opened) == 1
    for env in ({"XLENS_NO_BROWSER": "1"}, {"CI": "true"}):
        with monkeypatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            assert srv._browser_allowed() is False


def test_browser_failure_never_fails_tool(srv, models, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no browser")
    monkeypatch.setattr(srv.webbrowser, "open", boom)
    monkeypatch.setattr(srv._State, "open_browser", True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("XLENS_NO_BROWSER", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    res = srv.analyze_model(str(models["sample"]))
    assert not res.is_error and res.structured_content["viewer_url"]


def test_inline_page_requires_bridge(monkeypatch, tmp_path):
    from xlens.viewer import page
    monkeypatch.setattr(page, "_TEMPLATE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        page.render_page(None, mode="inline")

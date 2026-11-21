import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from xlens.viewer.server import Viewer


@pytest.fixture
def v():
    viewer = Viewer(page_html=lambda: "<html>map</html>")
    viewer.start()
    yield viewer
    viewer.stop()


def get(url):
    return urllib.request.urlopen(url, timeout=5)


def raw(v, method, path, headers=None):
    conn = http.client.HTTPConnection(v.host, v.port, timeout=5)
    conn.request(method, path, headers=headers or {})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


def test_token_required(v):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"http://127.0.0.1:{v.port}/")
    assert e.value.code == 403
    assert get(v.url).read() == b"<html>map</html>"


def test_wrong_token_forbidden(v):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"{v.base}/?k=nope")
    assert e.value.code == 403


def test_binds_loopback_only(v):
    assert v.host == "127.0.0.1" and len(v.token) >= 32
    assert v._httpd.server_address[0] == "127.0.0.1"


def test_non_loopback_host_rejected():
    for bad in ("0.0.0.0", "192.168.1.5", "example.com", ""):
        with pytest.raises(ValueError):
            Viewer(page_html=lambda: "x", host=bad)


@pytest.mark.parametrize("path", ["/model.json", "/events"])
def test_token_required_on_all_routes(v, path):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"{v.base}{path}")
    assert e.value.code == 403


def test_bad_host_on_events_rejected(v):
    resp, _ = raw(v, "GET", f"/events?k={v.token}", {"Host": "evil.example.com"})
    assert resp.status == 403


def test_replay_excludes_model_events(v):
    v.publish({"mode": "trace", "focus": ["S!A1"]})
    v.set_model({"rows": []})
    with get(f"{v.base}/events?k={v.token}") as r:
        for line in r:
            if line.startswith(b"data:"):
                assert json.loads(line[5:])["mode"] == "trace"
                break
        else:
            pytest.fail("no data line")


def wait_for(cond, secs=3.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_subscriber_removed_after_disconnect(v):
    r = get(f"{v.base}/events?k={v.token}")
    assert wait_for(lambda: len(v._subs) == 1)
    r.close()
    assert wait_for(lambda: len(v._subs) == 0)


def test_17th_sse_client_gets_503(v):
    opened = [get(f"{v.base}/events?k={v.token}") for _ in range(16)]
    try:
        assert wait_for(lambda: len(v._subs) == 16)
        with pytest.raises(urllib.error.HTTPError) as e:
            get(f"{v.base}/events?k={v.token}")
        assert e.value.code == 503
    finally:
        for r in opened:
            r.close()


def test_slow_subscriber_dropped_not_blocking(v):
    r = get(f"{v.base}/events?k={v.token}")
    assert wait_for(lambda: len(v._subs) == 1)
    sub = v._subs[0]
    with v._lock:  # simulate a stuck consumer by filling its queue directly
        while not sub.q.full():
            sub.q.put_nowait({"x": 1})
    t0 = time.time()
    v.publish({"mode": "trace"})
    assert time.time() - t0 < 1
    assert wait_for(lambda: len(v._subs) == 0)
    r.close()


def test_publish_stores_copy(v):
    ev = {"mode": "trace", "focus": ["S!A1"]}
    v.publish(ev)
    ev["focus"].append("mutated")
    assert v._last["focus"] == ["S!A1"]


def test_unserialisable_event_does_not_break_stream(v):
    circ = {"mode": "trace"}
    circ["self"] = circ
    v.publish(circ)  # must not raise
    v.publish({"mode": "trace", "ok": 1})
    with get(f"{v.base}/events?k={v.token}") as r:
        for line in r:
            if line.startswith(b"data:"):
                assert json.loads(line[5:])["ok"] == 1
                break


def test_frame_headers(v):
    resp, _ = raw(v, "GET", f"/?k={v.token}")
    assert resp.getheader("X-Frame-Options") == "DENY"
    csp = resp.getheader("Content-Security-Policy")
    assert "frame-ancestors 'none'" in csp and "base-uri 'none'" in csp and "form-action 'none'" in csp


def test_model_and_events(v):
    v.set_model({"rows": [1]})
    assert json.loads(get(f"{v.base}/model.json?k={v.token}").read()) == {"rows": [1]}
    got = []

    def listen():
        with get(f"{v.base}/events?k={v.token}") as r:
            for line in r:
                if line.startswith(b"data:"):
                    got.append(json.loads(line[5:]))
                    return

    t = threading.Thread(target=listen)
    t.start()
    time.sleep(0.3)
    v.publish({"mode": "trace", "focus": ["S!A1"]})
    t.join(5)
    assert got == [{"mode": "trace", "focus": ["S!A1"]}]


def test_unknown_path_404(v):
    resp, _ = raw(v, "GET", f"/nope?k={v.token}")
    assert resp.status == 404


def test_post_is_405(v):
    for method in ("POST", "PUT", "DELETE"):
        resp, _ = raw(v, method, f"/?k={v.token}")
        assert resp.status == 405


def test_bad_host_header_rejected(v):
    resp, _ = raw(v, "GET", f"/?k={v.token}", {"Host": "evil.example.com"})
    assert resp.status == 403
    resp, _ = raw(v, "GET", f"/?k={v.token}", {"Host": f"evil.example.com:{v.port}"})
    assert resp.status == 403
    resp, _ = raw(v, "GET", f"/?k={v.token}", {"Host": f"localhost:{v.port}"})
    assert resp.status == 200
    resp, _ = raw(v, "GET", f"/?k={v.token}", {"Host": f"127.0.0.1:{v.port}"})
    assert resp.status == 200


def test_security_headers(v):
    resp, _ = raw(v, "GET", f"/?k={v.token}")
    assert resp.getheader("Cache-Control") == "no-store"
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    assert resp.getheader("Referrer-Policy") == "no-referrer"
    csp = resp.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert resp.getheader("Access-Control-Allow-Origin") is None
    resp, _ = raw(v, "GET", f"/model.json?k={v.token}")
    assert resp.getheader("Referrer-Policy") == "no-referrer"
    assert resp.getheader("Content-Type") == "application/json"


def test_late_subscriber_gets_last_event(v):
    v.publish({"mode": "trace", "focus": ["S!B2"]})
    with get(f"{v.base}/events?k={v.token}") as r:
        for line in r:
            if line.startswith(b"data:"):
                assert json.loads(line[5:]) == {"mode": "trace", "focus": ["S!B2"]}
                break
        else:
            pytest.fail("no data line arrived")


def test_stop_completes_with_open_stream():
    viewer = Viewer(page_html=lambda: "x")
    viewer.start()
    r = get(f"{viewer.base}/events?k={viewer.token}")
    time.sleep(0.3)
    t0 = time.time()
    viewer.stop()
    assert time.time() - t0 < 2
    r.close()


def test_no_stdout_output(v, capsys):
    get(v.url).read()
    v.publish({"a": 1})
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_ipv6_loopback_url_is_bracketed():
    viewer = Viewer(page_html=lambda: "<html>map</html>", host="::1")
    try:
        viewer.start()
    except OSError:
        pytest.skip("IPv6 loopback is not available here")
    try:
        assert viewer.base == f"http://[::1]:{viewer.port}"
        assert viewer.url.startswith(f"http://[::1]:{viewer.port}/?k=")
        assert get(viewer.url).read() == b"<html>map</html>"
    finally:
        viewer.stop()

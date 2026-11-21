"""Loopback-only HTTP server: serves the map page, the model JSON and an SSE focus stream.

Runs inside the MCP server process, whose stdout carries the protocol, so this module
never writes to stdout and keeps request logging silent.
"""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
_MAX_SUBSCRIBERS = 16
_QUEUE_MAX = 256
_REQUEST_TIMEOUT = 10  # seconds to read a request
_STREAM_WRITE_TIMEOUT = 30  # seconds a stalled SSE client may block a write
_KEEPALIVE_SECS = 15.0
_POLL_SECS = 1.0


class _Sub:
    """One SSE subscriber: a bounded event queue plus a flag set when it is dropped."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self.dead = threading.Event()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, addr, handler):
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, handler)

    def handle_error(self, request, client_address):  # disconnects are routine; stay quiet
        pass


class Viewer:
    def __init__(self, page_html, host: str = "127.0.0.1", port: int = 0):
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(f"viewer must bind a loopback host, got {host!r}")
        self.host, self._port, self.token = host, port, secrets.token_urlsafe(32)
        self._page_html = page_html
        self._model: dict = {}
        self._subs: list[_Sub] = []
        self._lock = threading.Lock()
        self._httpd: _Server | None = None
        self._last: dict | None = None
        self._stopping = threading.Event()

    # -- public API ---------------------------------------------------------
    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def base(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host  # IPv6 literals need brackets in a URL
        return f"http://{host}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.base}/?k={self.token}"

    def start(self) -> None:
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            timeout = _REQUEST_TIMEOUT

            def log_message(self, *a):  # silence: stdout carries MCP
                pass

            def _host_ok(self) -> bool:
                host = self.headers.get("Host", "")
                port = viewer.port
                return host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")

            def _headers(self, ctype: str | None = None) -> None:
                if ctype:
                    self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                if ctype and ctype.startswith("text/html"):
                    self.send_header("Content-Security-Policy", _CSP)

            def _plain(self, code: int, extra: dict | None = None) -> None:
                self.send_response(code)
                self._headers()
                for k, val in (extra or {}).items():
                    self.send_header(k, val)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _send(self, code: int, ctype: str, body: bytes) -> None:
                self.send_response(code)
                self._headers(ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _method_not_allowed(self):
                self._plain(405, {"Allow": "GET"})

            do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _method_not_allowed

            def do_GET(self):
                if not self._host_ok():
                    return self._plain(403)
                u = urlparse(self.path)
                supplied = parse_qs(u.query).get("k", [""])[0]
                if not hmac.compare_digest(supplied.encode(), viewer.token.encode()):
                    return self._plain(403)
                try:
                    if u.path == "/":
                        self._send(200, "text/html; charset=utf-8", viewer._page_html().encode())
                    elif u.path == "/model.json":
                        body = json.dumps(viewer._model, default=str).encode()
                        self._send(200, "application/json", body)
                    elif u.path == "/events":
                        viewer._stream(self)
                    else:
                        self._plain(404)
                except OSError:
                    pass  # client went away
                except Exception:
                    try:
                        self._plain(500)
                    except OSError:
                        pass

        self._stopping.clear()
        self._httpd = _Server((self.host, self._port), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            for sub in self._subs:
                sub.dead.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    def set_model(self, model: dict) -> None:
        self._model = model
        self.publish({"mode": "model"})

    def publish(self, event: dict) -> None:
        try:  # deep copy via JSON so later mutation by the caller can't alter replay
            snap = json.loads(json.dumps(event, default=str))
        except (TypeError, ValueError):
            return  # unserialisable event: drop rather than break the caller
        with self._lock:
            if snap.get("mode") != "model":  # model refreshes are not replayed as focus
                self._last = snap
            for sub in list(self._subs):
                try:
                    sub.q.put_nowait(snap)
                except queue.Full:  # slow consumer: drop it rather than block publish
                    sub.dead.set()
                    self._subs.remove(sub)

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _frame(ev: dict) -> bytes:
        return b"data: " + json.dumps(ev, default=str).encode() + b"\n\n"

    def _stream(self, handler) -> None:
        sub, last = _Sub(), None
        with self._lock:  # subscribe + snapshot atomically so no event is missed or duplicated
            full = len(self._subs) >= _MAX_SUBSCRIBERS
            if not full:
                self._subs.append(sub)
                last = self._last
        if full:  # reply outside the lock: a slow client must not stall publish()
            return handler._plain(503)
        conn = handler.connection
        try:
            handler.send_response(200)
            handler._headers("text/event-stream")
            handler.end_headers()
            conn.settimeout(_STREAM_WRITE_TIMEOUT)  # request read is done; allow a long-lived stream
            if last is not None:
                handler.wfile.write(self._frame(last))
            handler.wfile.flush()
            next_ping = time.monotonic() + _KEEPALIVE_SECS
            while not self._stopping.is_set() and not sub.dead.is_set():
                try:
                    ev = sub.q.get(timeout=_POLL_SECS)
                except queue.Empty:
                    if self._client_gone(conn):
                        break
                    if time.monotonic() >= next_ping:
                        handler.wfile.write(b": keepalive\n\n")
                        handler.wfile.flush()
                        next_ping = time.monotonic() + _KEEPALIVE_SECS
                    continue
                handler.wfile.write(self._frame(ev))
                handler.wfile.flush()
                next_ping = time.monotonic() + _KEEPALIVE_SECS
        except (OSError, TypeError, ValueError):
            pass  # disconnect or unserialisable event: end the stream, never reply again
        finally:
            handler.close_connection = True
            with self._lock:
                if sub in self._subs:
                    self._subs.remove(sub)

    @staticmethod
    def _client_gone(conn) -> bool:
        try:
            if select.select([conn], [], [], 0)[0]:
                return conn.recv(1024) == b""
        except (OSError, ValueError):
            return True
        return False

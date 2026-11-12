"""Serve the offline workbench on this computer's loopback interface."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sqlite3
from threading import RLock
from time import monotonic
from urllib.parse import parse_qs, quote, unquote, urlsplit
import webbrowser

from .catalog import discover
from .web_session import Application


STATIC = Path(__file__).with_name("static")


class WorkbenchHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Instrument polling is routine. Actual operation errors go to the page.
        pass

    def respond(self, status, content, mime, *, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (ConnectionResetError, BrokenPipeError):
            pass

    @staticmethod
    def encode(data):
        return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()

    def payload(self, status, data):
        self.respond(status, self.encode(data), "application/json; charset=utf-8")

    def local_request(self, *, navigation=False):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        top_level = (navigation and self.headers.get("Sec-Fetch-Mode") == "navigate"
                     and self.headers.get("Sec-Fetch-Dest") == "document")
        return (host in {f"127.0.0.1:{port}", f"localhost:{port}"} and
                self.headers.get("Origin", "http://" + host) == "http://" + host and
                (self.headers.get("Sec-Fetch-Site") != "cross-site" or top_level))

    def do_GET(self):
        url = urlsplit(self.path)
        route = unquote(url.path)
        entry = route == "/" or route.startswith(("/lab/", "/experiment/"))
        if not self.local_request(navigation=entry):
            self.payload(403, {"error": "仅限本机工作台访问。"})
            return
        if route.startswith("/api/"):
            try:
                with self.server.app_lock:
                    if route == "/api/catalog":
                        data = self.server.app.catalog(include_history=False)
                    elif route == "/api/state":
                        query = parse_qs(url.query)
                        data = self.server.app.state(**{key: query[key][0] for key in
                                                       ("session", "product_cursor") if key in query})
                    else:
                        self.payload(404, {"error": "未知请求。"})
                        return
                    body = self.encode(data)
                self.respond(200, body, "application/json; charset=utf-8")
            except ValueError as error:
                self.payload(400, {"error": str(error)})
            except (OSError, sqlite3.Error) as error:
                self.payload(500, {"error": str(error)})
            return
        if route == "/" or route.startswith(("/lab/", "/experiment/")):
            route = "/index.html"
        try:
            asset = (STATIC / route.lstrip("/")).resolve()
            if not asset.is_relative_to(STATIC.resolve()) or not asset.is_file():
                self.payload(404, {"error": "找不到资源。"})
                return
            mime = "text/javascript" if asset.suffix == ".js" else mimetypes.guess_type(asset)[0]
            self.respond(200, asset.read_bytes(), mime or "application/octet-stream")
        except (ValueError, OSError) as error:
            self.payload(400, {"error": str(error)})

    def do_POST(self):
        if not self.local_request():
            self.payload(403, {"error": "仅限本机工作台访问。"})
            return
        if self.headers.get_content_type() != "application/json":
            self.payload(415, {"error": "请求必须使用 JSON。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            maximum = 64 * 1024 * 1024 if urlsplit(self.path).path in ("/api/open_package", "/api/replace_package", "/api/inspect_import", "/api/inspect_measurement") else 1024 * 1024
            if not 0 < length <= maximum:
                self.payload(413, {"error": "请求大小无效。"})
                return
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求必须包含 JSON 对象。")
            route = urlsplit(self.path).path
            filename = None
            with self.server.app_lock:
                value = self.server.app.request(route, data)
                if route == "/api/download":
                    filename, mime, body = value
                elif route == "/api/export":
                    mime = "application/json" if data["format"] == "json" else "text/csv"
                    mime += "; charset=utf-8"
                    body = value
                else:
                    mime, body = "application/json; charset=utf-8", self.encode(value)
            self.respond(200, body, mime, filename=filename)
        except (ValueError, KeyError, IndexError, TypeError, OverflowError) as error:
            self.payload(400, {"error": str(error)})
        except (OSError, sqlite3.Error) as error:
            self.payload(500, {"error": str(error)})


def make_server(paths=(), *, port=0, directory=None, clock=monotonic):
    definitions = discover(paths)
    store = Path.home() / ".nuclemu" / "workbench" if directory is None else directory
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkbenchHandler)
    server.app = Application(definitions, store, clock)
    server.app_lock = RLock()
    return server


def launch(paths=(), *, port=0, open_browser=True, directory=None):
    """Open the local workbench and serve it until the user presses Ctrl+C."""
    with make_server(paths, port=port, directory=directory) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Nuclemu · {url}  (Ctrl+C to stop)", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

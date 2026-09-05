"""On-Air / Living Log web prototype (stdlib HTTP + SQLite)."""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from mq_radio.config import DB_PATH
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.living_log.service import list_events, now_and_upcoming

STATIC_DIR = Path(__file__).parent / "static"


def _json_response(handler: BaseHTTPRequestHandler, data, status: int = 200) -> None:
    body = json.dumps(data, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f"[on-air] {self.address_string()} {fmt % args}")

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            log_date = (qs.get("date") or [date.today().isoformat()])[0]

            if path in ("/", "/index.html"):
                html = (STATIC_DIR / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                fp = STATIC_DIR / rel
                if not fp.exists() or not fp.is_file():
                    self.send_error(404)
                    return
                data = fp.read_bytes()
                ctype = "text/css" if fp.suffix == ".css" else "application/javascript"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/api/status":
                data = now_and_upcoming(log_date, db_path=db_path)
                _json_response(self, {"date": log_date, **data})
                return

            if path == "/api/log":
                events = list_events(log_date, db_path=db_path)
                _json_response(self, {"date": log_date, "events": events})
                return

            self.send_error(404)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            log_date = (qs.get("date") or [date.today().isoformat()])[0]
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)

            engine = MockEngine(log_date, db_path=db_path)
            if path == "/api/play":
                st = engine.play()
            elif path == "/api/stop":
                st = engine.stop()
            elif path == "/api/skip":
                engine._running = True
                st = engine.skip()
            elif path == "/api/step":
                st = engine.step()
            else:
                self.send_error(404)
                return
            _json_response(self, {
                "message": st.message,
                "running": st.running,
                "position": st.position,
                "title": st.current_title,
                "artist": st.current_artist,
            })

    return Handler


def run_server(host: str = "127.0.0.1", port: int = 8080, db_path: Optional[Path] = None) -> None:
    db = db_path or DB_PATH
    handler = make_handler(db)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"On-Air prototype at http://{host}:{port}/  (db={db})")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()

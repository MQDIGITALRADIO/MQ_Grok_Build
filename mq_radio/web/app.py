"""On-Air / Living Log web prototype (stdlib HTTP + SQLite)."""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from mq_radio.config import DATA_DIR, DB_PATH
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.living_log.service import list_events, now_and_upcoming
from mq_radio.web.settings_store import load_audio_outputs, save_audio_outputs

def _static_dir() -> Path:
    here = Path(__file__).resolve().parent / "static"
    if here.is_dir():
        return here
    import sys
    me = getattr(sys, "_MEI" + "PASS", None)
    if getattr(sys, "frozen", False) and me:
        bundled = Path(me) / "mq_radio" / "web" / "static"
        if bundled.is_dir():
            return bundled
    return here


STATIC_DIR = _static_dir()


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
                engine = MockEngine(log_date, db_path=db_path)
                engine.finish_if_due()
                data = now_and_upcoming(log_date, db_path=db_path)
                from mq_radio.engine.session import SESSION
                timing = SESSION.timing()
                _json_response(self, {"date": log_date, **data, "timing": timing, "running": SESSION.running})
                return

            if path == "/api/log":
                events = list_events(log_date, db_path=db_path)
                _json_response(self, {"date": log_date, "events": events})
                return

            if path == "/api/settings/audio":
                _json_response(self, load_audio_outputs(DATA_DIR))
                return

            self.send_error(404)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            log_date = (qs.get("date") or [date.today().isoformat()])[0]
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""

            if path == "/api/settings/audio":
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    _json_response(self, {"ok": False, "error": "invalid json"}, status=400)
                    return
                outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else payload
                if not isinstance(outputs, dict):
                    outputs = {}
                result = save_audio_outputs(outputs, DATA_DIR)
                _json_response(self, result)
                return

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

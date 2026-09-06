"""P0: multipart/path ingest + VU idle darkness + playable after play."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.living_log.service import list_library
from mq_radio.web.app import _synthetic_vu, make_handler
from mq_radio.web.multipart import parse_multipart
import mq_radio.config as cfg


@pytest.fixture()
def desk(tmp_path: Path):
    db = tmp_path / "desk.db"
    data = tmp_path / "data"
    data.mkdir()
    init_db(db)
    prev = cfg.DATA_DIR
    cfg.apply_data_dir(data)
    # Re-bind app module DATA_DIR used by some helpers
    import mq_radio.web.app as app_mod
    app_mod.DATA_DIR = data
    yield {"db": db, "data": data}
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev


def _silence_wav(path: Path, seconds: float = 0.4, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def _http_json(method: str, url: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            return resp.status, json.loads(body.decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return e.code, payload


def test_multipart_filename_star_parsed_as_file():
    b = "----BoundSTAR"
    body = b""
    body += f"--{b}\r\n".encode()
    body += b"Content-Disposition: form-data; name=\"file\"; filename*=UTF-8''My%20Hit.mp3\r\n"
    body += b"Content-Type: audio/mpeg\r\n\r\n"
    body += b"ID3" + b"\x00" * 80
    body += b"\r\n"
    body += f"--{b}--\r\n".encode()
    parts = parse_multipart(f"multipart/form-data; boundary={b}", body)
    assert isinstance(parts.get("file"), dict)
    assert parts["file"]["filename"] == "My Hit.mp3"
    assert parts["file"]["data"].startswith(b"ID3")


def test_vu_idle_is_fully_dark():
    vu = _synthetic_vu()
    assert vu["playing"] is False
    assert vu["left"] == 0.0
    assert vu["right"] == 0.0
    assert vu.get("peak_left", 0) == 0.0
    assert vu.get("peak_right", 0) == 0.0


def test_ingest_multipart_and_json_path_then_play(desk, tmp_path: Path):
    db = desk["db"]
    data = desk["data"]
    wav = _silence_wav(tmp_path / "import_me.wav", seconds=0.5)

    Handler = make_handler(db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"

    try:
        # Multipart Browse-style
        boundary = "----WebKitFormBoundaryMQ"
        raw = wav.read_bytes()
        body = b""
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="file"; filename="Air Cart.wav"\r\n'
        body += b"Content-Type: audio/wav\r\n\r\n"
        body += raw + b"\r\n"
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="title"\r\n\r\n'
        body += b"Air Cart\r\n"
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="artist"\r\n\r\n'
        body += b"Studio\r\n"
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="event_type"\r\n\r\n'
        body += b"MUSIC\r\n"
        body += f"--{boundary}--\r\n".encode()
        status, res = _http_json(
            "POST",
            f"{base}/api/library/ingest",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        assert status == 200, res
        assert res["ok"] is True
        assert res["track_id"] > 0
        tid = res["track_id"]

        # Alias + JSON path (Electron)
        wav2 = _silence_wav(tmp_path / "path_cart.wav", seconds=0.3)
        status, res2 = _http_json(
            "POST",
            f"{base}/api/ingest",
            data=json.dumps(
                {
                    "path": str(wav2),
                    "title": "Path Cart",
                    "artist": "Desk",
                    "event_type": "MUSIC",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert status == 200, res2
        assert res2["ok"] is True

        lib = list_library(q="Air Cart", db_path=db)
        assert any(row["id"] == tid for row in lib)

        # Put ingested cart on the Living Log (insert after position 0)
        day = "2026-09-06"
        status, inserted = _http_json(
            "POST",
            f"{base}/api/log/insert?date={day}",
            data=json.dumps(
                {
                    "after_position": -1,
                    "track_id": tid,
                    "event_type": "MUSIC",
                    "title": "Air Cart",
                    "artist": "Studio",
                    "duration_ms": 500,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert status == 200, inserted
        assert inserted.get("ok") is True, inserted

        # PLAY should bind session with playable media
        status, play = _http_json("POST", f"{base}/api/play?date={day}")
        assert status == 200, play
        assert play.get("running") is True

        status, st = _http_json("GET", f"{base}/api/status?date={day}")
        assert status == 200, st
        assert st.get("running") is True
        assert st.get("now") and st["now"].get("status") == "ON_AIR"
        assert st.get("playable_url") or (st["now"] and st["now"].get("playable_url"))

        # Idle VU after stop
        _http_json("POST", f"{base}/api/stop?date={day}")
        from mq_radio.engine.session import SESSION

        with SESSION.lock:
            SESSION.running = False
            SESSION.started_at = None
        vu = _synthetic_vu()
        assert vu["playing"] is False
        assert vu["left"] == 0.0 and vu["right"] == 0.0
    finally:
        httpd.shutdown()


def test_ingest_rejects_empty_with_clear_error(desk):
    from mq_radio.library.ingest import ingest_bytes

    res = ingest_bytes("empty.wav", b"", db_path=desk["db"], data_dir=desk["data"])
    assert res["ok"] is False
    assert "empty" in res["error"].lower()

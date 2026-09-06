"""Acceptance grind: P1 decks/markers/studio-clock/library-root Done evidence (no Mac audio)."""

from __future__ import annotations

import json
import threading
import time
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import mq_radio.config as cfg
from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import default_markers_for, ingest_file, library_audio_dir
from mq_radio.living_log.service import classify_ending, load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.web.app import make_handler
from mq_radio.web.build_info import DESKTOP_VERSION
from mq_radio.web.hotkeys_store import load_hotkeys, save_hotkeys


@pytest.fixture()
def desk(tmp_path: Path):
    db = tmp_path / "desk.db"
    data = tmp_path / "data"
    data.mkdir()
    init_db(db)
    seed_demo(db)
    prev = cfg.DATA_DIR
    cfg.apply_data_dir(data)
    import mq_radio.web.app as app_mod

    app_mod.DATA_DIR = data
    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None
        SESSION.running = False
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
        SESSION.active_deck = "A"
    yield {"db": db, "data": data, "tmp": tmp_path}
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev
    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None


def _http_json(method: str, url: str, data: bytes | None = None, headers: dict | None = None):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return e.code, payload


@pytest.fixture()
def httpd(desk):
    Handler = make_handler(desk["db"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.allow_reuse_address = True
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield {
            "port": port,
            "db": desk["db"],
            "data": desk["data"],
            "base": f"http://127.0.0.1:{port}",
            "tmp": desk["tmp"],
        }
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


def _tone_wav(path: Path, seconds: float = 2.0, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return path


def test_desktop_version_013_aligned():
    assert DESKTOP_VERSION == "0.1.3"


def test_markers_http_roundtrip_and_bad_id(httpd, tmp_path: Path):
    base = httpd["base"]
    src = _tone_wav(tmp_path / "Mark_Me.wav", seconds=8.0)
    ing = ingest_file(
        src,
        title="Mark Me",
        artist="Test",
        event_type="MUSIC",
        db_path=httpd["db"],
        data_dir=httpd["data"],
    )
    assert ing["ok"], ing
    tid = int(ing["track_id"])
    assert ing.get("outro_ms", 0) > 0
    d_intro, d_outro = default_markers_for("MUSIC", int(ing.get("duration_ms") or 8000))
    assert d_outro >= 500
    assert d_intro >= 0

    code, marked = _http_json(
        "POST",
        f"{base}/api/library/track/markers",
        data=json.dumps({"track_id": tid, "intro_ms": 1200, "end_pulse_ms": 2800}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert marked.get("ok") is True
    assert marked["intro_ms"] == 1200
    assert marked["outro_ms"] == 2800
    assert marked["end_pulse_ms"] == 2800
    assert marked.get("ending_type") == classify_ending(2800, has_track=True)
    assert marked["ending_type"] == "SOFT"
    assert "SOFT" in (marked.get("ending_label") or "")

    code, tr = _http_json("GET", f"{base}/api/library/track?id={tid}")
    assert code == 200
    track = tr["track"]
    assert track["intro_ms"] == 1200
    assert track["outro_ms"] == 2800
    assert track["ending_type"] == "SOFT"
    assert track.get("ending_label")

    code, bad = _http_json(
        "POST",
        f"{base}/api/library/track/markers",
        data=json.dumps({"track_id": "not-an-int", "intro_ms": 1}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 400
    assert bad.get("ok") is False
    assert "integer" in str(bad.get("error") or "").lower()

    code, missing = _http_json(
        "POST",
        f"{base}/api/library/track/markers",
        data=json.dumps({"intro_ms": 1}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 400
    assert missing.get("ok") is False


def test_status_decks_readable_with_ending_and_studio_clock(httpd):
    """Decks program slot: title/artist/time/ending + ELAPSED/REMAINING + studio_clock."""
    db = httpd["db"]
    base = httpd["base"]
    day = "2099-09-06"
    load_sample_hour(day, db_path=db, hour=14, clear_day=True)
    eng = MockEngine(day, db_path=db)
    st = eng.play()
    assert st.running
    with SESSION.lock:
        SESSION.duration_ms = 20_000
        SESSION.end_pulse_ms = 3000
        SESSION.intro_ms = 4000
        SESSION.started_at = time.time() - 2.5

    code, status = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    timing = status.get("timing") or {}
    assert timing.get("playing") is True
    assert timing.get("elapsed_ms", 0) >= 2000
    assert timing.get("remaining_ms", 0) > 0
    assert timing.get("duration_ms") == 20_000
    assert timing.get("end_pulse_ms") == 3000
    assert timing.get("intro_ms") == 4000

    decks = status.get("decks") or {}
    program = decks.get("program") or decks.get("a")
    assert program
    assert program.get("title")
    assert "artist" in program
    assert program.get("duration_ms")
    assert program.get("elapsed_ms", 0) >= 2000
    assert program.get("remaining_ms", 0) > 0
    assert program.get("ending_type") in ("COLD", "SOFT", "FADE")
    assert program.get("ending_label")
    # 3000ms pulse → SOFT; intro present → INTRO in label
    assert program["ending_type"] == "SOFT"
    assert "INTRO" in program["ending_label"]

    clock = status.get("studio_clock") or {}
    assert "to_time" in clock
    assert "etm_readout" in clock
    assert clock["to_time"] not in (None, "")

    code, log = _http_json("GET", f"{base}/api/log?date={day}")
    assert code == 200
    events = log.get("events") or []
    assert events
    music = [e for e in events if e.get("event_type") == "MUSIC"]
    assert music
    assert music[0].get("ending_type") in ("COLD", "SOFT", "FADE")
    assert music[0].get("ending_label")


def test_library_root_and_vt_inbox_http(httpd, tmp_path: Path):
    base = httpd["base"]
    data = httpd["data"]
    custom = tmp_path / "MQ_Digital_Library"
    code, saved = _http_json(
        "POST",
        f"{base}/api/settings/library-root",
        data=json.dumps({"path": str(custom)}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert saved.get("ok") is True
    assert Path(saved["path"]).resolve() == custom.resolve()
    assert library_audio_dir(data).resolve() == custom.resolve()

    code, st = _http_json("GET", f"{base}/api/settings/library-root")
    assert code == 200
    assert st.get("ok") is True
    assert Path(st["path"]).resolve() == custom.resolve()
    assert st.get("source") == "config"

    inbox = data / "vt-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    _tone_wav(inbox / "vocloner_break_01.wav", seconds=1.5)
    code, inbox_st = _http_json("GET", f"{base}/api/settings/vt-inbox")
    assert code == 200
    assert inbox_st.get("audio_files", 0) >= 1

    code, imported = _http_json(
        "POST",
        f"{base}/api/vt/import-inbox",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert imported.get("ok") is True
    assert int(imported.get("count") or 0) >= 1
    assert imported.get("imported")


def test_hotkey_in_place_path_no_library_copy(httpd, tmp_path: Path):
    """External path on hotkey slot persists as-is; fire plays in place (no ingest copy)."""
    data = httpd["data"]
    abs_path = str(tmp_path / "External" / "Sweeper_Brand.wav")
    _tone_wav(Path(abs_path), seconds=0.4)
    slots = load_hotkeys(data)["hotkeys"]
    slots[3] = {
        "slot": 3,
        "key": "F4",
        "label": "Brand Sweeper",
        "type": "SWEEPER",
        "target": None,
        "path": abs_path,
        "macro": None,
        "empty": False,
        "inject_mode": "over_program",
    }
    saved = save_hotkeys(slots, data)
    assert saved["ok"]
    again = load_hotkeys(data)
    hit = again["hotkeys"][3]
    assert hit["path"] == abs_path
    assert not str(hit["path"]).startswith(str(data / "library"))

    day = "2099-09-07"
    load_sample_hour(day, db_path=httpd["db"], hour=10, clear_day=True)
    code, fired = _http_json(
        "POST",
        f"{httpd['base']}/api/hotkey/fire",
        data=json.dumps(
            {
                "date": day,
                "path": abs_path,
                "label": "Brand Sweeper",
                "type": "SWEEPER",
                "inject_mode": "over_program",
                "inject": True,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert fired.get("ok") is True
    assert fired.get("fired") is True
    assert fired.get("copied_to_library") is False
    assert fired.get("exists") is True
    assert fired.get("playable_url")

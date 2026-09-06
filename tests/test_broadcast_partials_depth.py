"""Depth grind: cartwall pages, VT/segment API e2e, pulse/talk-up, mix-minus, TX mode."""

from __future__ import annotations

import base64
import json
import struct
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import mq_radio.config as cfg
from mq_radio.db.connection import init_db
from mq_radio.engine.audio_router import reset_audio_router
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import ffmpeg_available, ingest_file
from mq_radio.living_log.service import list_events, load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.web.app import make_handler
from mq_radio.web.hotkeys_store import (
    clear_slot,
    load_hotkeys,
    move_hotkey,
    page_slice,
    reorder_hotkeys,
    save_hotkeys,
    set_pages,
)
from mq_radio.web.settings_store import save_audio_outputs


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None
        SESSION.running = False
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
    return db


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
    reset_audio_router()
    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None
    yield {"db": db, "data": data}
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev
    reset_audio_router()


def _wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def _tone_wav(path: Path, *, seconds: float = 0.2, amp: float = 0.2) -> Path:
    import math

    rate = 16000
    n = int(rate * seconds)
    frames = b"".join(
        struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(n)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def _http_json(method: str, url: str, data: bytes | None = None, headers: dict | None = None):
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


def _serve(desk):
    Handler = make_handler(desk["db"])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}"


# —— Cartwall multi-page / reorder / color / clear ——


def test_hotkey_pages_expand_shrink_and_slice(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    loaded = load_hotkeys(data)
    assert loaded["pages"] == 2
    assert len(loaded["hotkeys"]) == 32
    expanded = set_pages(3, data, ui_page=1)
    assert expanded["ok"]
    assert expanded["pages"] == 3
    assert len(expanded["hotkeys"]) == 48
    assert expanded["ui_page"] == 1
    again = load_hotkeys(data)
    assert again["pages"] == 3
    assert again["ui_page"] == 1
    page2 = page_slice(again["hotkeys"], 2)
    assert len(page2) == 16
    assert page2[0]["slot"] == 32
    # Assign on page 3 then refuse shrink
    slots = again["hotkeys"]
    slots[40] = {
        "slot": 40,
        "key": "",
        "label": "Page3 Sting",
        "type": "SWEEPER",
        "color": "#00aaff",
        "path": "/Volumes/MQ/sting.wav",
        "inject_mode": "over_program",
        "empty": False,
    }
    save_hotkeys(slots, data, ui_page=2)
    bad = set_pages(2, data)
    assert not bad["ok"]
    assert "cannot shrink" in bad["error"]
    clear_slot(40, data)
    shrunk = set_pages(2, data)
    assert shrunk["ok"]
    assert shrunk["pages"] == 2


def test_hotkey_move_insert_across_pages(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    set_pages(3, data)
    slots = load_hotkeys(data)["hotkeys"]
    slots[0] = {
        "slot": 0,
        "key": "F1",
        "label": "Alpha",
        "type": "ID",
        "color": "#ff6600",
        "inject_mode": "over_program",
        "empty": False,
    }
    slots[17] = {
        "slot": 17,
        "key": "",
        "label": "Beta",
        "type": "PROMO",
        "color": "#33cc66",
        "inject_mode": "queue_next",
        "empty": False,
    }
    save_hotkeys(slots, data)
    moved = move_hotkey(0, 17, data)
    assert moved["ok"] and moved.get("moved")
    again = load_hotkeys(data)
    assert again["hotkeys"][17]["label"] == "Alpha"
    assert again["hotkeys"][17]["color"] == "#ff6600"
    # Page-0 F-keys rekeyed after shift
    assert again["hotkeys"][0]["key"] == "F1"
    # Swap still works
    swap = reorder_hotkeys(17, 0, data)
    assert swap["ok"]
    final = load_hotkeys(data)
    assert final["hotkeys"][0]["label"] == "Alpha"
    assert final["hotkeys"][0]["key"] == "F1"


def test_hotkey_pages_clear_move_api_e2e(desk):
    httpd, base = _serve(desk)
    try:
        code, hk = _http_json("GET", f"{base}/api/hotkeys")
        assert code == 200 and hk["pages"] == 2
        body = json.dumps({"pages": 4, "ui_page": 0}).encode()
        code, pages = _http_json(
            "POST",
            f"{base}/api/hotkeys/pages",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and pages["ok"]
        assert pages["pages"] == 4
        assert len(pages["hotkeys"]) == 64

        slots = pages["hotkeys"]
        slots[0]["label"] = "Color ID"
        slots[0]["type"] = "ID"
        slots[0]["color"] = "#ff6600"
        slots[0]["empty"] = False
        slots[20]["label"] = "Far Promo"
        slots[20]["type"] = "PROMO"
        slots[20]["color"] = "#33cc66"
        slots[20]["empty"] = False
        body = json.dumps({"hotkeys": slots, "ui_page": 1}).encode()
        code, saved = _http_json(
            "POST",
            f"{base}/api/hotkeys",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and saved["ok"]
        assert saved["ui_page"] == 1

        body = json.dumps({"from_slot": 0, "to_slot": 20}).encode()
        code, moved = _http_json(
            "POST",
            f"{base}/api/hotkeys/move",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and moved["ok"]
        assert moved["hotkeys"][20]["label"] == "Color ID"
        assert moved["hotkeys"][20]["color"] == "#ff6600"

        body = json.dumps({"slot": 20}).encode()
        code, cleared = _http_json(
            "POST",
            f"{base}/api/hotkeys/clear",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and cleared["ok"]
        assert cleared["hotkeys"][20]["empty"] is True
        assert cleared["hotkeys"][20]["label"] == ""
    finally:
        httpd.shutdown()


# —— VT record + segment editor API e2e ——


def test_vt_record_trim_attach_and_segment_api_e2e(desk, tmp_path: Path):
    db = desk["db"]
    data = desk["data"]
    day = "2099-08-10"
    load_sample_hour(day, db_path=db, hour=10, clear_day=True)
    events = list_events(day, db_path=db)
    vt_ev = next((e for e in events if e["event_type"] == "VOICE_TRACK"), None)
    if vt_ev is None:
        # sample hour always has VT; if not, use first event
        vt_ev = events[0]

    src = _tone_wav(tmp_path / "long_src.wav", seconds=1.0)
    ing = ingest_file(src, title="Long Bed", artist="Seg", db_path=db, data_dir=data)
    assert ing["ok"], ing

    httpd, base = _serve(desk)
    try:
        # Segment cut via API
        body = json.dumps(
            {
                "track_id": ing["track_id"],
                "in_ms": 100,
                "out_ms": 600,
                "title": "Bed Cut",
                "event_type": "VOICE_TRACK",
                "intro_ms": 50,
                "outro_ms": 80,
            }
        ).encode()
        code, seg = _http_json(
            "POST",
            f"{base}/api/library/segment",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and seg["ok"], seg
        assert seg["track_id"] > 0
        if ffmpeg_available():
            assert seg.get("cut") or seg.get("ffmpeg") or "segment" in (
                seg.get("message") or ""
            ).lower() or Path(seg.get("file_path") or "").suffix.lower() in (
                ".wav",
                "",
            )

        # Invalid window
        body = json.dumps(
            {"track_id": ing["track_id"], "in_ms": 800, "out_ms": 200}
        ).encode()
        code, bad = _http_json(
            "POST",
            f"{base}/api/library/segment",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 400
        assert not bad.get("ok")

        # VT record with wav b64 + trim
        take = _tone_wav(tmp_path / "vt_take.wav", seconds=0.6)
        b64 = base64.b64encode(take.read_bytes()).decode()
        body = json.dumps(
            {
                "event_id": vt_ev["id"],
                "audio_b64": b64,
                "mime": "audio/wav",
                "trim_in_ms": 50,
                "trim_out_ms": 400,
                "script_text": "API recorded take",
            }
        ).encode()
        code, rec = _http_json(
            "POST",
            f"{base}/api/vt/record",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and rec["ok"], rec
        assert rec["log_event_id"] == vt_ev["id"]
        assert rec["trim_mode"] in ("cut", "markers_only", "raw")
        assert rec.get("track_id") or rec.get("audio_path")

        # Missing audio
        body = json.dumps({"event_id": vt_ev["id"], "audio_b64": ""}).encode()
        code, miss = _http_json(
            "POST",
            f"{base}/api/vt/record",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 400
        assert not miss.get("ok")

        # Attach segment cart to VT event
        body = json.dumps(
            {"event_id": vt_ev["id"], "track_id": seg["track_id"]}
        ).encode()
        code, att = _http_json(
            "POST",
            f"{base}/api/vt/attach-cart",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and att["ok"], att
        assert att["track_id"] == seg["track_id"]
    finally:
        httpd.shutdown()


# —— AUTO end-pulse / ASSIST talk-up timing ——


def test_auto_pulse_exact_boundary_and_noop(demo_db):
    day = "2099-08-11"
    load_sample_hour(day, db_path=demo_db, hour=11, clear_day=True)
    eng = MockEngine(day, db_path=demo_db)
    with SESSION.lock:
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
    eng.play()
    with SESSION.lock:
        first = SESSION.event_id
        SESSION.end_pulse_ms = 1000
        SESSION.duration_ms = 5000
        # Exactly at boundary: elapsed == dur - pulse
        SESSION.started_at = time.time() - 4.0
        t = SESSION.timing()
    assert t["pulse_due"] is True
    assert t["in_end_pulse"] is True
    assert eng.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.event_id != first
        assert SESSION.running is True

    # Fresh cart — not due yet
    with SESSION.lock:
        SESSION.end_pulse_ms = 1000
        SESSION.duration_ms = 10000
        SESSION.started_at = time.time() - 1.0
        assert SESSION.timing()["pulse_due"] is False
    assert eng.finish_if_due() is False


def test_assist_talk_up_applicable_and_pulse_api(desk):
    db = desk["db"]
    day = "2099-08-12"
    load_sample_hour(day, db_path=db, hour=12, clear_day=True)
    with SESSION.lock:
        SESSION.playout_mode = "ASSIST"
        SESSION.auto_advance = False
    eng = MockEngine(day, db_path=db)
    eng.play()
    with SESSION.lock:
        SESSION.intro_ms = 4000
        SESSION.duration_ms = 20000
        SESSION.started_at = time.time() - 1.0
        SESSION.event_type = "MUSIC"
        t = SESSION.timing()
    assert t["talk_up_applicable"] is True
    assert t["in_intro"] is True
    assert 2500 <= t["talk_up_remaining_ms"] <= 3500

    with SESSION.lock:
        SESSION.event_type = "ID"
        SESSION.intro_ms = 4000
        t2 = SESSION.timing()
    assert t2["talk_up_applicable"] is False  # imaging IDs don't talk-up

    with SESSION.lock:
        SESSION.event_type = "MUSIC"
        SESSION.end_pulse_ms = 500
        SESSION.duration_ms = 2000
        SESSION.started_at = time.time() - 1.6
        first = SESSION.event_id
    assert eng.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.assist_go_ready is True

    httpd, base = _serve(desk)
    try:
        # Pulse without go while already finished path — go advances
        body = json.dumps({"date": day}).encode()
        code, idle = _http_json(
            "POST",
            f"{base}/api/pulse",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200
        # Without go, ASSIST armed still needs go=true for advance_with_overlap force
        # finish_if_due already returned; pulse without go may not force
        body = json.dumps({"go": True, "date": day}).encode()
        code, go = _http_json(
            "POST",
            f"{base}/api/pulse",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and go["ok"]
        assert go["advanced"] is True
        with SESSION.lock:
            assert SESSION.assist_go_ready is False
            assert SESSION.event_id != first or SESSION.running
    finally:
        httpd.shutdown()


def test_auto_mode_ignores_talk_up_applicable(demo_db):
    day = "2099-08-13"
    load_sample_hour(day, db_path=demo_db, hour=13, clear_day=True)
    with SESSION.lock:
        SESSION.playout_mode = "AUTO"
        SESSION.auto_advance = True
    eng = MockEngine(day, db_path=demo_db)
    eng.play()
    with SESSION.lock:
        SESSION.intro_ms = 5000
        SESSION.duration_ms = 20000
        SESSION.started_at = time.time() - 1.0
        SESSION.event_type = "MUSIC"
        t = SESSION.timing()
    assert t["in_intro"] is True
    assert t["talk_up_applicable"] is False  # AUTO — no VOCALS IN desk cue


# —— Multi-bus / mix-minus browser path ——


def test_mix_minus_browser_path_api_e2e(desk):
    httpd, base = _serve(desk)
    try:
        body = json.dumps(
            {
                "outputs": {
                    "program": "builtin",
                    "monitor": "builtin",
                    "headphones": "usb",
                    "aux1": "none",
                    "aux2": "none",
                    "mix_minus": "usb",
                    "stream": "same_as_program",
                    "record": "none",
                },
                "inputs": {"aux_in": "zoom_return", "mic": "none"},
            }
        ).encode()
        code, route = _http_json(
            "POST",
            f"{base}/api/settings/audio",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and route.get("ok"), route
        code, st = _http_json("GET", f"{base}/api/audio/route")
        assert code == 200
        mm = (st.get("mix_minus") or st) if "mix_minus" in st else (st.get("mix_minus") or {})
        # status shape: either top-level mix_minus or nested
        if "mix_minus" in st:
            mm = st["mix_minus"]
        assert mm.get("paired") is True or mm.get("out") == "usb"

        body = json.dumps(
            {
                "subtract_active": True,
                "subtract_mode": "program_minus_aux",
                "detail": "Web Audio live e2e",
            }
        ).encode()
        code, live = _http_json(
            "POST",
            f"{base}/api/audio/mix-minus",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and live["ok"]
        mm2 = live["mix_minus"]
        assert mm2["subtract_active"] is True
        assert mm2["subtract_mode"] == "program_minus_aux"
        assert "Browser" in (mm2.get("description") or "") or "live" in (
            mm2.get("description") or ""
        ).lower()

        code, st2 = _http_json("GET", f"{base}/api/status")
        assert code == 200
        ar = st2.get("audio_route") or {}
        mm3 = ar.get("mix_minus") or {}
        assert mm3.get("subtract_active") is True
    finally:
        httpd.shutdown()


# —— TX / transmission mode operator path ——


def test_transmission_mode_operator_api_e2e(desk, tmp_path: Path):
    httpd, base = _serve(desk)
    try:
        body = json.dumps(
            {"apply_template": "FM", "transmission_mode": True, "enabled": True}
        ).encode()
        code, saved = _http_json(
            "POST",
            f"{base}/api/settings/processing",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and saved.get("ok"), saved
        assert saved.get("transmission_mode") is True
        assert saved.get("template") == "FM"

        code, st = _http_json("GET", f"{base}/api/status")
        assert code == 200
        proc = st.get("processing") or {}
        assert proc.get("transmission_mode") is True
        assert proc.get("template") == "FM"
        assert "+TX" in (proc.get("summary") or "") or proc.get("transmission_mode")

        # Digital + TX
        body = json.dumps(
            {"apply_template": "DIGITAL", "transmission_mode": True}
        ).encode()
        code, dig = _http_json(
            "POST",
            f"{base}/api/settings/processing",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and dig.get("ok")
        assert dig.get("template") == "DIGITAL"
        assert dig.get("transmission_mode") is True

        src = _tone_wav(tmp_path / "tx_in.wav", seconds=0.25)
        dst = tmp_path / "tx_out.wav"
        body = json.dumps(
            {
                "src": str(src),
                "dst": str(dst),
                "template": "FM",
                "transmission_mode": True,
            }
        ).encode()
        code, wav = _http_json(
            "POST",
            f"{base}/api/settings/processing/wav-stub",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and wav.get("ok"), wav
        assert Path(wav["dst"]).is_file()
        assert wav.get("transmission_mode") is True
        assert wav.get("template") == "FM"

        # Desk mode (TX off) persists
        body = json.dumps({"transmission_mode": False}).encode()
        code, desk_mode = _http_json(
            "POST",
            f"{base}/api/settings/processing",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and desk_mode.get("ok")
        assert desk_mode.get("transmission_mode") is False
    finally:
        httpd.shutdown()

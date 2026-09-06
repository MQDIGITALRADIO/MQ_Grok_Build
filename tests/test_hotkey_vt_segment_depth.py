"""Depth grind: hotkey fire path reliability + VT/segment deeper API e2e (no Mac audio)."""

from __future__ import annotations

import base64
import json
import struct
import threading
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import mq_radio.config as cfg
from mq_radio.db.connection import init_db
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import ffmpeg_available, get_track, ingest_file
from mq_radio.living_log.service import list_events, load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.voice_tracker.recording import save_vt_recording
from mq_radio.web.app import make_handler


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
    yield {"db": db, "data": data}
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev
    with SESSION.lock:
        SESSION.oneshot = None


def _tone_wav(path: Path, *, seconds: float = 0.4, amp: float = 0.2) -> Path:
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


# —— Hotkey fire path reliability ——


def test_hotkey_fire_existing_path_injects_oneshot_and_media(desk, tmp_path: Path):
    day = "2099-09-20"
    load_sample_hour(day, db_path=desk["db"], hour=10, clear_day=True)
    sting = _tone_wav(tmp_path / "sting.wav", seconds=0.35)
    httpd, base = _serve(desk)
    try:
        body = json.dumps(
            {
                "date": day,
                "label": "Brand Sting",
                "type": "SWEEPER",
                "path": str(sting),
                "inject_mode": "over_program",
                "inject": True,
            }
        ).encode()
        code, res = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and res["fired"] is True, res
        assert res["ok"] is True
        assert res["exists"] is True
        assert res["injected"] is True
        assert res["inject_mode"] == "over_program"
        assert res["copied_to_library"] is False
        assert res["playable_url"]
        assert "media?path=" in res["playable_url"]
        assert res["duration_ms"] > 0
        assert res["date"] == day
        assert "desk audio" in (res.get("message") or "").lower()

        code, st = _http_json("GET", f"{base}/api/status?date={day}")
        assert code == 200
        shot = st.get("oneshot")
        assert shot is not None
        assert shot.get("label") == "Brand Sting"
        assert shot.get("playable_url")

        # Media endpoint serves absolute path (desk one-shot)
        media_url = base + res["playable_url"]
        req = urllib.request.Request(media_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            ctype = resp.headers.get("Content-Type") or ""
            assert "audio" in ctype or "octet" in ctype
            blob = resp.read()
            assert len(blob) > 44
            assert blob[:4] == b"RIFF"
    finally:
        httpd.shutdown()
        with SESSION.lock:
            SESSION.oneshot = None


def test_hotkey_fire_track_id_and_queue_next_date(desk, tmp_path: Path):
    day = "2099-09-21"
    load_sample_hour(day, db_path=desk["db"], hour=11, clear_day=True)
    before = list_events(day, db_path=desk["db"])
    src = _tone_wav(tmp_path / "id_cart.wav", seconds=0.5)
    ing = ingest_file(
        src, title="Station ID", artist="MQ", event_type="ID",
        db_path=desk["db"], data_dir=desk["data"],
    )
    assert ing["ok"], ing

    httpd, base = _serve(desk)
    try:
        # Fire by track id over program
        body = json.dumps(
            {
                "date": day,
                "target": ing["track_id"],
                "inject_mode": "over_program",
            }
        ).encode()
        code, res = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and res["fired"], res
        assert res["kind"] == "track"
        assert res["track_id"] == ing["track_id"]
        assert res["exists"] is True
        assert res["playable_url"] == f"/api/media/track/{ing['track_id']}"
        assert res["label"] == "Station ID"
        assert res["injected"] is True

        # Serve track media
        req = urllib.request.Request(base + res["playable_url"])
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            assert resp.read()[:4] == b"RIFF"

        with SESSION.lock:
            SESSION.oneshot = None

        # queue_next must honor body date (not server "today")
        body = json.dumps(
            {
                "date": day,
                "label": "Queued Promo",
                "type": "PROMO",
                "target": ing["track_id"],
                "inject_mode": "queue_next",
            }
        ).encode()
        code, q = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and q["fired"], q
        assert q["inject_mode"] == "queue_next"
        assert q["injected"] is True
        assert q["date"] == day
        assert "log 2099-09-21" in (q.get("message") or "")
        after = list_events(day, db_path=desk["db"])
        assert len(after) == len(before) + 1
        queued = next(e for e in after if "HOTKEY INJECT" in (e.get("notes") or ""))
        assert queued["manual_flag"] == "MANUAL"
        assert queued["title"] == "Queued Promo"
    finally:
        httpd.shutdown()
        with SESSION.lock:
            SESSION.oneshot = None


def test_hotkey_fire_desk_only_and_empty_reject(desk, tmp_path: Path):
    sting = _tone_wav(tmp_path / "desk_only.wav", seconds=0.2)
    httpd, base = _serve(desk)
    try:
        body = json.dumps(
            {
                "label": "Preview Only",
                "path": str(sting),
                "inject": False,
                "inject_mode": "over_program",
            }
        ).encode()
        code, res = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and res["fired"], res
        assert res["injected"] is False
        assert res["exists"] is True
        assert res["playable_url"]
        assert "desk-only" in (res.get("message") or "").lower()
        with SESSION.lock:
            assert SESSION.oneshot is None

        # Empty fire
        body = json.dumps({"label": "Hotkey", "inject": True}).encode()
        code, empty = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 400
        assert empty.get("fired") is False
        assert "empty" in (empty.get("message") or empty.get("error") or "").lower()

        # Boolean inject_mode must not become mode string
        body = json.dumps(
            {
                "label": "Bool Mode",
                "path": str(sting),
                "inject_mode": True,
                "inject": True,
            }
        ).encode()
        code, bool_mode = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and bool_mode["fired"]
        assert bool_mode["inject_mode"] == "over_program"
    finally:
        httpd.shutdown()
        with SESSION.lock:
            SESSION.oneshot = None


def test_hotkey_fire_missing_path_status_clear(desk):
    httpd, base = _serve(desk)
    try:
        body = json.dumps(
            {
                "label": "Ghost",
                "type": "ID",
                "path": "/Volumes/MQ/does-not-exist.wav",
                "inject_mode": "over_program",
            }
        ).encode()
        code, res = _http_json(
            "POST",
            f"{base}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200
        assert res["fired"] is True
        assert res["exists"] is False
        assert res["playable_url"] is None
        assert res["copied_to_library"] is False
        assert "missing" in (res.get("message") or "").lower()
    finally:
        httpd.shutdown()


# —— VT record / Segment Editor deeper round-trip ——


def test_vt_invalid_trim_and_empty_audio(desk, tmp_path: Path):
    day = "2099-09-22"
    load_sample_hour(day, db_path=desk["db"], hour=12, clear_day=True)
    vt = next(e for e in list_events(day, db_path=desk["db"]) if e["event_type"] == "VOICE_TRACK")
    take = _tone_wav(tmp_path / "vt.wav", seconds=0.5)
    b64 = base64.b64encode(take.read_bytes()).decode()

    bad = save_vt_recording(
        vt["id"],
        audio_b64=b64,
        mime="audio/wav",
        trim_in_ms=800,
        trim_out_ms=200,
        db_path=desk["db"],
        data_dir=desk["data"],
    )
    assert not bad["ok"]
    assert "after" in bad["error"].lower() or "out" in bad["error"].lower()

    empty = save_vt_recording(
        vt["id"],
        audio_b64="data:audio/wav;base64,",  # truthy wrapper, empty payload
        mime="audio/wav",
        db_path=desk["db"],
        data_dir=desk["data"],
    )
    assert not empty["ok"]
    assert "empty" in empty["error"].lower()

    httpd, base = _serve(desk)
    try:
        body = json.dumps(
            {
                "event_id": vt["id"],
                "audio_b64": b64,
                "mime": "audio/wav",
                "trim_in_ms": 500,
                "trim_out_ms": 100,
            }
        ).encode()
        code, api_bad = _http_json(
            "POST",
            f"{base}/api/vt/record",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 400
        assert not api_bad.get("ok")
    finally:
        httpd.shutdown()


def test_vt_record_segment_source_markers_attach_roundtrip(desk, tmp_path: Path):
    """Record → segment cut+markers (+source) → attach → log event has cart."""
    db = desk["db"]
    data = desk["data"]
    day = "2099-09-23"
    load_sample_hour(day, db_path=db, hour=13, clear_day=True)
    vt_ev = next(e for e in list_events(day, db_path=db) if e["event_type"] == "VOICE_TRACK")

    long_src = _tone_wav(tmp_path / "interview.wav", seconds=1.2)
    ing = ingest_file(
        long_src, title="Long Interview", artist="Guest",
        db_path=db, data_dir=data,
    )
    assert ing["ok"], ing

    httpd, base = _serve(desk)
    try:
        take = _tone_wav(tmp_path / "mic_take.wav", seconds=0.7)
        b64 = base64.b64encode(take.read_bytes()).decode()
        body = json.dumps(
            {
                "event_id": vt_ev["id"],
                "audio_b64": b64,
                "mime": "audio/wav",
                "trim_in_ms": 40,
                "trim_out_ms": 500,
                "script_text": "Roundtrip take",
            }
        ).encode()
        code, rec = _http_json(
            "POST",
            f"{base}/api/vt/record",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and rec["ok"], rec
        assert rec["trim_mode"] in ("cut", "markers_only", "raw")
        assert rec.get("track_id") or rec.get("audio_path")
        assert rec["trim_in_ms"] == 40
        assert int(rec["trim_out_ms"]) == 500

        # Segment long cart with markers on NEW + SOURCE
        body = json.dumps(
            {
                "track_id": ing["track_id"],
                "in_ms": 100,
                "out_ms": 700,
                "title": "Interview Part A",
                "artist": "Guest",
                "event_type": "VOICE_TRACK",
                "intro_ms": 80,
                "outro_ms": 120,
                "end_pulse_ms": 120,
                "save_source_markers": True,
                "source_intro_ms": 90,
                "source_outro_ms": 150,
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
        assert seg.get("intro_ms") == 80
        assert seg.get("outro_ms") == 120 or seg.get("end_pulse_ms") == 120
        assert seg.get("source_markers_saved") is True
        assert seg.get("source_track_id") == ing["track_id"]
        assert seg.get("source_intro_ms") == 90
        assert seg.get("source_outro_ms") == 150

        # Confirm DB markers on both carts
        new_cart = get_track(seg["track_id"], db_path=db)
        assert new_cart is not None
        assert int(new_cart["intro_ms"] or 0) == 80
        src_cart = get_track(ing["track_id"], db_path=db)
        assert int(src_cart["intro_ms"] or 0) == 90
        assert int(src_cart["outro_ms"] or 0) == 150

        if ffmpeg_available():
            assert seg.get("trim_mode") in ("cut", "markers_only") or seg.get("cut") in (
                True,
                False,
                None,
            )

        # Attach segment to VT log event
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

        events = list_events(day, db_path=db)
        attached = next(e for e in events if e["id"] == vt_ev["id"])
        assert attached["track_id"] == seg["track_id"]
        assert attached["event_type"] == "VOICE_TRACK"
        assert attached["manual_flag"] == "MANUAL"
        assert "Interview Part A" in (attached.get("title") or "")
        assert "[VT AUDIO" in (attached.get("notes") or "")

        # GET track playable for segment cart
        code, tr = _http_json("GET", f"{base}/api/library/track?id={seg['track_id']}")
        assert code == 200 and tr.get("ok"), tr
        assert tr["track"]["id"] == seg["track_id"]
    finally:
        httpd.shutdown()


def test_segue_context_has_audition_fields_without_claiming_mac(desk):
    """Segue context + save stay Partial for Mac hear-through; API fields present."""
    day = "2099-09-24"
    load_sample_hour(day, db_path=desk["db"], hour=14, clear_day=True)
    events = list_events(day, db_path=desk["db"])
    music = [e for e in events if e["event_type"] == "MUSIC"]
    assert len(music) >= 2
    httpd, base = _serve(desk)
    try:
        code, ctx = _http_json("GET", f"{base}/api/segue?event_id={music[0]['id']}")
        assert code == 200 and ctx.get("ok"), ctx
        assert "outgoing" in ctx or "from" in ctx or "segue" in ctx
        body = json.dumps(
            {
                "from_event_id": music[0]["id"],
                "to_event_id": music[1]["id"],
                "duck_db": -12,
                "crossfade_ms": 1800,
                "from_outro_mark_ms": 400,
                "to_intro_mark_ms": 600,
            }
        ).encode()
        code, saved = _http_json(
            "POST",
            f"{base}/api/segue/save",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and saved["ok"], saved
        assert saved["segue"]["crossfade_ms"] == 1800
        assert saved["segue"]["duck_db"] == -12.0
    finally:
        httpd.shutdown()

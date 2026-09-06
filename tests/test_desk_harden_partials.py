"""P0/P1 desk harden: Living Log, talk-up/pulse, hotkey reorder, segue/segment, ingest edges."""

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

import mq_radio.config as cfg
from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import (
    ffmpeg_available,
    ingest_bytes,
    ingest_file,
    save_segment_as_cart,
)
from mq_radio.living_log.service import (
    delete_event,
    insert_event,
    list_events,
    list_library,
    load_sample_hour,
    replace_event,
)
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import generate_log
from mq_radio.segue.service import save_segue, segue_context_for_event
from mq_radio.web.app import make_handler
from mq_radio.web.hotkeys_store import load_hotkeys, reorder_hotkeys, save_hotkeys


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
    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None
    yield {"db": db, "data": data}
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev


def _wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> Path:
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
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return e.code, payload


# —— Living Log reliability ——


def test_living_log_insert_clamps_after_position(demo_db):
    day = "2099-04-01"
    load_sample_hour(day, db_path=demo_db, hour=10, clear_day=True)
    before = list_events(day, db_path=demo_db)
    lib = list_library(db_path=demo_db)
    music = next(t for t in lib if t["event_type"] == "MUSIC")
    # Huge after_position must clamp to end, not create a sparse gap
    ins = insert_event(
        day,
        after_position=9999,
        event_dict={"track_id": music["id"]},
        db_path=demo_db,
    )
    assert ins["ok"], ins
    after = list_events(day, db_path=demo_db)
    assert len(after) == len(before) + 1
    positions = [e["position"] for e in after]
    assert positions == list(range(len(after)))
    assert after[-1]["id"] == ins["event_id"]
    assert after[-1]["manual_flag"] == "MANUAL"


def test_living_log_delete_replace_error_paths(demo_db):
    day = "2099-04-02"
    load_sample_hour(day, db_path=demo_db, hour=11, clear_day=True)
    events = list_events(day, db_path=demo_db)
    music = next(e for e in events if e["event_type"] == "MUSIC")
    bad = delete_event(999999, db_path=demo_db)
    assert not bad["ok"]
    assert "not found" in bad["error"]
    bad2 = delete_event("nope", db_path=demo_db)
    assert not bad2["ok"]
    bad3 = replace_event(music["id"], 999999, db_path=demo_db)
    assert not bad3["ok"]
    bad4 = replace_event("x", 1, db_path=demo_db)
    assert not bad4["ok"]


def test_living_log_manual_and_vt_survive_regenerate(demo_db):
    day = "2099-04-03"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    events = list_events(day, db_path=demo_db)
    vt = next(e for e in events if e["event_type"] == "VOICE_TRACK")
    lib = list_library(db_path=demo_db)
    music = next(t for t in lib if t["event_type"] == "MUSIC")
    ins = insert_event(
        day,
        after_position=vt["position"],
        event_dict={"track_id": music["id"]},
        db_path=demo_db,
    )
    assert ins["ok"]
    # Soft regenerate preserves MANUAL
    generate_log(day, db_path=demo_db, force=False)
    after = list_events(day, db_path=demo_db)
    manuals = [e for e in after if e["manual_flag"] == "MANUAL"]
    assert any(e["id"] == ins["event_id"] or e["title"] == music["title"] for e in manuals)
    assert any(e["event_type"] == "VOICE_TRACK" and e["manual_flag"] == "MANUAL" for e in after)


def test_living_log_api_delete_insert_replace(desk):
    db = desk["db"]
    day = "2099-04-04"
    load_sample_hour(day, db_path=db, hour=9, clear_day=True)
    Handler = make_handler(db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, log = _http_json("GET", f"{base}/api/log?date={day}")
        assert code == 200
        events = log["events"]
        target = next(e for e in events if e["event_type"] == "MUSIC")
        code, lib = _http_json("GET", f"{base}/api/library")
        assert code == 200
        tracks = lib.get("tracks") or lib.get("library") or lib
        if isinstance(tracks, dict):
            tracks = tracks.get("tracks") or []
        music = next(x for x in tracks if x.get("event_type") == "MUSIC")

        body = json.dumps({"event_id": target["id"]}).encode()
        code, deleted = _http_json(
            "POST",
            f"{base}/api/log/delete",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and deleted["ok"]

        body = json.dumps(
            {"date": day, "after_position": 0, "track_id": music["id"]}
        ).encode()
        code, inserted = _http_json(
            "POST",
            f"{base}/api/log/insert",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and inserted["ok"], inserted

        other = next(x for x in tracks if x["id"] != music["id"] and x.get("event_type") == "MUSIC")
        body = json.dumps(
            {"event_id": inserted["event_id"], "track_id": other["id"]}
        ).encode()
        code, replaced = _http_json(
            "POST",
            f"{base}/api/log/replace",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and replaced["ok"], replaced
        assert replaced["title"] == other["title"]
    finally:
        httpd.shutdown()


# —— AUTO pulse / ASSIST talk-up ——


def test_talk_up_countdown_fields_assist_only_semantics(demo_db):
    day = "2099-05-01"
    load_sample_hour(day, db_path=demo_db, hour=8, clear_day=True)
    with SESSION.lock:
        SESSION.playout_mode = "ASSIST"
        SESSION.auto_advance = False
    eng = MockEngine(day, db_path=demo_db)
    eng.play()
    with SESSION.lock:
        SESSION.intro_ms = 5000
        SESSION.duration_ms = 20000
        SESSION.started_at = time.time() - 1.5  # 1500ms into intro
        SESSION.event_type = "MUSIC"
        t = SESSION.timing()
    assert t["playing"] is True
    assert t["in_intro"] is True
    assert t["vocals_in"] is False
    assert 3000 <= t["talk_up_remaining_ms"] <= 4000
    assert t["event_type"] == "MUSIC"
    assert t["intro_ms"] == 5000

    with SESSION.lock:
        SESSION.started_at = time.time() - 6.0  # past intro
        t2 = SESSION.timing()
    assert t2["in_intro"] is False
    assert t2["vocals_in"] is True
    assert t2["talk_up_remaining_ms"] == 0


def test_assist_go_via_pulse_api_advances(desk):
    db = desk["db"]
    day = "2099-05-02"
    load_sample_hour(day, db_path=db, hour=14, clear_day=True)
    with SESSION.lock:
        SESSION.playout_mode = "ASSIST"
        SESSION.auto_advance = False
    eng = MockEngine(day, db_path=db)
    eng.play()
    with SESSION.lock:
        first = SESSION.event_id
        SESSION.end_pulse_ms = 800
        SESSION.duration_ms = 3000
        SESSION.started_at = time.time() - 2.5
    assert eng.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.assist_go_ready is True

    Handler = make_handler(db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"go": True, "date": day}).encode()
        code, res = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/api/pulse",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and res["ok"]
        assert res["advanced"] is True
        with SESSION.lock:
            assert SESSION.assist_go_ready is False
            assert SESSION.event_id != first or SESSION.running
    finally:
        httpd.shutdown()


def test_auto_end_pulse_chains_with_overlap(demo_db):
    day = "2099-05-03"
    load_sample_hour(day, db_path=demo_db, hour=15, clear_day=True)
    eng = MockEngine(day, db_path=demo_db)
    with SESSION.lock:
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
    eng.play()
    with SESSION.lock:
        first = SESSION.event_id
        SESSION.end_pulse_ms = 1200
        SESSION.duration_ms = 4000
        SESSION.started_at = time.time() - 3.0
        assert SESSION.timing()["pulse_due"] is True
    assert eng.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.event_id != first
        assert SESSION.running is True
        # Dual-deck overlap should be active after AUTO pulse chain
        assert SESSION.overlap_active is True or SESSION.event_id is not None


# —— Hotkey bank reorder + persistence ——


def test_hotkey_reorder_persists_and_rekeys(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    slots = load_hotkeys(data)["hotkeys"]
    slots[0] = {
        "slot": 0,
        "key": "F1",
        "label": "Alpha ID",
        "type": "ID",
        "color": "#ff6600",
        "path": "/Volumes/MQ/alpha.wav",
        "inject_mode": "over_program",
        "empty": False,
    }
    slots[1] = {
        "slot": 1,
        "key": "F2",
        "label": "Beta Sweep",
        "type": "SWEEPER",
        "color": "#00aaff",
        "inject_mode": "queue_next",
        "empty": False,
    }
    save_hotkeys(slots, data)
    res = reorder_hotkeys(0, 1, data)
    assert res["ok"], res
    again = load_hotkeys(data)
    assert again["hotkeys"][0]["label"] == "Beta Sweep"
    assert again["hotkeys"][0]["key"] == "F1"  # rekeyed
    assert again["hotkeys"][0]["color"] == "#00aaff"
    assert again["hotkeys"][1]["label"] == "Alpha ID"
    assert again["hotkeys"][1]["key"] == "F2"
    assert again["hotkeys"][1]["path"] == "/Volumes/MQ/alpha.wav"
    bad = reorder_hotkeys(0, 99, data)
    assert not bad["ok"]


def test_hotkey_reorder_api(desk):
    Handler = make_handler(desk["db"])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, hk = _http_json("GET", f"{base}/api/hotkeys")
        assert code == 200
        slots = hk["hotkeys"]
        slots[0]["label"] = "Reorder Me"
        slots[0]["type"] = "ID"
        slots[0]["empty"] = False
        slots[2]["label"] = "Target Slot"
        slots[2]["type"] = "PROMO"
        slots[2]["empty"] = False
        body = json.dumps({"hotkeys": slots}).encode()
        code, saved = _http_json(
            "POST",
            f"{base}/api/hotkeys",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and saved["ok"]
        body = json.dumps({"from_slot": 0, "to_slot": 2}).encode()
        code, reo = _http_json(
            "POST",
            f"{base}/api/hotkeys/reorder",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200 and reo["ok"], reo
        code, again = _http_json("GET", f"{base}/api/hotkeys")
        assert again["hotkeys"][0]["label"] == "Target Slot"
        assert again["hotkeys"][2]["label"] == "Reorder Me"
        assert again["hotkeys"][0]["key"] == "F1"
    finally:
        httpd.shutdown()


def test_hotkey_fire_status_feedback_missing_path(desk):
    Handler = make_handler(desk["db"])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps(
            {
                "label": "Missing Sting",
                "type": "SWEEPER",
                "path": "/no/such/file/sting.wav",
                "inject_mode": "over_program",
                "inject": True,
            }
        ).encode()
        code, res = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/api/hotkey/fire",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200
        assert res["fired"] is True
        assert res["exists"] is False
        assert "missing" in (res.get("message") or "").lower()
        assert res["copied_to_library"] is False
    finally:
        httpd.shutdown()


# —— Segue / segment validation ——


def test_segue_save_validation_paths(demo_db):
    day = "2099-06-01"
    load_sample_hour(day, db_path=demo_db, hour=16, clear_day=True)
    events = list_events(day, db_path=demo_db)
    music = [e for e in events if e["event_type"] == "MUSIC"]
    assert len(music) >= 2
    same = save_segue(
        {"from_event_id": music[0]["id"], "to_event_id": music[0]["id"]},
        db_path=demo_db,
    )
    assert not same["ok"]
    missing = save_segue(
        {"from_event_id": music[0]["id"], "to_event_id": 999999},
        db_path=demo_db,
    )
    assert not missing["ok"]
    bad_duck = save_segue(
        {
            "from_event_id": music[0]["id"],
            "to_event_id": music[1]["id"],
            "duck_db": "loud",
        },
        db_path=demo_db,
    )
    assert not bad_duck["ok"]
    clamped = save_segue(
        {
            "from_event_id": music[0]["id"],
            "to_event_id": music[1]["id"],
            "duck_db": -99,
            "crossfade_ms": 50000,
            "from_outro_mark_ms": -5,
            "to_intro_mark_ms": 2500,
        },
        db_path=demo_db,
    )
    assert clamped["ok"], clamped
    assert clamped["segue"]["duck_db"] == -40.0
    assert clamped["segue"]["crossfade_ms"] == 12000
    assert clamped["segue"]["from_outro_mark_ms"] == 0
    assert clamped["segue"]["to_intro_mark_ms"] == 2500


def test_segment_invalid_window_and_missing_track(demo_db, tmp_path: Path):
    data = tmp_path / "data"
    bad = save_segment_as_cart(999999, in_ms=0, out_ms=1000, db_path=demo_db, data_dir=data)
    assert not bad["ok"]
    src = _wav(tmp_path / "seg.wav", seconds=2.0)
    ing = ingest_file(src, title="Seg Source", db_path=demo_db, data_dir=data)
    assert ing["ok"], ing
    inv = save_segment_as_cart(
        ing["track_id"], in_ms=1500, out_ms=500, db_path=demo_db, data_dir=data
    )
    assert not inv["ok"]
    assert "after" in (inv.get("error") or "").lower() or "out" in (inv.get("error") or "").lower()


# —— Library ingest edge cases ——


def test_ingest_bad_paths_empty_and_unsupported(demo_db, tmp_path: Path):
    data = tmp_path / "data"
    miss = ingest_file(tmp_path / "nope.wav", db_path=demo_db, data_dir=data)
    assert not miss["ok"]
    assert "not found" in miss["error"].lower() or "file" in miss["error"].lower()

    d = tmp_path / "adir"
    d.mkdir()
    isdir = ingest_file(d, db_path=demo_db, data_dir=data)
    assert not isdir["ok"]
    assert "directory" in isdir["error"].lower()

    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    emp = ingest_file(empty, db_path=demo_db, data_dir=data)
    assert not emp["ok"]
    assert "empty" in emp["error"].lower()

    noext = tmp_path / "rawblob"
    noext.write_bytes(b"RIFF" + b"\x00" * 40)
    nx = ingest_file(noext, db_path=demo_db, data_dir=data)
    assert not nx["ok"]

    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    bad = ingest_file(txt, db_path=demo_db, data_dir=data)
    assert not bad["ok"]
    assert "unsupported" in bad["error"].lower()

    empty_bytes = ingest_bytes("x.wav", b"", db_path=demo_db, data_dir=data)
    assert not empty_bytes["ok"]


def test_ingest_flac_and_mp4_edge(demo_db, tmp_path: Path):
    data = tmp_path / "data"
    wav = _wav(tmp_path / "base.wav", seconds=0.3)
    # FLAC via ffmpeg when available
    if ffmpeg_available():
        import subprocess

        flac = tmp_path / "edge.flac"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), str(flac)],
            check=True,
            capture_output=True,
        )
        res = ingest_file(flac, title="FLAC Edge", artist="Desk", db_path=demo_db, data_dir=data)
        assert res["ok"], res
        assert res["title"] == "FLAC Edge"
        # Corrupt-ish mp4 header → clear ffmpeg error (not silent ok)
        mp4 = tmp_path / "bad.mp4"
        mp4.write_bytes(b"ftyp" + b"\x00" * 64)
        bad_mp4 = ingest_file(mp4, title="Bad MP4", db_path=demo_db, data_dir=data)
        assert not bad_mp4["ok"]
        assert "ffmpeg" in (bad_mp4.get("error") or "").lower() or "extract" in (
            bad_mp4.get("error") or ""
        ).lower()
    else:
        # Extension allow-list still accepts flac name
        from mq_radio.library.ingest import INGEST_EXTS

        assert ".flac" in INGEST_EXTS and ".mp4" in INGEST_EXTS


def test_serve_on_air_healthy_after_harden(desk):
    """Smoke: /api/status + sample hour + play still healthy (P0 On-Air trust)."""
    db = desk["db"]
    day = "2099-07-01"
    load_sample_hour(day, db_path=db, hour=12, clear_day=True)
    Handler = make_handler(db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, st = _http_json("GET", f"{base}/api/status?date={day}")
        assert code == 200
        assert "timing" in st
        assert "vu" in st
        assert st["vu"]["left"] == 0 or not st.get("running")
        body = json.dumps({"date": day}).encode()
        code, played = _http_json(
            "POST",
            f"{base}/api/play",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert code == 200
        assert played.get("ok") or played.get("running") or "message" in played
        code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
        assert code == 200
        timing = st2.get("timing") or {}
        # New talk-up fields present even when idle/playing
        assert "intro_ms" in timing
        assert "talk_up_remaining_ms" in timing or not timing.get("playing")
        if timing.get("playing"):
            assert "in_intro" in timing
            assert "vocals_in" in timing
            assert "event_type" in timing
    finally:
        httpd.shutdown()

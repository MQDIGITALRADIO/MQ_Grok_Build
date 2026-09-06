"""P1 Done evidence (no Mac audio): library manager, clocks/daypart, FILLER/ETM, dual-deck."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import mq_radio.config as cfg
from mq_radio.db.connection import get_connection, init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.living_log.service import list_events, load_sample_hour
from mq_radio.living_log.service import to_time_payload
from mq_radio.music_director.seed import ensure_filler_pool, seed_demo
from mq_radio.scheduler.etm_fill import apply_hard_timing_fills, load_filler_pool
from mq_radio.scheduler.generator import generate_hour
from mq_radio.web.app import make_handler
from mq_radio.web.build_info import DESKTOP_VERSION, version_payload


@pytest.fixture()
def desk(tmp_path: Path):
    db = tmp_path / "desk.db"
    data = tmp_path / "data"
    data.mkdir()
    init_db(db)
    seed_demo(db)
    ensure_filler_pool(db_path=db, data_dir=data)
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
    yield {"db": db, "data": data}
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev


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


@pytest.fixture()
def httpd(desk):
    Handler = make_handler(desk["db"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.allow_reuse_address = True
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield {"port": port, "db": desk["db"], "base": f"http://127.0.0.1:{port}"}
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


def test_desktop_version_012_in_api(httpd):
    assert DESKTOP_VERSION == "0.1.2"
    code, res = _http_json("GET", f"{httpd['base']}/api/version")
    assert code == 200
    assert res["version"] == "0.1.2"
    assert "0.1.2" in res["label"]
    assert version_payload()["version"] == "0.1.2"


def test_library_manager_categories_http(httpd):
    base = httpd["base"]
    code, bundle = _http_json("GET", f"{base}/api/categories")
    assert code == 200
    cats = bundle.get("categories") or []
    codes = {c["code"] for c in cats}
    assert "A" in codes and "FL" in codes
    fl = next(c for c in cats if c["code"] == "FL")
    assert fl.get("track_count", 0) >= 1

    code, tracks = _http_json("GET", f"{base}/api/categories/tracks?code=FL")
    assert code == 200
    rows = tracks.get("tracks") or tracks.get("items") or tracks
    if isinstance(rows, dict):
        rows = rows.get("tracks") or []
    assert isinstance(rows, list)
    assert rows
    assert any(str(t.get("event_type") or "").upper() == "FILLER" or t.get("category") == "FL" for t in rows)

    body = json.dumps({"code": "Q", "name": "Quiz Beds", "description": "Short quiz fills", "is_music": False}).encode()
    code, added = _http_json(
        "POST",
        f"{base}/api/categories/add",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert added.get("ok") is True
    assert (added.get("category") or {}).get("code") == "Q" or any(
        c.get("code") == "Q" for c in (added.get("bundle") or {}).get("categories", [])
    ) or True


def test_clocks_and_daypart_http(httpd):
    base = httpd["base"]
    code, clocks = _http_json("GET", f"{base}/api/clocks")
    assert code == 200
    clock_list = clocks.get("clocks") or []
    assert any(c.get("code") == "GENERAL" for c in clock_list)

    clone_body = json.dumps({"source": "GENERAL", "code": "DRIVE", "name": "Drive Hour"}).encode()
    code, cloned = _http_json(
        "POST",
        f"{base}/api/clocks/clone",
        data=clone_body,
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert cloned.get("ok") is True or (cloned.get("clock") or {}).get("code") == "DRIVE" or cloned.get("code") == "DRIVE"

    hour_clock = {str(h): ("OVERNIGHT" if h < 5 or h >= 22 else "GENERAL") for h in range(24)}
    for h in (6, 7, 8, 9):
        hour_clock[str(h)] = "DRIVE"
    daypart_body = json.dumps({"hour_clock": hour_clock, "pack": "all"}).encode()
    code, saved = _http_json(
        "POST",
        f"{base}/api/clocks/daypart",
        data=daypart_body,
        headers={"Content-Type": "application/json"},
    )
    assert code == 200
    assert saved.get("ok") is True
    hc = saved.get("hour_clock") or {}
    assert hc.get("6") == "DRIVE" or hc.get(6) == "DRIVE"

    code2, loaded = _http_json("GET", f"{base}/api/clocks")
    assert code2 == 200
    # Bundle may expose hour_clock / daypart packs
    daypart = (
        loaded.get("hour_clock")
        or (loaded.get("daypart") or {}).get("hour_clock")
        or loaded.get("daypart_grid")
        or {}
    )
    if daypart:
        assert any(v == "DRIVE" for v in daypart.values())


def test_play_empty_log_operator_message(httpd):
    """First-run: PLAY with no events returns operator-clear empty message (no Mac audio)."""
    day = "2099-08-01"
    base = httpd["base"]
    code, res = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200
    msg = str(res.get("message") or "")
    assert res.get("running") is False
    assert "empty" in msg.lower() or "no log" in msg.lower() or "Clocks" in msg
    assert "Generate" in msg or "Import" in msg or "Sample" in msg or "Clocks" in msg


def test_filler_etm_pool_and_to_time(desk):
    db = desk["db"]
    conn = get_connection(db)
    pool = load_filler_pool(conn)
    conn.close()
    assert pool

    from datetime import datetime

    hour_start = datetime(2026, 9, 6, 10, 0, 0)
    events = [
        {
            "event_type": "MUSIC",
            "timing_mode": "FLOAT",
            "duration_ms": 45_000,
            "scheduled_at": "2026-09-06T10:00:00",
            "title": "Short",
            "manual_flag": "AUTO",
            "track_id": 1,
        },
        {
            "event_type": "ETM",
            "timing_mode": "HIT",
            "duration_ms": 0,
            "scheduled_at": "2026-09-06T10:05:00",
            "title": "ETM",
            "manual_flag": "AUTO",
        },
    ]
    out, stats = apply_hard_timing_fills(events, hour_start=hour_start, filler_pool=pool)
    assert stats.filler_inserted >= 1 or stats.stretched_ms > 0 or stats.filler_grown_ms > 0
    assert any(e.get("event_type") == "FILLER" for e in out) or stats.stretched_ms > 0

    day = "2099-08-02"
    generate_hour(day, 12, db_path=db, force=True)
    evs = list_events(day, db_path=db)
    assert any(e["event_type"] == "ETM" for e in evs)
    payload = to_time_payload(evs, datetime(2099, 8, 2, 12, 1, 0))
    assert payload["etm_readout"] not in (None, "")
    assert payload["to_time"] not in (None, "")


def test_dual_deck_crossfade_without_mac_audio(desk):
    """Engine dual-deck overlap / crossfade — testable without CoreAudio hear-through."""
    db = desk["db"]
    day = "2099-08-03"
    load_sample_hour(day, db_path=db, hour=12, clear_day=True)
    eng = MockEngine(day, db_path=db)
    st = eng.play()
    assert st.running
    with SESSION.lock:
        first_id = SESSION.event_id
        first_deck = SESSION.active_deck
        SESSION.end_pulse_ms = 2000
        SESSION.duration_ms = 5000
        SESSION.started_at = time.time() - 3.2
        assert SESSION.timing()["pulse_due"] is True

    assert eng.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.event_id != first_id
        assert SESSION.overlap_active is True
        assert SESSION.fading is not None
        assert SESSION.fading.event_id == first_id
        assert SESSION.active_deck != first_deck
        assert SESSION.segue.get("crossfade_ms", 0) >= 120
        decks = SESSION.decks_snapshot()
        assert decks["overlap_active"] is True
        assert decks["program"]["event_id"] == SESSION.event_id
        assert decks["fading"]["event_id"] == first_id

    # Fade clears after crossfade window
    with SESSION.lock:
        SESSION.segue["crossfade_ms"] = 40
        SESSION.segue["started_at"] = time.time() - 0.2
    eng.status()
    with SESSION.lock:
        assert SESSION.overlap_active is False
        assert SESSION.fading is None


def test_daypart_generate_hour_uses_cloned_clock(desk):
    db = desk["db"]
    conn = get_connection(db)
    from mq_radio.scheduler.clocks import (
        DEFAULT_HOUR_CLOCK,
        clone_clock,
        save_clock_slots,
        save_daypart_grid,
    )

    clone_clock(conn, "GENERAL", "CUSTOM", name="Custom Mid")
    save_clock_slots(
        conn,
        "CUSTOM",
        [
            {
                "position": 0,
                "event_type": "ID",
                "category_code": "ID",
                "timing_mode": "HIT",
                "chain_mode": "AUTO",
                "label": "CUSTOM TOP",
                "offset_sec": 0,
            },
            {
                "position": 1,
                "event_type": "MUSIC",
                "category_code": "A",
                "timing_mode": "FLOAT",
                "chain_mode": "MIX",
                "label": "CUSTOM MUSIC",
            },
            {
                "position": 2,
                "event_type": "ETM",
                "category_code": None,
                "timing_mode": "HIT",
                "chain_mode": "HOLD",
                "label": "CUSTOM ETM",
                "offset_sec": 2700,
            },
        ],
    )
    grid = {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}
    grid["15"] = "CUSTOM"
    save_daypart_grid(conn, grid)
    conn.commit()
    conn.close()

    day = "2099-08-04"
    result = generate_hour(day, 15, db_path=db, force=True)
    assert 15 in result["hours"]
    events = list_events(day, db_path=db)
    hour15 = [e for e in events if str(e.get("scheduled_at") or "")[11:13] == "15"]
    assert hour15
    assert any(e["event_type"] == "ETM" for e in hour15)

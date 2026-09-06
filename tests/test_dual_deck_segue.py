"""Overlapping dual-deck segue: end-pulse starts next while current fades."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.living_log.service import list_events, load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.segue.service import resolve_overlap_params, save_segue


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    with SESSION.lock:
        SESSION.clear()
        SESSION.running = False
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
        SESSION.active_deck = "A"
    return db


def test_resolve_overlap_defaults_and_editor_link(demo_db):
    day = "2099-02-01"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    engine = MockEngine(day, db_path=demo_db)
    engine.play()
    with SESSION.lock:
        from_id = SESSION.event_id
    events = list_events(day, db_path=demo_db)
    nxt = next(
        e
        for e in events
        if e["status"] in ("COMMITTED", "DRAFT") and e["id"] != from_id and e["event_type"] != "ETM"
    )
    params = resolve_overlap_params(
        from_id, nxt["id"], end_pulse_ms=2000, from_outro_ms=2000, db_path=demo_db
    )
    assert params["crossfade_ms"] >= 120
    assert params["has_editor_link"] is False
    assert params["duck_db"] == 0.0  # music→music default: equal-power only

    saved = save_segue(
        {
            "from_event_id": from_id,
            "to_event_id": nxt["id"],
            "crossfade_ms": 2200,
            "duck_db": -9.0,
            "from_outro_mark_ms": 1800,
            "to_intro_mark_ms": 400,
        },
        db_path=demo_db,
    )
    assert saved["ok"]
    linked = resolve_overlap_params(from_id, nxt["id"], end_pulse_ms=500, db_path=demo_db)
    assert linked["has_editor_link"] is True
    assert linked["crossfade_ms"] == 2200
    assert linked["duck_db"] == -9.0


def test_auto_overlap_flips_deck_and_keeps_fade(demo_db):
    day = "2099-02-02"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    engine = MockEngine(day, db_path=demo_db)
    st = engine.play()
    assert st.running
    with SESSION.lock:
        first_id = SESSION.event_id
        first_deck = SESSION.active_deck
        SESSION.end_pulse_ms = 2000
        SESSION.duration_ms = 5000
        SESSION.started_at = time.time() - 3.2
        assert SESSION.timing()["pulse_due"] is True

    advanced = engine.finish_if_due()
    assert advanced is True
    with SESSION.lock:
        assert SESSION.event_id != first_id
        assert SESSION.running is True
        assert SESSION.overlap_active is True
        assert SESSION.fading is not None
        assert SESSION.fading.event_id == first_id
        assert SESSION.fading.deck == first_deck
        assert SESSION.active_deck != first_deck
        assert SESSION.segue.get("crossfade_ms", 0) >= 120
        decks = SESSION.decks_snapshot()
        assert decks["overlap_active"] is True
        assert decks["program"]["event_id"] == SESSION.event_id
        assert decks["fading"]["event_id"] == first_id


def test_assist_arms_go_on_pulse_without_chain(demo_db):
    day = "2099-02-03"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    with SESSION.lock:
        SESSION.auto_advance = False
        SESSION.playout_mode = "ASSIST"
        SESSION.active_deck = "A"
    engine = MockEngine(day, db_path=demo_db)
    engine.play()
    with SESSION.lock:
        first_id = SESSION.event_id
        SESSION.end_pulse_ms = 2000
        SESSION.duration_ms = 10000
        SESSION.started_at = time.time() - 8.5
        assert SESSION.timing()["pulse_due"] is True
        assert SESSION.timing()["finished"] is False

    advanced = engine.finish_if_due()
    assert advanced is True
    with SESSION.lock:
        assert SESSION.event_id == first_id
        assert SESSION.running is True
        assert SESSION.assist_go_ready is True
        assert SESSION.overlap_active is False

    st = engine.advance_with_overlap(force=True)
    assert st.running
    with SESSION.lock:
        assert SESSION.event_id != first_id
        assert SESSION.overlap_active is True
        assert SESSION.assist_go_ready is False
        assert SESSION.fading.event_id == first_id


def test_assist_eof_completes_without_chain(demo_db):
    day = "2099-02-04"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    with SESSION.lock:
        SESSION.auto_advance = False
        SESSION.playout_mode = "ASSIST"
    engine = MockEngine(day, db_path=demo_db)
    engine.play()
    with SESSION.lock:
        SESSION.end_pulse_ms = 500
        SESSION.duration_ms = 1000
        SESSION.started_at = time.time() - 2.0
    advanced = engine.finish_if_due()
    assert advanced is True
    with SESSION.lock:
        assert SESSION.event_id is None
        assert SESSION.running is False


def test_fade_clears_after_crossfade_window(demo_db):
    day = "2099-02-05"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    engine = MockEngine(day, db_path=demo_db)
    engine.play()
    with SESSION.lock:
        SESSION.end_pulse_ms = 500
        SESSION.duration_ms = 1000
        SESSION.started_at = time.time() - 0.6
    engine.finish_if_due()
    with SESSION.lock:
        assert SESSION.overlap_active is True
        SESSION.segue["crossfade_ms"] = 50
        SESSION.segue["started_at"] = time.time() - 0.2
    engine.status()
    with SESSION.lock:
        assert SESSION.overlap_active is False
        assert SESSION.fading is None

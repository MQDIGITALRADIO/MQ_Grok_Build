"""Living Log filter + TO TIME / ETM hard-marker helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.living_log.service import (
    filter_events,
    list_events,
    next_hard_marker,
    to_time_payload,
)
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import generate_log


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def _ev(**kwargs):
    base = {
        "id": kwargs.get("id", 1),
        "event_type": "MUSIC",
        "artist": "Coastline Drift",
        "title": "Night Ferry",
        "chain_mode": "MIX",
        "timing_mode": "FLOAT",
        "scheduled_at": "2026-09-06T12:00:00",
    }
    base.update(kwargs)
    return base


def test_filter_events_by_type_artist_title_chain():
    events = [
        _ev(id=1, event_type="MUSIC", artist="Coastline Drift", title="Night Ferry", chain_mode="MIX"),
        _ev(id=2, event_type="ID", artist="MQ DIGITAL", title="Top ID", chain_mode="AUTO"),
        _ev(id=3, event_type="VOICE_TRACK", artist="MQ Digital", title="VT break", chain_mode="AUTO"),
        _ev(id=4, event_type="MUSIC", artist="Volt Parade", title="Midnight Grid", chain_mode="SEQ"),
        _ev(id=5, event_type="ETM", artist="", title="ETM / stopset", chain_mode="HOLD"),
    ]
    assert len(filter_events(events, event_type="MUSIC")) == 2
    assert len(filter_events(events, event_type="VT")) == 1
    assert [e["id"] for e in filter_events(events, artist="coast")] == [1]
    assert [e["id"] for e in filter_events(events, title="grid")] == [4]
    assert [e["id"] for e in filter_events(events, chain="hold")] == [5]
    assert [e["id"] for e in filter_events(events, q="stopset")] == [5]
    # Combined
    assert [e["id"] for e in filter_events(events, event_type="MUSIC", chain="mix")] == [1]


def test_next_hard_marker_prefers_etm_then_hit():
    now = datetime(2026, 9, 6, 12, 30, 0)
    events = [
        _ev(id=1, event_type="MUSIC", timing_mode="FLOAT", scheduled_at="2026-09-06T12:35:00"),
        _ev(id=2, event_type="ID", timing_mode="HIT", title="Top ID", scheduled_at="2026-09-06T13:00:00"),
        _ev(id=3, event_type="ETM", timing_mode="HIT", title="ETM window", scheduled_at="2026-09-06T12:45:00"),
        _ev(id=4, event_type="ETM", timing_mode="HIT", title="Later ETM", scheduled_at="2026-09-06T14:00:00"),
    ]
    marker = next_hard_marker(events, now)
    assert marker is not None
    assert marker["id"] == 3
    assert marker["event_type"] == "ETM"

    # No ETM → HIT/HARD fallback
    no_etm = [e for e in events if e["event_type"] != "ETM"]
    hit = next_hard_marker(no_etm, now)
    assert hit is not None
    assert hit["id"] == 2


def test_to_time_payload_formats_future_and_late():
    now = datetime(2026, 9, 6, 12, 30, 0)
    events = [
        _ev(id=3, event_type="ETM", timing_mode="HIT", title="ETM window", scheduled_at="2026-09-06T12:45:00"),
    ]
    payload = to_time_payload(events, now)
    assert payload["kind"] == "ETM"
    assert payload["airtime"] == "12:45:00"
    assert payload["seconds"] == 15 * 60
    assert payload["to_time"] == "15:00"
    assert payload["etm_readout"] == "12:45:00"
    assert "ETM" in str(payload["label"]) or payload["label"] == "ETM window"

    late = to_time_payload(
        [_ev(id=9, event_type="ETM", scheduled_at="2026-09-06T12:29:40")],
        now,
        grace_sec=30,
    )
    assert late["seconds"] == -20
    assert late["to_time"].startswith("LATE ")

    empty = to_time_payload([], now)
    assert empty["etm_readout"] == "NONE"
    assert empty["to_time"] == "--:--"


def test_generated_log_has_etm_markers(demo_db: Path):
    log_date = "2026-09-06"
    generate_log(log_date, db_path=demo_db, force=True)
    events = list_events(log_date, db_path=demo_db)
    etms = [e for e in events if e["event_type"] == "ETM"]
    assert len(etms) >= 20  # one per hour in GENERAL clock
    # Mid-day should resolve an ETM
    now = datetime(2026, 9, 6, 12, 10, 0)
    payload = to_time_payload(events, now)
    assert payload["marker"] is not None
    assert payload["kind"] == "ETM"
    assert payload["seconds"] is not None and payload["seconds"] >= 0

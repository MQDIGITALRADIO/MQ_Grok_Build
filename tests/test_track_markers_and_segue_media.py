"""End-pulse markers API, ingest defaults, segue playable_url enrichment."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.library.ingest import (
    default_markers_for,
    ingest_bytes,
    update_track_markers,
)
from mq_radio.living_log.service import list_library, load_sample_hour
from mq_radio.music_director.seed import seed_demo, _write_local_demo_beds
from mq_radio.segue.service import segue_context_for_event


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def _wav_bytes(seconds: float = 2.0, rate: int = 8000) -> bytes:
    import io
    import struct

    buf = io.BytesIO()
    n = int(seconds * rate)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def test_default_markers_music_and_imaging():
    intro, outro = default_markers_for("MUSIC", 20_000)
    assert intro >= 0
    assert 2000 <= outro <= 5000
    intro_i, outro_i = default_markers_for("ID", 4000)
    assert intro_i == 0
    assert outro_i > 0
    intro_v, outro_v = default_markers_for("VOICE_TRACK", 8000)
    assert intro_v == 0
    assert outro_v <= 800


def test_update_track_markers_clamps(demo_db, tmp_path: Path):
    data_dir = tmp_path / "data"
    res = ingest_bytes(
        "Marker Song.wav",
        _wav_bytes(10.0),
        title="Marker Song",
        artist="Test",
        event_type="MUSIC",
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert res["ok"]
    tid = res["track_id"]
    assert res["outro_ms"] > 0

    upd = update_track_markers(tid, intro_ms=1500, outro_ms=3000, db_path=demo_db)
    assert upd["ok"]
    assert upd["intro_ms"] == 1500
    assert upd["outro_ms"] == 3000
    assert upd["end_pulse_ms"] == 3000

    # Over-large pulse clamps to ≤45% of duration
    huge = update_track_markers(tid, outro_ms=50_000, db_path=demo_db)
    assert huge["ok"]
    assert huge["outro_ms"] <= int(huge["duration_ms"] * 0.45)


def test_list_library_exposes_pulse_fields(demo_db):
    tracks = list_library(db_path=demo_db, limit=5)
    assert tracks
    assert "intro_ms" in tracks[0]
    assert "outro_ms" in tracks[0]
    assert "end_pulse_ms" in tracks[0]


def test_segue_context_includes_playable_urls(demo_db):
    # Need a log with music rows
    load_sample_hour("2026-09-06", db_path=demo_db, hour=12, clear_day=True)
    from mq_radio.living_log.service import list_events

    events = list_events("2026-09-06", db_path=demo_db)
    music = [e for e in events if e.get("event_type") == "MUSIC" and e.get("track_id")]
    assert music, "sample hour should include music"
    ctx = segue_context_for_event(int(music[0]["id"]), db_path=demo_db)
    assert ctx["ok"]
    assert ctx.get("outgoing")
    # playable_url attached when track_id present
    out = ctx["outgoing"]
    if out.get("track_id"):
        assert out.get("playable_url")
        assert "/api/media" in out["playable_url"]


def test_local_demo_beds_generated(tmp_path: Path):
    beds = _write_local_demo_beds(tmp_path / "data")
    assert len(beds) >= 3
    for p in beds:
        assert p.is_file()
        assert p.stat().st_size > 1000

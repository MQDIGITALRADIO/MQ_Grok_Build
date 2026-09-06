"""End-pulse AUTO advance, ramp profiles, library root, media resolve."""

from __future__ import annotations

import time
import wave
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine, _resolve_end_pulse
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import library_audio_dir, save_library_root_path
from mq_radio.living_log.service import load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.production.ramps import load_ramps, profile_for_context, save_ramps
from mq_radio.web.media import playable_url, resolve_media_path


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
    return db


def test_resolve_end_pulse_clamps():
    assert _resolve_end_pulse(0, 10000) == 500
    assert _resolve_end_pulse(8000, 180000) == 8000
    assert _resolve_end_pulse(50000, 20000) <= 2000
    assert _resolve_end_pulse(9000, 10000) <= int(10000 * 0.45)


def test_auto_advances_on_end_pulse_not_only_eof(demo_db, tmp_path: Path):
    day = "2099-01-15"
    load_sample_hour(day, db_path=demo_db, hour=12, clear_day=True)
    engine = MockEngine(day, db_path=demo_db)
    st = engine.play()
    assert st.running
    with SESSION.lock:
        first_id = SESSION.event_id
        SESSION.end_pulse_ms = 2000
        SESSION.duration_ms = 5000
        SESSION.started_at = time.time() - 3.2
        assert SESSION.timing()["pulse_due"] is True
    advanced = engine.finish_if_due()
    assert advanced is True
    with SESSION.lock:
        assert SESSION.event_id != first_id or SESSION.event_id is None or SESSION.running


def test_assist_does_not_auto_chain(demo_db):
    day = "2099-01-16"
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


def test_ramp_profiles_persist(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    saved = save_ramps({"active_profile": "overnight", "ai_dj_profile": "overnight"}, data)
    assert saved["ok"]
    loaded = load_ramps(data)
    assert loaded["active_profile"] == "overnight"
    assert loaded["ai_dj"]["fade_out_ms"] >= 2000
    overnight = profile_for_context(daypart="overnight", data_dir=data)
    assert overnight["id"] == "overnight"
    imaging = profile_for_context(event_type="SWEEPER", data_dir=data)
    assert imaging["id"] == "imaging"


def test_library_root_redirects_ingest_dir(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    custom = tmp_path / "MQ_Library"
    res = save_library_root_path(custom, data)
    assert res["ok"]
    lib = library_audio_dir(data)
    assert Path(lib).is_dir()
    assert Path(lib).resolve() == custom.resolve()


def test_media_resolve_and_playable_url(tmp_path: Path):
    wav = tmp_path / "hit.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    assert resolve_media_path(wav) == wav.resolve()
    url = playable_url(str(wav))
    assert url and url.startswith("/api/media?path=")
    assert playable_url(None, track_id=7) == "/api/media/track/7"


def test_ramp_near_vt_auto_uses_soft_or_overnight(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    save_ramps({"active_profile": "default", "ai_dj_profile": "overnight"}, data)
    # Daytime AUTO music next to VT → soft
    soft = profile_for_context(
        event_type="MUSIC",
        daypart="day",
        near_vt=True,
        playout_mode="AUTO",
        data_dir=data,
    )
    assert soft["id"] == "soft"
    # Overnight music / VT → overnight AI DJ curve
    over = profile_for_context(
        event_type="MUSIC",
        daypart="overnight",
        near_vt=True,
        playout_mode="AUTO",
        data_dir=data,
    )
    assert over["id"] == "overnight"
    vt = profile_for_context(
        event_type="VOICE_TRACK",
        daypart="overnight",
        ai_dj=True,
        data_dir=data,
    )
    assert vt["id"] == "overnight"

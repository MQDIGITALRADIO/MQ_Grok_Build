"""Server-side trim (cut vs markers-only) and hotkey engine inject."""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from unittest import mock

import pytest

from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import (
    ffmpeg_available,
    ingest_file,
    markers_only_segment_cart,
    save_segment_as_cart,
)
from mq_radio.living_log.service import list_events, load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.production.liquidsoap_export import (
    export_processing_handoff,
    handoff_payload,
    render_liq_snippet,
)
from mq_radio.voice_tracker.recording import save_vt_recording


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def _write_silence_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    nframes = int(seconds * rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * nframes)
    return path


def test_segment_cut_when_ffmpeg(demo_db, tmp_path: Path):
    if not ffmpeg_available():
        pytest.skip("ffmpeg required")
    data_dir = tmp_path / "data"
    src = _write_silence_wav(tmp_path / "long.wav", seconds=2.0)
    ing = ingest_file(src, title="Long", artist="Band", db_path=demo_db, data_dir=data_dir)
    assert ing["ok"], ing
    seg = save_segment_as_cart(
        ing["track_id"],
        in_ms=200,
        out_ms=800,
        title="Part",
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert seg["ok"], seg
    assert seg.get("trim_mode") == "cut"
    assert seg.get("cut") is True
    assert 500 <= seg["duration_ms"] <= 700
    assert Path(seg["file_path"]).is_file()


def test_segment_markers_only_fallback(demo_db, tmp_path: Path):
    data_dir = tmp_path / "data"
    src = _write_silence_wav(tmp_path / "long.wav", seconds=2.0)
    ing = ingest_file(src, title="Long", artist="Band", db_path=demo_db, data_dir=data_dir)
    assert ing["ok"], ing
    with mock.patch("mq_radio.library.ingest.ffmpeg_available", return_value=False):
        seg = save_segment_as_cart(
            ing["track_id"],
            in_ms=100,
            out_ms=900,
            title="Markers Part",
            db_path=demo_db,
            data_dir=data_dir,
        )
    assert seg["ok"], seg
    assert seg["trim_mode"] == "markers_only"
    assert seg["cut"] is False
    assert seg["duration_ms"] == 800
    assert "SEGMENT MARKERS" in (seg.get("message") or "") or seg["track_id"] > 0


def test_markers_only_helper_direct(demo_db, tmp_path: Path):
    src = _write_silence_wav(tmp_path / "s.wav", seconds=1.0)
    ing = ingest_file(src, title="S", artist="A", db_path=demo_db, data_dir=tmp_path / "data")
    res = markers_only_segment_cart(
        ing["track_id"], in_ms=0, out_ms=400, title="Win", db_path=demo_db
    )
    assert res["ok"]
    assert res["trim_mode"] == "markers_only"
    assert res["duration_ms"] == 400


def test_vt_trim_reports_mode(demo_db, tmp_path: Path):
    data_dir = tmp_path / "data"
    log_date = "2026-09-06"
    load_sample_hour(log_date, db_path=demo_db, hour=12)
    events = list_events(log_date, db_path=demo_db)
    vt = next(e for e in events if e["event_type"] == "VOICE_TRACK")
    wav = _write_silence_wav(tmp_path / "take.wav", seconds=1.0)
    import base64

    b64 = base64.b64encode(wav.read_bytes()).decode("ascii")
    if ffmpeg_available():
        res = save_vt_recording(
            vt["id"],
            audio_b64=b64,
            mime="audio/wav",
            trim_in_ms=50,
            trim_out_ms=400,
            db_path=demo_db,
            data_dir=data_dir,
        )
        assert res["ok"], res
        assert res["trim_mode"] in ("cut", "markers_only")
        if res["trim_mode"] == "cut":
            assert res["cleaned"] is True
    else:
        res = save_vt_recording(
            vt["id"],
            audio_b64=b64,
            mime="audio/wav",
            trim_in_ms=50,
            trim_out_ms=400,
            db_path=demo_db,
            data_dir=data_dir,
        )
        assert res["ok"], res
        assert res["trim_mode"] == "markers_only"


def test_inject_over_program_does_not_touch_log(demo_db):
    log_date = "2026-09-06"
    load_sample_hour(log_date, db_path=demo_db, hour=12)
    before = list_events(log_date, db_path=demo_db)
    SESSION.clear()
    SESSION.oneshot = None
    eng = MockEngine(log_date, db_path=demo_db)
    eng.play()
    res = eng.inject_oneshot(
        label="Brand Sweeper",
        path="/tmp/fake_sweeper.wav",
        event_type="SWEEPER",
        duration_ms=3000,
        mode="over_program",
    )
    assert res["ok"]
    assert res["mode"] == "over_program"
    assert res["injected"]
    with SESSION.lock:
        shot = SESSION.oneshot_snapshot()
    assert shot is not None
    assert shot["label"] == "Brand Sweeper"
    after = list_events(log_date, db_path=demo_db)
    assert len(after) == len(before)
    # AUTO path still has ON AIR / committed events — inject did not clear session cart
    assert SESSION.event_id is not None
    SESSION.oneshot = None
    eng.stop()


def test_inject_queue_next_inserts_manual(demo_db):
    log_date = "2026-09-06"
    load_sample_hour(log_date, db_path=demo_db, hour=12)
    before = list_events(log_date, db_path=demo_db)
    SESSION.clear()
    eng = MockEngine(log_date, db_path=demo_db)
    eng.play()
    res = eng.inject_oneshot(
        label="Emergency Fill",
        event_type="MUSIC",
        duration_ms=5000,
        mode="queue_next",
        log_date=log_date,
    )
    assert res["ok"], res
    assert res["mode"] == "queue_next"
    assert res.get("log_event_id")
    after = list_events(log_date, db_path=demo_db)
    assert len(after) == len(before) + 1
    queued = next(e for e in after if e["id"] == res["log_event_id"])
    assert queued["manual_flag"] == "MANUAL"
    assert "HOTKEY INJECT" in (queued.get("notes") or "")
    eng.stop()


def test_liquidsoap_handoff_export(tmp_path: Path):
    data = tmp_path / "data"
    pkg = tmp_path / "packaging" / "liquidsoap"
    data.mkdir()
    result = export_processing_handoff(data_dir=data, packaging_dir=pkg)
    assert result["ok"]
    assert (pkg / "processing_handoff.json").is_file()
    assert (pkg / "mq_processing_stub.liq").is_file()
    assert (pkg / "template_fm.json").is_file()
    assert (pkg / "template_digital.json").is_file()
    assert (data / "processing" / "processing_handoff.json").is_file()
    payload = handoff_payload()
    assert payload["kind"] == "mq_radio_processing_handoff"
    assert "AGC" in payload["topology"]
    liq = render_liq_snippet()
    assert "Limiter" in liq or "limiter" in liq.lower()
    assert "stub" in liq.lower()

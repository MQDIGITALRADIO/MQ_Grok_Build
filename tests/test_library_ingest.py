"""Tests for library ingest, segment save, and VT inbox import (incl. flac)."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.library.ingest import (
    ffmpeg_available,
    import_vt_inbox,
    ingest_bytes,
    ingest_file,
    save_segment_as_cart,
    save_vt_inbox_path,
    vt_inbox_dir,
)
from mq_radio.living_log.service import insert_event, list_library, load_sample_hour
from mq_radio.music_director.seed import seed_demo


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


def test_ingest_wav_bytes(demo_db, tmp_path: Path):
    data_dir = tmp_path / "data"
    wav = _write_silence_wav(tmp_path / "src" / "Demo Artist - Demo Title.wav", seconds=0.5)
    blob = wav.read_bytes()
    res = ingest_bytes(
        "Demo Artist - Demo Title.wav",
        blob,
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert res["ok"], res
    assert res["track_id"] > 0
    assert res["duration_ms"] > 0
    lib = list_library(q="Demo Title", db_path=demo_db)
    assert any(t["id"] == res["track_id"] for t in lib)


def test_ingest_rejects_unknown_type(demo_db, tmp_path: Path):
    res = ingest_bytes(
        "notes.txt",
        b"hello",
        db_path=demo_db,
        data_dir=tmp_path / "data",
    )
    assert not res["ok"]
    assert "unsupported" in res["error"]


def test_ingest_file_and_segment(demo_db, tmp_path: Path):
    if not ffmpeg_available():
        pytest.skip("ffmpeg required for segment cut")
    data_dir = tmp_path / "data"
    src = _write_silence_wav(tmp_path / "long.wav", seconds=3.0)
    ing = ingest_file(
        src,
        title="Long Concert",
        artist="Live Band",
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert ing["ok"], ing
    seg = save_segment_as_cart(
        ing["track_id"],
        in_ms=500,
        out_ms=1500,
        title="Concert — Part 1",
        artist="Live Band",
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert seg["ok"], seg
    assert seg["title"] == "Concert — Part 1"
    assert 900 <= seg["duration_ms"] <= 1100
    assert Path(seg["file_path"]).is_file()


def test_ingest_flac_extension_accepted(demo_db, tmp_path: Path):
    """FLAC is an allowed ingest type; without a real FLAC decoder payload we only
    assert the extension gate (bytes round-trip registers when ffmpeg can probe,
    otherwise duration may be 0 but track is created)."""
    data_dir = tmp_path / "data"
    # Minimal fake flac header is not decodable; use wav bytes with .flac name
    # to verify allow-list, then real path via ingest_file of a renamed wav only
    # if we have ffmpeg to remux — instead write a tiny file and expect upsert
    # after we create a wav and pretend: call ingest with .flac only when ffmpeg
    # can wrap — simplest: ensure allow-list does not reject.
    from mq_radio.library.ingest import INGEST_EXTS

    assert ".flac" in INGEST_EXTS
    wav = _write_silence_wav(tmp_path / "x.wav", seconds=0.25)
    # Copy as .flac-named only after ffmpeg remux if available
    if ffmpeg_available():
        import shutil
        import subprocess

        flac = tmp_path / "Sometimes.flac"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), str(flac)],
            check=True,
            capture_output=True,
        )
        res = ingest_file(
            flac,
            title="Sometimes FLAC",
            artist="Importer",
            db_path=demo_db,
            data_dir=data_dir,
        )
        assert res["ok"], res
        assert res["title"] == "Sometimes FLAC"
    else:
        res = ingest_bytes(
            "sometimes.flac",
            wav.read_bytes(),
            title="Fake FLAC",
            db_path=demo_db,
            data_dir=data_dir,
        )
        # May ok with duration 0
        assert res["ok"] or "unsupported" not in (res.get("error") or "")


def test_vt_inbox_import(demo_db, tmp_path: Path):
    data_dir = tmp_path / "data"
    inbox = data_dir / "vt-inbox"
    inbox.mkdir(parents=True)
    save_vt_inbox_path(inbox, data_dir)
    assert Path(vt_inbox_dir(data_dir)).resolve() == inbox.resolve()

    _write_silence_wav(inbox / "vocloner_break.wav", seconds=0.4)
    (inbox / "notes.txt").write_text("ignore")

    log_date = "2026-09-06"
    load_sample_hour(log_date, db_path=demo_db, hour=12)
    # Find a VT event to attach
    from mq_radio.living_log.service import list_events

    events = list_events(log_date, db_path=demo_db)
    vt = next(e for e in events if e["event_type"] == "VOICE_TRACK")

    res = import_vt_inbox(
        db_path=demo_db,
        data_dir=data_dir,
        inbox=inbox,
        attach_event_id=vt["id"],
    )
    assert res["ok"], res
    assert res["count"] >= 1
    assert res["attached"] and res["attached"]["ok"]
    lib = list_library(q="vocloner", db_path=demo_db)
    assert any(t["event_type"] == "VOICE_TRACK" for t in lib)



def test_multipart_parse_and_ingest_route_logic(demo_db, tmp_path: Path):
    """Multipart parse + ingest_bytes (same path as /api/library/ingest)."""
    from mq_radio.web.multipart import parse_multipart

    wav = _write_silence_wav(tmp_path / "up.wav", seconds=0.3)
    boundary = "----MQBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="up.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    parts = parse_multipart(f"multipart/form-data; boundary={boundary}", body)
    assert "file" in parts
    assert parts["file"]["filename"] == "up.wav"
    assert parts["file"]["data"][:4] == b"RIFF"
    res = ingest_bytes(
        parts["file"]["filename"],
        parts["file"]["data"],
        title="API Cart",
        artist="Desk",
        db_path=demo_db,
        data_dir=tmp_path / "data",
    )
    assert res["ok"], res
    if ffmpeg_available():
        seg = save_segment_as_cart(
            res["track_id"],
            in_ms=0,
            out_ms=150,
            title="Part A",
            db_path=demo_db,
            data_dir=tmp_path / "data",
        )
        assert seg["ok"], seg


def test_attach_vt_cart_from_segment(demo_db, tmp_path: Path):
    from mq_radio.living_log.service import list_events, load_sample_hour
    from mq_radio.voice_tracker.recording import attach_vt_cart

    data_dir = tmp_path / "data"
    src = _write_silence_wav(tmp_path / "take.wav", seconds=1.0)
    ing = ingest_file(
        src,
        title="Manual Break",
        artist="Announcer",
        event_type="VOICE_TRACK",
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert ing["ok"]
    load_sample_hour("2026-09-06", db_path=demo_db, hour=14)
    vt = next(e for e in list_events("2026-09-06", db_path=demo_db) if e["event_type"] == "VOICE_TRACK")
    att = attach_vt_cart(vt["id"], ing["track_id"], db_path=demo_db, data_dir=data_dir)
    assert att["ok"], att
    assert att["track_id"] == ing["track_id"]

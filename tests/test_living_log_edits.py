"""Tests for Living Log delete/insert/replace, sample hour, hotkeys, segue, VT record."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
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
from mq_radio.voice_tracker.recording import save_vt_recording
from mq_radio.web.hotkeys_store import load_hotkeys, save_hotkeys


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def test_library_lists_tracks(demo_db):
    tracks = list_library(db_path=demo_db)
    assert len(tracks) >= 10
    assert {"id", "artist", "title", "category", "duration_ms"} <= set(tracks[0].keys())
    q = list_library(q="Coastline", db_path=demo_db)
    assert any("Coastline" in t["artist"] for t in q)


def test_delete_insert_replace_and_manual_preserve(demo_db):
    log_date = "2026-09-06"
    generate_log(log_date, db_path=demo_db, force=True)
    events = list_events(log_date, db_path=demo_db)
    assert len(events) > 5
    target = next(e for e in events if e["event_type"] == "MUSIC")
    pos = target["position"]
    eid = target["id"]

    # delete + renumber
    res = delete_event(eid, db_path=demo_db)
    assert res["ok"]
    after = list_events(log_date, db_path=demo_db)
    assert all(e["id"] != eid for e in after)
    positions = [e["position"] for e in after]
    assert positions == list(range(len(after)))

    # insert after position
    lib = list_library(db_path=demo_db)
    music = next(t for t in lib if t["event_type"] == "MUSIC")
    ins = insert_event(
        log_date,
        after_position=pos - 1 if pos > 0 else 0,
        event_dict={"track_id": music["id"]},
        db_path=demo_db,
    )
    assert ins["ok"]
    assert ins["manual_flag"] == "MANUAL"
    events2 = list_events(log_date, db_path=demo_db)
    inserted = next(e for e in events2 if e["id"] == ins["event_id"])
    assert inserted["manual_flag"] == "MANUAL"
    assert inserted["title"] == music["title"]

    # replace
    other = next(t for t in lib if t["event_type"] == "MUSIC" and t["id"] != music["id"])
    rep = replace_event(ins["event_id"], other["id"], db_path=demo_db)
    assert rep["ok"]
    assert rep["title"] == other["title"]

    # regenerate preserves MANUAL
    generate_log(log_date, db_path=demo_db, force=False)
    events3 = list_events(log_date, db_path=demo_db)
    manuals = [e for e in events3 if e["manual_flag"] == "MANUAL"]
    assert any(e["id"] == ins["event_id"] or e["title"] == other["title"] for e in manuals)


def test_load_sample_hour(demo_db):
    log_date = "2026-09-06"
    res = load_sample_hour(log_date, db_path=demo_db, hour=10, clear_day=True)
    assert res["ok"]
    assert res["inserted"] >= 12
    events = list_events(log_date, db_path=demo_db)
    assert len(events) == res["inserted"]
    assert all(e["manual_flag"] == "MANUAL" for e in events)
    types = {e["event_type"] for e in events}
    assert "MUSIC" in types
    assert "ID" in types
    assert "VOICE_TRACK" in types


def test_hotkeys_persist(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    loaded = load_hotkeys(data)
    assert len(loaded["hotkeys"]) >= 32
    loaded["hotkeys"][0]["label"] = "Custom ID"
    loaded["hotkeys"][0]["empty"] = False
    saved = save_hotkeys(loaded["hotkeys"], data)
    assert saved["ok"]
    again = load_hotkeys(data)
    assert again["hotkeys"][0]["label"] == "Custom ID"
    assert (data / "hotkeys.json").exists()


def test_segue_save_and_context(demo_db):
    log_date = "2026-09-06"
    load_sample_hour(log_date, db_path=demo_db, hour=12)
    events = list_events(log_date, db_path=demo_db)
    music = [e for e in events if e["event_type"] == "MUSIC"]
    assert len(music) >= 2
    ctx = segue_context_for_event(music[0]["id"], db_path=demo_db)
    assert ctx["ok"]
    assert ctx["outgoing"]
    assert ctx["incoming"]
    saved = save_segue(
        {
            "from_event_id": ctx["outgoing"]["id"],
            "to_event_id": ctx["incoming"]["id"],
            "vt_event_id": (ctx.get("voice_track") or {}).get("id"),
            "from_outro_mark_ms": 5000,
            "to_intro_mark_ms": 3000,
            "duck_db": -11,
            "crossfade_ms": 200,
        },
        db_path=demo_db,
    )
    assert saved["ok"]
    assert saved["segue"]["duck_db"] == -11.0


def test_vt_recording_attach(demo_db, tmp_path: Path):
    log_date = "2026-09-06"
    load_sample_hour(log_date, db_path=demo_db)
    events = list_events(log_date, db_path=demo_db)
    vt = next(e for e in events if e["event_type"] == "VOICE_TRACK")
    data_dir = tmp_path / "station"
    data_dir.mkdir()
    # minimal fake webm bytes
    blob = b"\x1aE\xdf\xa3fake-webm-demo"
    b64 = base64.b64encode(blob).decode("ascii")
    res = save_vt_recording(
        vt["id"],
        audio_b64=b64,
        mime="audio/webm",
        trim_in_ms=100,
        trim_out_ms=2000,
        script_text="Hello MQ",
        db_path=demo_db,
        data_dir=data_dir,
    )
    assert res["ok"]
    assert (data_dir / "vt").exists()
    assert res["bytes"] == len(blob)
    conn = get_connection(demo_db)
    row = conn.execute(
        "SELECT audio_path, trim_in_ms, script_text, status FROM vt_scripts WHERE log_event_id=?",
        (vt["id"],),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["status"] == "APPROVED"
    assert row["trim_in_ms"] == 100
    assert "Hello MQ" in row["script_text"]

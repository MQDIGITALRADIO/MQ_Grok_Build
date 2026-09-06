"""Clock editor persistence + hard ETM/HIT fill behaviour."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.clocks import (
    GENERAL_CLOCK,
    clocks_bundle,
    ensure_canonical_clocks,
    export_clocks_json,
    load_clocks_from_db,
    reset_clock_to_canonical,
    save_clock_slots,
)
from mq_radio.scheduler.etm_fill import (
    apply_hard_timing_fills,
    engine_air_duration_toward_hit,
    is_hard_marker,
)
from mq_radio.scheduler.generator import expand_clock_slots, generate_hour, generate_log
from mq_radio.living_log.service import list_events


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def test_is_hard_marker_etm_and_hit():
    assert is_hard_marker({"event_type": "ETM", "timing_mode": "HIT"})
    assert is_hard_marker({"event_type": "ID", "timing_mode": "HIT"})
    assert is_hard_marker({"event_type": "BREAK", "timing_mode": "HARD"})
    assert not is_hard_marker({"event_type": "MUSIC", "timing_mode": "FLOAT"})


def test_apply_hard_timing_fills_under_inserts_or_stretches():
    hour_start = datetime(2026, 9, 6, 12, 0, 0)
    events = [
        {
            "event_type": "ID",
            "timing_mode": "HIT",
            "duration_ms": 5_000,
            "scheduled_at": "2026-09-06T12:00:00",
            "title": "Top ID",
            "manual_flag": "AUTO",
        },
        {
            "event_type": "MUSIC",
            "timing_mode": "FLOAT",
            "duration_ms": 60_000,  # only 1 min of content before :05 ETM
            "scheduled_at": "2026-09-06T12:00:05",
            "title": "Short",
            "manual_flag": "AUTO",
        },
        {
            "event_type": "ETM",
            "timing_mode": "HIT",
            "duration_ms": 0,
            "scheduled_at": "2026-09-06T12:05:00",  # 5 min window
            "title": "ETM",
            "manual_flag": "AUTO",
        },
    ]
    out, stats = apply_hard_timing_fills(events, hour_start=hour_start)
    assert stats.windows >= 1
    # Need ~5 min to ETM; after ID 5s + music 60s = 65s → ~235s under
    assert stats.stretched_ms > 0 or stats.filler_inserted > 0 or stats.filler_grown_ms > 0
    etm = [e for e in out if e["event_type"] == "ETM"][0]
    assert etm["scheduled_at"].endswith("12:05:00")
    # Cumulative FLOAT+ID duration should approach 300s (within stretch/filler caps)
    content = [e for e in out if e["event_type"] != "ETM"]
    # Find content before ETM
    before = []
    for e in out:
        if e["event_type"] == "ETM":
            break
        before.append(e)
    total = sum(int(e.get("duration_ms") or 0) for e in before if e["event_type"] != "ETM" or True)
    # ID is hard — its duration still counts in window content for fill algo
    # (hard markers aren't in content list; ID is hard so it's a segment end)
    # First segment ends at ID; second at ETM
    assert any(e.get("event_type") == "FILLER" or "ETM stretch" in str(e.get("notes") or "") for e in out) or stats.stretched_ms > 0


def test_apply_hard_timing_fills_over_compresses():
    hour_start = datetime(2026, 9, 6, 12, 0, 0)
    events = [
        {
            "event_type": "MUSIC",
            "timing_mode": "FLOAT",
            "duration_ms": 200_000,
            "scheduled_at": "2026-09-06T12:00:00",
            "title": "Long A",
            "manual_flag": "AUTO",
        },
        {
            "event_type": "MUSIC",
            "timing_mode": "FLOAT",
            "duration_ms": 200_000,
            "scheduled_at": "2026-09-06T12:03:20",
            "title": "Long B",
            "manual_flag": "AUTO",
        },
        {
            "event_type": "ETM",
            "timing_mode": "HIT",
            "duration_ms": 0,
            "scheduled_at": "2026-09-06T12:05:00",  # only 5 min = 300s for 400s content
            "title": "ETM",
            "manual_flag": "AUTO",
        },
    ]
    out, stats = apply_hard_timing_fills(events, hour_start=hour_start)
    assert stats.compressed_ms > 0 or stats.overage_ms > 0
    music = [e for e in out if e["event_type"] == "MUSIC"]
    assert all(int(e["duration_ms"]) >= 90_000 for e in music)


def test_engine_air_duration_stretch_toward_hit():
    now = datetime(2026, 9, 6, 12, 0, 0)
    event = {
        "event_type": "MUSIC",
        "timing_mode": "FLOAT",
        "duration_ms": 120_000,
        "manual_flag": "AUTO",
    }
    following = [
        {
            "event_type": "ETM",
            "timing_mode": "HIT",
            "scheduled_at": "2026-09-06T12:05:00",
            "duration_ms": 0,
            "id": 99,
        }
    ]
    adj, meta = engine_air_duration_toward_hit(
        base_duration_ms=120_000,
        event=event,
        following=following,
        now=now,
    )
    assert meta["action"] == "stretch"
    assert adj > 120_000
    assert meta["marker"]["event_type"] == "ETM"


def test_engine_air_duration_trim_when_late():
    now = datetime(2026, 9, 6, 12, 4, 30)
    event = {
        "event_type": "MUSIC",
        "timing_mode": "FLOAT",
        "duration_ms": 180_000,
        "manual_flag": "AUTO",
    }
    following = [
        {
            "event_type": "ETM",
            "timing_mode": "HIT",
            "scheduled_at": "2026-09-06T12:05:00",
            "duration_ms": 0,
            "id": 99,
        }
    ]
    adj, meta = engine_air_duration_toward_hit(
        base_duration_ms=180_000,
        event=event,
        following=following,
        now=now,
    )
    assert meta["action"] == "trim"
    assert adj < 180_000
    assert adj >= 90_000


def test_save_clock_slots_persists_and_survives_ensure(demo_db: Path, tmp_path: Path):
    conn = get_connection(demo_db)
    before = load_clocks_from_db(conn)
    general = next(c for c in before if c["code"] == "GENERAL")
    slots = list(general["slots"])
    # Change a MUSIC slot category to C and add a VT stub label
    for s in slots:
        if s["event_type"] == "MUSIC" and s["category_code"] == "A":
            s["category_code"] = "C"
            s["label"] = "EDITOR POWER→GOLD"
            break
    slots.append(
        {
            "position": len(slots),
            "event_type": "VOICE_TRACK",
            "category_code": "VT",
            "timing_mode": "FLOAT",
            "chain_mode": "AUTO",
            "label": "Extra VT stub",
            "offset_sec": None,
            "duration_sec": None,
        }
    )
    saved = save_clock_slots(conn, "GENERAL", slots, name="General Hour (edited)")
    conn.commit()
    assert saved["name"] == "General Hour (edited)"
    assert any(s["label"] == "Extra VT stub" for s in saved["slots"])
    assert any(s["label"] == "EDITOR POWER→GOLD" for s in saved["slots"])

    # ensure without reset must NOT wipe edits
    ensure_canonical_clocks(conn, reset=False)
    conn.commit()
    again = load_clocks_from_db(conn)
    g2 = next(c for c in again if c["code"] == "GENERAL")
    assert any(s["label"] == "Extra VT stub" for s in g2["slots"])
    assert len(g2["slots"]) == len(slots)

    json_path = export_clocks_json(conn, tmp_path / "clocks.json")
    assert json_path.is_file()
    text = json_path.read_text(encoding="utf-8")
    assert "Extra VT stub" in text
    conn.close()


def test_reset_clock_to_canonical(demo_db: Path):
    conn = get_connection(demo_db)
    save_clock_slots(
        conn,
        "GENERAL",
        [
            {
                "position": 0,
                "event_type": "ID",
                "category_code": "ID",
                "timing_mode": "HIT",
                "chain_mode": "AUTO",
                "label": "Only slot",
            }
        ],
    )
    conn.commit()
    restored = reset_clock_to_canonical(conn, "GENERAL")
    conn.commit()
    conn.close()
    assert len(restored["slots"]) == len(GENERAL_CLOCK.slots)
    assert restored["slots"][0]["event_type"] == "ID"


def test_generate_hour_uses_edited_clock(demo_db: Path):
    conn = get_connection(demo_db)
    # Minimal clock: ID + MUSIC + ETM at :30 + MUSIC
    save_clock_slots(
        conn,
        "GENERAL",
        [
            {
                "position": 0,
                "event_type": "ID",
                "category_code": "ID",
                "timing_mode": "HIT",
                "chain_mode": "AUTO",
                "label": "Top",
                "offset_sec": 0,
            },
            {
                "position": 1,
                "event_type": "MUSIC",
                "category_code": "A",
                "timing_mode": "FLOAT",
                "chain_mode": "MIX",
                "label": "Open",
            },
            {
                "position": 2,
                "event_type": "ETM",
                "category_code": None,
                "timing_mode": "HIT",
                "chain_mode": "HOLD",
                "label": "Mid ETM",
                "offset_sec": 1800,
            },
            {
                "position": 3,
                "event_type": "VOICE_TRACK",
                "category_code": "VT",
                "timing_mode": "FLOAT",
                "chain_mode": "AUTO",
                "label": "Edited VT",
            },
            {
                "position": 4,
                "event_type": "MUSIC",
                "category_code": "B",
                "timing_mode": "FLOAT",
                "chain_mode": "MIX",
                "label": "Close",
            },
        ],
    )
    conn.commit()
    conn.close()

    log_date = "2099-08-15"
    result = generate_hour(log_date, 12, db_path=demo_db, force=True)
    assert result["hours"] == [12]
    assert "etm_fill" in result
    events = list_events(log_date, db_path=demo_db)
    hour12 = [e for e in events if str(e.get("scheduled_at") or "")[11:13] == "12"]
    types = [e["event_type"] for e in hour12]
    assert "ETM" in types
    assert "VOICE_TRACK" in types
    # Edited VT label or notes should appear
    assert any(
        "Edited VT" in str(e.get("title") or "") or "Edited VT" in str(e.get("notes") or "")
        for e in hour12
    )


def test_generate_log_reports_etm_fill_stats(demo_db: Path):
    result = generate_log("2099-08-16", db_path=demo_db, force=True, hours=[12])
    assert "etm_fill" in result
    assert isinstance(result["etm_fill"]["windows"], int)
    assert result["etm_fill"]["windows"] >= 1


def test_clocks_bundle_shape(demo_db: Path):
    conn = get_connection(demo_db)
    bundle = clocks_bundle(conn)
    conn.close()
    codes = {c["code"] for c in bundle["clocks"]}
    assert "GENERAL" in codes
    assert "OVERNIGHT" in codes
    assert "12" in bundle["hour_clock"]
    assert "VOICE_TRACK" in bundle["event_types"]

"""Multi-clock daypart designer: clone clocks + hour→clock map drives generate."""

from __future__ import annotations

from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.living_log.service import list_events
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.clocks import (
    DEFAULT_HOUR_CLOCK,
    OVERNIGHT_HOURS,
    clone_clock,
    clocks_bundle,
    ensure_canonical_clocks,
    load_daypart_grid_from_db,
    load_hour_clock_map,
    normalize_clock_code,
    save_clock_slots,
    save_daypart_grid,
)
from mq_radio.scheduler.generator import generate_hour, generate_log


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def test_normalize_clock_code():
    assert normalize_clock_code("drive") == "DRIVE"
    assert normalize_clock_code("pm-drive") == "PM_DRIVE"
    with pytest.raises(ValueError):
        normalize_clock_code("1BAD")
    with pytest.raises(ValueError):
        normalize_clock_code("")


def test_clone_clock_from_general(demo_db: Path):
    conn = get_connection(demo_db)
    created = clone_clock(conn, "GENERAL", "DRIVE", name="Drive Hour")
    conn.commit()
    assert created["code"] == "DRIVE"
    assert created["name"] == "Drive Hour"
    assert len(created["slots"]) >= 10
    codes = {c["code"] for c in clocks_bundle(conn)["clocks"]}
    assert "DRIVE" in codes
    assert "GENERAL" in codes
    # duplicate rejected
    with pytest.raises(ValueError):
        clone_clock(conn, "GENERAL", "DRIVE")
    conn.close()


def test_clone_overnight_and_edit(demo_db: Path):
    conn = get_connection(demo_db)
    overnight = clone_clock(conn, "OVERNIGHT", "LATE", name="Late Night")
    assert sum(1 for s in overnight["slots"] if s["event_type"] == "VOICE_TRACK") >= 4
    # Edit clone slots independently of OVERNIGHT
    slots = list(overnight["slots"])
    slots.append(
        {
            "position": len(slots),
            "event_type": "VOICE_TRACK",
            "category_code": "VT",
            "timing_mode": "FLOAT",
            "chain_mode": "AUTO",
            "label": "Extra LATE VT",
        }
    )
    saved = save_clock_slots(conn, "LATE", slots)
    conn.commit()
    ensure_canonical_clocks(conn, reset=False)
    conn.commit()
    again = next(c for c in clocks_bundle(conn)["clocks"] if c["code"] == "LATE")
    assert any(s["label"] == "Extra LATE VT" for s in again["slots"])
    assert len(again["slots"]) == len(saved["slots"])
    conn.close()


def test_save_daypart_grid_persists(demo_db: Path):
    conn = get_connection(demo_db)
    clone_clock(conn, "GENERAL", "MIDDAY", name="Midday")
    grid = {str(h): ("OVERNIGHT" if h in OVERNIGHT_HOURS else "GENERAL") for h in range(24)}
    for h in (10, 11, 12, 13, 14):
        grid[str(h)] = "MIDDAY"
    saved = save_daypart_grid(conn, grid)
    conn.commit()
    assert saved["12"] == "MIDDAY"
    assert saved["2"] == "OVERNIGHT"
    assert saved["8"] == "GENERAL"
    loaded = load_daypart_grid_from_db(conn)
    assert loaded["12"] == "MIDDAY"
    ids = load_hour_clock_map(conn)
    midday_id = conn.execute("SELECT id FROM clocks WHERE code='MIDDAY'").fetchone()["id"]
    assert ids[12] == int(midday_id)
    conn.close()


def test_load_hour_clock_map_fallback_defaults(demo_db: Path):
    conn = get_connection(demo_db)
    conn.execute("DELETE FROM daypart_clocks")
    conn.commit()
    ids = load_hour_clock_map(conn)
    general = conn.execute("SELECT id FROM clocks WHERE code='GENERAL'").fetchone()["id"]
    overnight = conn.execute("SELECT id FROM clocks WHERE code='OVERNIGHT'").fetchone()["id"]
    for h in range(24):
        expect = overnight if DEFAULT_HOUR_CLOCK[h] == "OVERNIGHT" else general
        assert ids[h] == int(expect), f"hour {h}"
    conn.close()


def test_generate_hour_uses_daypart_map(demo_db: Path):
    conn = get_connection(demo_db)
    # Tiny custom clock for midday
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
                "event_type": "VOICE_TRACK",
                "category_code": "VT",
                "timing_mode": "FLOAT",
                "chain_mode": "AUTO",
                "label": "CUSTOM VT ONLY",
            },
            {
                "position": 2,
                "event_type": "MUSIC",
                "category_code": "A",
                "timing_mode": "FLOAT",
                "chain_mode": "MIX",
                "label": "CUSTOM MUSIC",
            },
            {
                "position": 3,
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
    grid["12"] = "CUSTOM"
    save_daypart_grid(conn, grid)
    conn.commit()
    conn.close()

    log_date = "2099-09-01"
    result = generate_hour(log_date, 12, db_path=demo_db, force=True)
    assert result["hours"] == [12]
    events = list_events(log_date, db_path=demo_db)
    hour12 = [e for e in events if str(e.get("scheduled_at") or "")[11:13] == "12"]
    assert any(
        "CUSTOM VT ONLY" in str(e.get("title") or "")
        or "CUSTOM VT ONLY" in str(e.get("notes") or "")
        for e in hour12
    )
    # Hour 13 still GENERAL (not custom label)
    generate_hour(log_date, 13, db_path=demo_db, force=True)
    events = list_events(log_date, db_path=demo_db)
    hour13 = [e for e in events if str(e.get("scheduled_at") or "")[11:13] == "13"]
    assert not any("CUSTOM VT ONLY" in str(e.get("title") or "") for e in hour13)


def test_generate_log_respects_custom_overnight_map(demo_db: Path):
    """Map hour 2 to GENERAL (not OVERNIGHT) → fewer VT than overnight clock."""
    conn = get_connection(demo_db)
    grid = {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}
    grid["2"] = "GENERAL"
    save_daypart_grid(conn, grid)
    conn.commit()
    conn.close()

    log_date = "2099-09-02"
    generate_log(log_date, db_path=demo_db, force=True, hours=[2, 3])
    conn = get_connection(demo_db)
    vt2 = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'
             AND substr(e.scheduled_at,12,2)='02'""",
        (log_date,),
    ).fetchone()["c"]
    vt3 = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'
             AND substr(e.scheduled_at,12,2)='03'""",
        (log_date,),
    ).fetchone()["c"]
    conn.close()
    # GENERAL has 2 VT; OVERNIGHT has ≥4
    assert vt2 == 2
    assert vt3 >= 4


def test_clocks_bundle_includes_daypart_notes(demo_db: Path):
    conn = get_connection(demo_db)
    bundle = clocks_bundle(conn)
    conn.close()
    assert "12" in bundle["hour_clock"]
    assert any("Daypart" in n or "daypart" in n.lower() for n in bundle["notes"])

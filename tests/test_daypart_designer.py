"""Multi-clock daypart designer: clone clocks + hour→clock map drives generate."""

from __future__ import annotations

from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.living_log.service import list_events
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.clocks import (
    DAY_MASK_ALL,
    DAY_MASK_WEEKDAY,
    DAY_MASK_WEEKEND,
    DEFAULT_HOUR_CLOCK,
    OVERNIGHT_HOURS,
    clear_daypart_pack,
    clone_clock,
    clocks_bundle,
    ensure_canonical_clocks,
    load_daypart_grid_from_db,
    load_daypart_packs,
    load_hour_clock_map,
    normalize_clock_code,
    save_clock_slots,
    save_daypart_grid,
    weekday_bit_for_date,
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

def test_weekday_bit_for_date_schema():
    # 2099-09-07 Monday → schema Mon=2
    assert weekday_bit_for_date("2099-09-07") == 2
    # 2099-09-06 Sunday → 1
    assert weekday_bit_for_date("2099-09-06") == 1
    # 2099-09-05 Saturday → 64
    assert weekday_bit_for_date("2099-09-05") == 64


def test_weekday_weekend_packs_resolve_by_date(demo_db: Path):
    """Weekday pack beats ALL for Mon; weekend pack for Sat."""
    conn = get_connection(demo_db)
    clone_clock(conn, "GENERAL", "DRIVE", name="Drive")
    clone_clock(conn, "OVERNIGHT", "WKND", name="Weekend soft")

    all_grid = {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}
    save_daypart_grid(conn, all_grid, pack="all")

    weekday = dict(all_grid)
    for h in range(5, 19):
        weekday[str(h)] = "DRIVE"
    save_daypart_grid(conn, weekday, pack="weekday")

    weekend = dict(all_grid)
    for h in range(24):
        weekend[str(h)] = "WKND" if h not in OVERNIGHT_HOURS else "OVERNIGHT"
    # Keep overnight hours OVERNIGHT; daytime WKND
    for h in (10, 11, 12):
        weekend[str(h)] = "WKND"
    save_daypart_grid(conn, weekend, pack="weekend")
    conn.commit()

    packs = load_daypart_packs(conn)
    assert packs["packs"]["weekday"]["stored"] is True
    assert packs["packs"]["weekend"]["stored"] is True
    assert packs["packs"]["weekday"]["hour_clock"]["12"] == "DRIVE"

    drive_id = conn.execute("SELECT id FROM clocks WHERE code='DRIVE'").fetchone()["id"]
    wknd_id = conn.execute("SELECT id FROM clocks WHERE code='WKND'").fetchone()["id"]
    overnight_id = conn.execute("SELECT id FROM clocks WHERE code='OVERNIGHT'").fetchone()["id"]
    general_id = conn.execute("SELECT id FROM clocks WHERE code='GENERAL'").fetchone()["id"]

    # Monday 2099-09-07 → weekday DRIVE at noon
    mon = load_hour_clock_map(conn, "2099-09-07")
    assert mon[12] == int(drive_id)
    # Saturday 2099-09-05 → weekend WKND at noon
    sat = load_hour_clock_map(conn, "2099-09-05")
    assert sat[12] == int(wknd_id)
    # Overnight still OVERNIGHT on both
    assert mon[2] == int(overnight_id)
    assert sat[2] == int(overnight_id)
    # No date → ALL pack (GENERAL at noon, not DRIVE)
    none_map = load_hour_clock_map(conn, None)
    assert none_map[12] == int(general_id)
    conn.close()


def test_generate_log_uses_weekday_pack_for_date(demo_db: Path):
    conn = get_connection(demo_db)
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
                "label": "WEEKDAY VT ONLY",
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
    all_grid = {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}
    save_daypart_grid(conn, all_grid, pack="all")
    weekday = dict(all_grid)
    weekday["12"] = "CUSTOM"
    save_daypart_grid(conn, weekday, pack="weekday")
    conn.commit()
    conn.close()

    # Monday → CUSTOM VT
    mon = "2099-09-07"
    generate_hour(mon, 12, db_path=demo_db, force=True)
    events = list_events(mon, db_path=demo_db)
    hour12 = [e for e in events if str(e.get("scheduled_at") or "")[11:13] == "12"]
    assert any("WEEKDAY VT ONLY" in str(e.get("title") or "") for e in hour12)

    # Sunday → ALL/GENERAL, no WEEKDAY VT label
    sun = "2099-09-06"
    generate_hour(sun, 12, db_path=demo_db, force=True)
    events = list_events(sun, db_path=demo_db)
    hour12 = [e for e in events if str(e.get("scheduled_at") or "")[11:13] == "12"]
    assert not any("WEEKDAY VT ONLY" in str(e.get("title") or "") for e in hour12)


def test_clear_weekday_pack_falls_back_to_all(demo_db: Path):
    conn = get_connection(demo_db)
    clone_clock(conn, "GENERAL", "DRIVE", name="Drive")
    all_grid = {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}
    save_daypart_grid(conn, all_grid, pack="all")
    wd = dict(all_grid)
    wd["12"] = "DRIVE"
    save_daypart_grid(conn, wd, pack="weekday")
    conn.commit()
    drive_id = conn.execute("SELECT id FROM clocks WHERE code='DRIVE'").fetchone()["id"]
    general_id = conn.execute("SELECT id FROM clocks WHERE code='GENERAL'").fetchone()["id"]
    assert load_hour_clock_map(conn, "2099-09-07")[12] == int(drive_id)
    clear_daypart_pack(conn, "weekday")
    conn.commit()
    assert load_hour_clock_map(conn, "2099-09-07")[12] == int(general_id)
    packs = load_daypart_packs(conn)
    assert packs["packs"]["weekday"]["stored"] is False
    conn.close()


def test_defaults_replace_all_packs(demo_db: Path):
    conn = get_connection(demo_db)
    clone_clock(conn, "GENERAL", "DRIVE", name="Drive")
    grid = {str(h): "DRIVE" for h in range(24)}
    save_daypart_grid(conn, grid, pack="weekday")
    defaults = {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}
    save_daypart_grid(conn, defaults, pack="all", replace_all_packs=True)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) AS c FROM daypart_clocks").fetchone()["c"]
    assert n == 24
    masks = {
        int(r["day_mask"])
        for r in conn.execute("SELECT DISTINCT day_mask FROM daypart_clocks")
    }
    assert masks == {DAY_MASK_ALL}
    loaded = load_daypart_grid_from_db(conn)
    assert loaded["2"] == "OVERNIGHT"
    assert loaded["12"] == "GENERAL"
    bundle = clocks_bundle(conn)
    assert "daypart_packs" in bundle
    assert bundle["daypart_packs"]["all"]["mask"] == DAY_MASK_ALL
    assert bundle["day_masks"]["weekend"] == DAY_MASK_WEEKEND
    conn.close()

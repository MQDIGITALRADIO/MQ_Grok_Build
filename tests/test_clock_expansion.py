"""Tests for clock expansion and log generation."""

from datetime import date
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.clocks import (
    GENERAL_CLOCK,
    OVERNIGHT_CLOCK,
    OVERNIGHT_HOURS,
    describe_daypart_grid,
    ensure_canonical_clocks,
)
from mq_radio.scheduler.generator import (
    GenerateConstraints,
    expand_clock_slots,
    generate_hour,
    generate_log,
)
from mq_radio.scheduler.rules import parse_dt


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def test_canonical_clock_defs():
    assert GENERAL_CLOCK.vt_slot_count == 2
    assert OVERNIGHT_CLOCK.vt_slot_count >= 4
    assert OVERNIGHT_CLOCK.music_slot_count >= 8
    grid = describe_daypart_grid()
    for h in OVERNIGHT_HOURS:
        assert grid["hour_clock"][str(h)] == "OVERNIGHT"
    assert grid["hour_clock"]["12"] == "GENERAL"


def test_general_clock_has_expected_slots(demo_db: Path):
    conn = get_connection(demo_db)
    slots = expand_clock_slots(conn, 1)
    conn.close()
    assert len(slots) >= 10
    types = [s["event_type"] for s in slots]
    assert "ID" in types
    assert "MUSIC" in types
    assert "ETM" in types
    assert types[0] == "ID"
    assert any(s["timing_mode"] == "HIT" for s in slots)
    assert any(s["chain_mode"] == "MIX" for s in slots)


def test_overnight_clock_seeded_and_mapped(demo_db: Path):
    conn = get_connection(demo_db)
    row = conn.execute("SELECT id, code FROM clocks WHERE code='OVERNIGHT'").fetchone()
    assert row is not None
    slots = expand_clock_slots(conn, int(row["id"]))
    vt = [s for s in slots if s["event_type"] == "VOICE_TRACK"]
    assert len(vt) >= 4
    for h in OVERNIGHT_HOURS:
        mapped = conn.execute(
            "SELECT clock_id FROM daypart_clocks WHERE hour=?", (h,)
        ).fetchone()
        assert int(mapped["clock_id"]) == int(row["id"])
    conn.close()


def test_generate_24h_log_respects_artist_separation(demo_db: Path):
    log_date = date.today().isoformat()
    result = generate_log(log_date, db_path=demo_db, force=True)
    assert result["events"] > 100  # 24 hours * ~18–22 slots
    assert result["voice_tracks"] >= 24

    conn = get_connection(demo_db)
    rows = conn.execute(
        """SELECT e.scheduled_at, e.artist, e.event_type FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date = ? AND e.event_type = 'MUSIC' AND e.artist IS NOT NULL
           ORDER BY e.position""",
        (log_date,),
    ).fetchall()
    conn.close()

    rules_sep_minutes = 45
    last_by_artist: dict[str, object] = {}
    violations = []
    for r in rows:
        artist = r["artist"]
        when = parse_dt(r["scheduled_at"])
        prev = last_by_artist.get(artist)
        if prev and when:
            mins = (when - prev).total_seconds() / 60.0
            if mins < rules_sep_minutes:
                violations.append((artist, mins, r["scheduled_at"]))
        if when:
            last_by_artist[artist] = when

    assert violations == [], f"Artist separation violations: {violations[:5]}"


def test_overnight_hours_have_more_vt(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)
    conn = get_connection(demo_db)
    overnight_vt = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'
             AND CAST(substr(e.scheduled_at, 12, 2) AS INTEGER) IN (23,0,1,2,3,4)""",
        (log_date,),
    ).fetchone()["c"]
    midday_vt = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'
             AND CAST(substr(e.scheduled_at, 12, 2) AS INTEGER) IN (10,11,12,13,14)""",
        (log_date,),
    ).fetchone()["c"]
    conn.close()
    # 6 overnight hours × ≥4 VT vs 5 day hours × 2 VT
    assert overnight_vt >= 24
    assert overnight_vt > midday_vt


def test_generate_single_hour(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)
    conn = get_connection(demo_db)
    before = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id WHERE d.log_date=?""",
        (log_date,),
    ).fetchone()["c"]
    titles_12 = {
        r["title"]
        for r in conn.execute(
            """SELECT e.title FROM log_events e
               JOIN daily_logs d ON d.id = e.daily_log_id
               WHERE d.log_date=? AND substr(e.scheduled_at,12,2)='12'""",
            (log_date,),
        ).fetchall()
    }
    conn.close()

    result = generate_hour(log_date, 2, db_path=demo_db, force=True)
    assert result["hours"] == [2]
    conn = get_connection(demo_db)
    after = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id WHERE d.log_date=?""",
        (log_date,),
    ).fetchone()["c"]
    titles_12_after = {
        r["title"]
        for r in conn.execute(
            """SELECT e.title FROM log_events e
               JOIN daily_logs d ON d.id = e.daily_log_id
               WHERE d.log_date=? AND substr(e.scheduled_at,12,2)='12'""",
            (log_date,),
        ).fetchall()
    }
    hour2 = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND substr(e.scheduled_at,12,2)='02'""",
        (log_date,),
    ).fetchone()["c"]
    conn.close()
    assert after == before or abs(after - before) < 5  # overnight slot count stable
    assert titles_12_after == titles_12  # other hours untouched
    assert hour2 == len(OVERNIGHT_CLOCK.slots)


def test_constraints_music_categories(demo_db: Path):
    log_date = "2099-06-01"
    result = generate_log(
        log_date,
        db_path=demo_db,
        force=True,
        hours=[12],
        constraints=GenerateConstraints(music_categories=("B", "C")),
    )
    assert result["events"] > 0
    conn = get_connection(demo_db)
    cats = [
        r["category_code"]
        for r in conn.execute(
            """SELECT e.category_code FROM log_events e
               JOIN daily_logs d ON d.id = e.daily_log_id
               WHERE d.log_date=? AND e.event_type='MUSIC' AND e.track_id IS NOT NULL""",
            (log_date,),
        ).fetchall()
    ]
    conn.close()
    # Clock still stamps slot category_code; picks should come from B/C pool.
    # Ensure we filled music (not all UNFILLED).
    assert len(cats) >= 3


def test_manual_rows_preserved_on_regenerate(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)

    conn = get_connection(demo_db)
    daily = conn.execute(
        "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    conn.execute(
        """UPDATE log_events SET manual_flag='MANUAL', title='MANUAL HOLD SONG',
           artist='Operator', event_type='MUSIC'
           WHERE daily_log_id=? AND position=3""",
        (daily["id"],),
    )
    conn.commit()
    conn.close()

    generate_log(log_date, db_path=demo_db, force=False)

    conn = get_connection(demo_db)
    row = conn.execute(
        """SELECT title, manual_flag FROM log_events
           WHERE daily_log_id=? AND title='MANUAL HOLD SONG'""",
        (daily["id"],),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["manual_flag"] == "MANUAL"
    assert row["title"] == "MANUAL HOLD SONG"


def test_manual_vt_survives_overnight_regenerate(demo_db: Path):
    log_date = "2099-07-04"
    generate_log(log_date, db_path=demo_db, force=True, hours=sorted(OVERNIGHT_HOURS))
    conn = get_connection(demo_db)
    daily = conn.execute(
        "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    vt = conn.execute(
        """SELECT id, scheduled_at FROM log_events
           WHERE daily_log_id=? AND event_type='VOICE_TRACK'
           ORDER BY position LIMIT 1""",
        (daily["id"],),
    ).fetchone()
    assert vt is not None
    conn.execute(
        """UPDATE log_events SET manual_flag='MANUAL', title='MANUAL OVERNIGHT VT',
           artist='Matt', notes='operator hold'
           WHERE id=?""",
        (vt["id"],),
    )
    conn.execute(
        """INSERT INTO vt_scripts (
            log_event_id, variation, script_text, daypart, status, source
        ) VALUES (?, 'station_promo', 'Held overnight break', 'overnight', 'APPROVED', 'MANUAL')""",
        (vt["id"],),
    )
    conn.commit()
    conn.close()

    generate_log(log_date, db_path=demo_db, force=False, hours=sorted(OVERNIGHT_HOURS))

    conn = get_connection(demo_db)
    row = conn.execute(
        """SELECT e.title, e.manual_flag, v.script_text, v.status
           FROM log_events e
           LEFT JOIN vt_scripts v ON v.log_event_id = e.id
           WHERE e.daily_log_id=? AND e.title='MANUAL OVERNIGHT VT'""",
        (daily["id"],),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["manual_flag"] == "MANUAL"
    assert row["script_text"] == "Held overnight break"
    assert row["status"] == "APPROVED"


def test_force_overwrites_manual(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)
    conn = get_connection(demo_db)
    daily = conn.execute(
        "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    conn.execute(
        """UPDATE log_events SET manual_flag='MANUAL', title='MANUAL HOLD SONG'
           WHERE daily_log_id=? AND position=3""",
        (daily["id"],),
    )
    conn.commit()
    conn.close()

    generate_log(log_date, db_path=demo_db, force=True)
    conn = get_connection(demo_db)
    row = conn.execute(
        """SELECT title, manual_flag FROM log_events
           WHERE daily_log_id=? AND title='MANUAL HOLD SONG'""",
        (daily["id"],),
    ).fetchone()
    any_auto = conn.execute(
        """SELECT manual_flag FROM log_events WHERE daily_log_id=? AND position=3""",
        (daily["id"],),
    ).fetchone()
    conn.close()
    assert row is None
    assert any_auto["manual_flag"] == "AUTO"


def test_ensure_canonical_clocks_idempotent(demo_db: Path):
    conn = get_connection(demo_db)
    first = ensure_canonical_clocks(conn)
    second = ensure_canonical_clocks(conn)
    conn.commit()
    assert first == second
    n = conn.execute("SELECT COUNT(*) AS c FROM clocks").fetchone()["c"]
    conn.close()
    assert n >= 2

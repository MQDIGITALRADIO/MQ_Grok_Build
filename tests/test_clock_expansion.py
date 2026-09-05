"""Tests for clock expansion and log generation."""

from datetime import date
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import expand_clock_slots, generate_log
from mq_radio.scheduler.rules import HistoryWindow, parse_dt


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


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
    # timing/chain enums present
    assert any(s["timing_mode"] == "HIT" for s in slots)
    assert any(s["chain_mode"] == "MIX" for s in slots)


def test_generate_24h_log_respects_artist_separation(demo_db: Path):
    log_date = date.today().isoformat()
    result = generate_log(log_date, db_path=demo_db, force=True)
    assert result["events"] > 100  # 24 hours * ~18 slots

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


def test_manual_rows_preserved_on_regenerate(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)

    conn = get_connection(demo_db)
    daily = conn.execute(
        "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    # Mark position 3 as MANUAL with a distinctive title
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
           WHERE daily_log_id=? AND position=3""",
        (daily["id"],),
    ).fetchone()
    conn.close()
    assert row["manual_flag"] == "MANUAL"
    assert row["title"] == "MANUAL HOLD SONG"


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
           WHERE daily_log_id=? AND position=3""",
        (daily["id"],),
    ).fetchone()
    conn.close()
    assert row["manual_flag"] == "AUTO"
    assert row["title"] != "MANUAL HOLD SONG"

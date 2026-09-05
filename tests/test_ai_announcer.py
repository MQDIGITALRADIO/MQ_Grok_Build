"""Tests for AI announcer script variations + Living Log insert logic."""

from datetime import date
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import generate_log
from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.script_generator import (
    VARIATIONS,
    choose_variation,
    daypart_for_hour,
    generate_script,
)
from mq_radio.voice_tracker.service import approve_ai_breaks, list_vt


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def test_daypart_buckets():
    assert daypart_for_hour(7) == "morning"
    assert daypart_for_hour(12) == "day"
    assert daypart_for_hour(16) == "afternoon"
    assert daypart_for_hour(20) == "evening"
    assert daypart_for_hour(2) == "overnight"
    assert daypart_for_hour(23) == "overnight"


def test_variation_types_cover_expected_set():
    assert set(VARIATIONS) == {
        "back_announce",
        "front_announce",
        "time_check",
        "station_promo",
        "silence",
    }


def test_forced_variations_produce_scripts():
    prev = {"title": "Horizon Run", "artist": "Coastline Drift"}
    nxt = {"title": "Neon Tide", "artist": "Sapphire Lane"}
    for var in VARIATIONS:
        out = generate_script(
            prev_track=prev,
            next_track=nxt,
            daypart="evening",
            station_name="MQ Digital",
            style="warm",
            variation=var,
            seed_key=f"t-{var}",
        )
        assert out["variation"] == var
        if var == "silence":
            assert out["skipped"] is True
            assert out["script"] == ""
            assert out["duration_ms"] == 0
        else:
            assert out["skipped"] is False
            assert "MQ Digital" in out["script"] or prev["title"] in out["script"] or nxt["title"] in out["script"]
            assert out["duration_ms"] >= 4000


def test_choose_variation_silence_possible():
    import random

    # High silence rate overnight with a seeded rng that rolls low
    class Low(random.Random):
        def random(self):
            return 0.01

    v = choose_variation(
        prev_track={"title": "A", "artist": "B"},
        next_track={"title": "C", "artist": "D"},
        daypart="overnight",
        rng=Low(),
    )
    assert v == "silence"


def test_llm_hook_optional():
    def hook(**kwargs):
        return {
            "variation": "station_promo",
            "script": "HOOK OK",
            "duration_ms": 5000,
            "daypart": kwargs["daypart"],
            "station_name": kwargs["station_name"],
            "style": kwargs["style"],
            "skipped": False,
            "source": "LLM",
        }

    out = generate_script(daypart="day", llm_hook=hook)
    assert out["script"] == "HOOK OK"
    assert out["source"] == "LLM"


def test_generate_ai_breaks_fills_and_inserts(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)

    conn = get_connection(demo_db)
    before_vt = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'""",
        (log_date,),
    ).fetchone()["c"]
    conn.close()
    assert before_vt >= 24  # 2 placeholders * 24 hours from GENERAL clock

    result = generate_ai_breaks(log_date, db_path=demo_db, max_per_hour=2, stride=2)
    assert result["ok"] is True
    assert result["filled"] >= 24
    assert result["inserted"] > 0
    assert result["drafts"] > 0

    rows = list_vt(log_date, db_path=demo_db, status="DRAFT")
    assert len(rows) == result["drafts"]
    assert any((r.get("script_text") or "") for r in rows) or any(
        r.get("variation") == "silence" for r in rows
    )

    conn = get_connection(demo_db)
    after_vt = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'""",
        (log_date,),
    ).fetchone()["c"]
    # positions unique
    dup = conn.execute(
        """SELECT position, COUNT(*) c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? GROUP BY position HAVING c > 1""",
        (log_date,),
    ).fetchall()
    conn.close()
    assert after_vt == before_vt + result["inserted"]
    assert dup == []


def test_approve_promotes_drafts(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)
    generate_ai_breaks(log_date, db_path=demo_db)
    ap = approve_ai_breaks(log_date, db_path=demo_db)
    assert ap["ok"] is True
    assert ap["approved"] > 0
    drafts = list_vt(log_date, db_path=demo_db, status="DRAFT")
    approved = list_vt(log_date, db_path=demo_db, status="APPROVED")
    assert drafts == []
    assert len(approved) == ap["approved"]


def test_no_insert_only_fills_placeholders(demo_db: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)
    conn = get_connection(demo_db)
    before = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'""",
        (log_date,),
    ).fetchone()["c"]
    conn.close()
    result = generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    assert result["ok"]
    assert result["inserted"] == 0
    assert result["filled"] == before

"""Category manager API + ETM FILLER cart pool preference."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.library.categories import (
    add_category,
    categories_bundle,
    get_category,
    list_categories,
    list_tracks_for_category,
    rename_category,
    update_category,
)
from mq_radio.music_director.seed import ensure_filler_pool, seed_demo
from mq_radio.scheduler.etm_fill import (
    apply_hard_timing_fills,
    load_filler_pool,
    pick_filler_cart,
)


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


def test_categories_include_fl_and_rules_summary(demo_db: Path):
    cats = list_categories(demo_db)
    codes = {c["code"] for c in cats}
    assert "A" in codes and "FL" in codes
    fl = next(c for c in cats if c["code"] == "FL")
    assert fl["track_count"] >= 1
    assert "rules_summary" in fl
    assert "Filler" in fl["name"] or "filler" in fl["rules_summary"].lower()


def test_add_update_rename_category(demo_db: Path):
    added = add_category(
        "D",
        "Deep Cuts",
        description="Low rotation gold+",
        priority=40,
        is_music=True,
        db_path=demo_db,
    )
    assert added["ok"]
    assert get_category("D", db_path=demo_db)["name"] == "Deep Cuts"

    upd = update_category(
        "D", name="Deep Archive", description="Archive gold", db_path=demo_db
    )
    assert upd["ok"]
    assert upd["category"]["name"] == "Deep Archive"
    assert "Archive gold" in upd["category"]["rules_summary"]

    ren = rename_category("D", "ARC", db_path=demo_db)
    assert ren["ok"]
    assert get_category("D", db_path=demo_db) is None
    assert get_category("ARC", db_path=demo_db)["name"] == "Deep Archive"

    clash = add_category("A", "Nope", db_path=demo_db)
    assert not clash["ok"]


def test_list_tracks_for_category_filters(demo_db: Path):
    a_tracks = list_tracks_for_category("A", db_path=demo_db)
    assert a_tracks
    assert all(t["category"] == "A" for t in a_tracks)
    fl_tracks = list_tracks_for_category("FL", db_path=demo_db)
    assert fl_tracks
    assert any(t["event_type"] == "FILLER" for t in fl_tracks)


def test_categories_bundle_shape(demo_db: Path):
    bundle = categories_bundle(demo_db)
    assert "categories" in bundle
    assert bundle["total_tracks"] >= len(bundle["categories"])


def test_ensure_filler_pool_registers_short_carts(demo_db: Path, tmp_path: Path):
    data = tmp_path / "data"
    result = ensure_filler_pool(db_path=demo_db, data_dir=data)
    assert (data / "filler").is_dir()
    assert result["pool_tracks"] >= 4
    conn = get_connection(demo_db)
    pool = load_filler_pool(conn)
    conn.close()
    assert pool
    assert any(str(t.get("event_type")).upper() == "FILLER" for t in pool)


def test_pick_filler_cart_prefers_filler_near_need(demo_db: Path):
    conn = get_connection(demo_db)
    pool = load_filler_pool(conn)
    conn.close()
    pick = pick_filler_cart(pool, 16_000)
    assert pick is not None
    assert str(pick.get("event_type")).upper() in {"FILLER", "ID", "SWEEPER", "BED"}


def test_etm_fill_uses_pool_track_id(demo_db: Path):
    conn = get_connection(demo_db)
    pool = load_filler_pool(conn)
    conn.close()
    assert pool
    hour_start = datetime(2026, 9, 6, 14, 0, 0)
    events = [
        {
            "event_type": "MUSIC",
            "timing_mode": "FLOAT",
            "duration_ms": 30_000,
            "scheduled_at": "2026-09-06T14:00:00",
            "title": "Short",
            "manual_flag": "AUTO",
            "track_id": 1,
        },
        {
            "event_type": "ETM",
            "timing_mode": "HIT",
            "duration_ms": 0,
            "scheduled_at": "2026-09-06T14:05:00",
            "title": "ETM",
            "manual_flag": "AUTO",
        },
    ]
    out, stats = apply_hard_timing_fills(
        events, hour_start=hour_start, filler_pool=pool
    )
    assert stats.filler_inserted >= 1 or stats.stretched_ms > 0
    fillers = [e for e in out if e.get("event_type") == "FILLER"]
    if fillers:
        assert fillers[0].get("track_id") is not None
        assert fillers[0].get("title") not in (None, "")

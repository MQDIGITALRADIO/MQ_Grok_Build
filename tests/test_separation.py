"""Tests for artist/title separation scoring."""

from datetime import datetime, timedelta

from mq_radio.scheduler.rules import HistoryWindow, Ruleset, artist_separation_ok, score_track


def _track(**kwargs):
    base = {
        "id": 1,
        "title": "Horizon Run",
        "artist": "Coastline Drift",
        "album": "Tidal",
        "explicit": 0,
        "start_date": None,
        "end_date": None,
        "last_played": None,
        "play_count": 0,
        "energy": 6,
        "australian": 1,
        "rotation_category": "Power",
    }
    base.update(kwargs)
    return base


def test_artist_separation_blocks_too_soon():
    rules = Ruleset(artist_separation_minutes=60)
    history = HistoryWindow()
    when0 = datetime(2026, 9, 5, 10, 0, 0)
    history.add(_track(), when0)
    when1 = when0 + timedelta(minutes=30)
    ok = artist_separation_ok("Coastline Drift", when1, history, 60)
    assert ok is False
    score, reasons = score_track(_track(), when1, history, rules, "A")
    assert score < 0
    assert any("artist_sep" in r for r in reasons)


def test_artist_separation_allows_after_window():
    rules = Ruleset(artist_separation_minutes=60)
    history = HistoryWindow()
    when0 = datetime(2026, 9, 5, 10, 0, 0)
    history.add(_track(), when0)
    when1 = when0 + timedelta(minutes=61)
    ok = artist_separation_ok("Coastline Drift", when1, history, 60)
    assert ok is True
    score, _ = score_track(
        _track(id=2, title="Night Ferry", album="Other Album"), when1, history, rules, "A"
    )
    assert score > 0


def test_title_separation():
    rules = Ruleset(title_separation_minutes=120, artist_separation_minutes=0)
    history = HistoryWindow()
    when0 = datetime(2026, 9, 5, 8, 0, 0)
    history.add(_track(), when0)
    # same title too soon — artist sep disabled so title should catch
    when1 = when0 + timedelta(minutes=30)
    score, reasons = score_track(_track(), when1, history, rules, "A")
    assert score < 0
    assert any("title_sep" in r for r in reasons)


def test_explicit_blocked():
    rules = Ruleset(explicit_allowed=False)
    history = HistoryWindow()
    when = datetime(2026, 9, 5, 12, 0, 0)
    score, reasons = score_track(_track(explicit=1), when, history, rules, "A")
    assert score < 0
    assert "explicit_blocked" in reasons


def test_artist_hour_cap():
    rules = Ruleset(same_artist_max_per_hour=2, artist_separation_minutes=1)
    history = HistoryWindow()
    base = datetime(2026, 9, 5, 14, 0, 0)
    history.add(_track(id=1, title="A", album="Alb1"), base)
    history.add(_track(id=2, title="B", album="Alb2"), base + timedelta(minutes=5))
    when = base + timedelta(minutes=10)
    score, reasons = score_track(_track(id=3, title="C", album="Alb3"), when, history, rules, "A")
    assert score < 0
    assert "artist_hour_cap" in reasons


def test_never_played_bonus_beats_recent():
    rules = Ruleset()
    history = HistoryWindow()
    when = datetime(2026, 9, 5, 9, 0, 0)
    fresh = _track(id=1, last_played=None, play_count=0)
    tired = _track(
        id=2,
        title="Other",
        artist="Other Artist",
        last_played=(when - timedelta(hours=1)).isoformat(sep=" "),
        play_count=20,
    )
    s1, _ = score_track(fresh, when, history, rules, "A")
    s2, _ = score_track(tired, when, history, rules, "A")
    assert s1 > s2

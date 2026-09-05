"""Deterministic Living Log generator — clock expansion + scored selection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.scheduler.rules import HistoryWindow, Ruleset, score_track


MUSIC_EVENT_TYPES = {"MUSIC"}
ASSET_EVENT_TYPES = {"SWEEPER", "ID", "PROMO", "VOICE_TRACK", "BED", "FILLER"}


def _load_rules(conn, ruleset_code: str = "MQ_DIGITAL") -> tuple[int, Ruleset]:
    row = conn.execute(
        "SELECT * FROM station_rules WHERE code = ? AND active = 1", (ruleset_code,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM station_rules WHERE active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    if not row:
        return 0, Ruleset()
    extra = {}
    if row["rules_json"]:
        extra = json.loads(row["rules_json"])
    return int(row["id"]), Ruleset.from_row(row, extra)


def _tracks_for_category(conn, category_code: Optional[str], event_type: str) -> list[dict]:
    if event_type in ASSET_EVENT_TYPES:
        rows = conn.execute(
            """SELECT t.*, c.code AS category_code FROM tracks t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.active = 1 AND t.event_type = ?""",
            (event_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    if category_code:
        rows = conn.execute(
            """SELECT t.*, c.code AS category_code FROM tracks t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.active = 1 AND t.event_type = 'MUSIC' AND c.code = ?""",
            (category_code,),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

    rows = conn.execute(
        """SELECT t.*, c.code AS category_code FROM tracks t
           LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.active = 1 AND t.event_type = 'MUSIC'"""
    ).fetchall()
    return [dict(r) for r in rows]


def _pick_best(
    candidates: list[dict],
    when: datetime,
    history: HistoryWindow,
    rules: Ruleset,
    category_code: Optional[str],
    used_ids: set[int],
) -> tuple[Optional[dict], float]:
    """Pick highest-scoring eligible track. Hard fails (score < 0) are never chosen."""
    best = None
    best_score = -1.0

    def consider(pool, prefer_unused: bool):
        nonlocal best, best_score
        for t in pool:
            if prefer_unused and t["id"] in used_ids:
                continue
            s, _ = score_track(t, when, history, rules, category_code)
            if s < 0:
                continue
            # slight preference for unused
            adj = s + (5.0 if t["id"] not in used_ids else 0.0)
            if adj > best_score:
                best_score = adj
                best = t

    consider(candidates, prefer_unused=True)
    if best is None:
        consider(candidates, prefer_unused=False)
    return best, (best_score if best is not None else -1.0)


def expand_clock_slots(conn, clock_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM clock_slots WHERE clock_id = ? ORDER BY position""",
        (clock_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def generate_log(
    log_date: str,
    db_path: Optional[Path] = None,
    force: bool = False,
    ruleset_code: str = "MQ_DIGITAL",
) -> dict:
    """
    Generate a 24h Living Log for log_date (YYYY-MM-DD).
    Preserves MANUAL rows unless force=True.
    """
    conn = get_connection(db_path)
    rules_id, rules = _load_rules(conn, ruleset_code)

    existing = conn.execute(
        "SELECT * FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()

    manual_rows: dict[int, dict] = {}
    if existing and not force:
        manuals = conn.execute(
            """SELECT * FROM log_events
               WHERE daily_log_id = ? AND manual_flag = 'MANUAL'
               ORDER BY position""",
            (existing["id"],),
        ).fetchall()
        manual_rows = {int(r["position"]): dict(r) for r in manuals}
        conn.execute("DELETE FROM log_events WHERE daily_log_id = ? AND manual_flag != 'MANUAL'",
                     (existing["id"],))
        daily_log_id = existing["id"]
        conn.execute(
            """UPDATE daily_logs SET status='DRAFT', ruleset_id=?, generated_at=datetime('now')
               WHERE id=?""",
            (rules_id, daily_log_id),
        )
    elif existing and force:
        conn.execute("DELETE FROM log_events WHERE daily_log_id = ?", (existing["id"],))
        daily_log_id = existing["id"]
        conn.execute(
            """UPDATE daily_logs SET status='DRAFT', ruleset_id=?, generated_at=datetime('now')
               WHERE id=?""",
            (rules_id, daily_log_id),
        )
        manual_rows = {}
    else:
        cur = conn.execute(
            """INSERT INTO daily_logs (log_date, status, ruleset_id, generated_at)
               VALUES (?, 'DRAFT', ?, datetime('now'))""",
            (log_date, rules_id),
        )
        daily_log_id = cur.lastrowid

    # clock per hour
    hour_clocks = {}
    for row in conn.execute("SELECT hour, clock_id FROM daypart_clocks").fetchall():
        hour_clocks[int(row["hour"])] = int(row["clock_id"])
    default_clock = hour_clocks.get(0, 1)

    history = HistoryWindow()
    # seed history from as_played recent + last_played on tracks lightly
    for row in conn.execute(
        """SELECT a.artist, a.title, a.played_at, a.track_id, t.album
           FROM as_played a
           LEFT JOIN tracks t ON t.id = a.track_id
           ORDER BY a.played_at DESC LIMIT 200"""
    ).fetchall():
        dt = datetime.fromisoformat(row["played_at"]) if row["played_at"] else None
        if dt:
            history.plays.append({
                "track_id": row["track_id"],
                "artist": (row["artist"] or "").lower(),
                "title": (row["title"] or "").lower(),
                "album": (row["album"] or "").lower() if row["album"] else "",
                "played_at": dt,
            })
    # chronological for window logic
    history.plays.sort(key=lambda p: p["played_at"])

    base = datetime.strptime(log_date, "%Y-%m-%d")
    position = 0
    used_ids: set[int] = set()
    generated = 0
    preserved = 0

    # If preserving manuals, rebuild full list by merging
    # Strategy: regenerate all positions; skip insert when position has MANUAL
    max_manual_pos = max(manual_rows.keys()) if manual_rows else -1

    for hour in range(24):
        clock_id = hour_clocks.get(hour, default_clock)
        slots = expand_clock_slots(conn, clock_id)
        # Spread slots across the wall-clock hour so separation has real airtime
        slot_count = max(len(slots), 1)
        hour_start = base + timedelta(hours=hour)
        # ~3 minutes between music-capable slots on average within 60 min
        step_sec = 3600.0 / slot_count

        for slot_index, slot in enumerate(slots):
            # Preserve MANUAL at this position
            if position in manual_rows and not force:
                m = manual_rows[position]
                when = datetime.fromisoformat(m["scheduled_at"]) if m.get("scheduled_at") else (
                    hour_start + timedelta(seconds=step_sec * slot_index)
                )
                if m.get("track_id") and m.get("event_type") == "MUSIC":
                    history.add({
                        "id": m["track_id"],
                        "artist": m.get("artist") or "",
                        "title": m.get("title") or "",
                        "album": "",
                    }, when)
                    used_ids.add(int(m["track_id"]))
                preserved += 1
                position += 1
                continue

            when = hour_start + timedelta(seconds=step_sec * slot_index)
            et = slot["event_type"]
            cat = slot.get("category_code")
            timing = slot.get("timing_mode") or "FLOAT"
            chain = slot.get("chain_mode") or "AUTO"

            track = None
            score = None
            title = slot.get("label") or et
            artist = None
            duration_ms = 0
            track_id = None

            if et in ("ETM", "BREAK", "COMMAND", "LIVE", "SHOW", "FILLER"):
                # structural markers — no track required
                duration_ms = 0 if et == "ETM" else (30_000 if et == "BREAK" else 0)
                title = slot.get("label") or et
            else:
                candidates = _tracks_for_category(conn, cat, et)
                track, score = _pick_best(candidates, when, history, rules, cat, used_ids)
                if track:
                    track_id = track["id"]
                    title = track["title"]
                    artist = track["artist"]
                    duration_ms = int(track["duration_ms"] or 0)
                    used_ids.add(track_id)
                    if et == "MUSIC":
                        history.add(track, when)
                else:
                    title = f"[UNFILLED {et}/{cat or '-'}]"
                    duration_ms = 5000

            # Delete any non-manual leftover at position then insert
            conn.execute(
                "DELETE FROM log_events WHERE daily_log_id = ? AND position = ? AND manual_flag != 'MANUAL'",
                (daily_log_id, position),
            )
            # Only insert if not occupied by manual
            exists_manual = conn.execute(
                """SELECT 1 FROM log_events WHERE daily_log_id=? AND position=? AND manual_flag='MANUAL'""",
                (daily_log_id, position),
            ).fetchone()
            if not exists_manual:
                conn.execute(
                    """INSERT INTO log_events (
                        daily_log_id, position, scheduled_at, event_type, track_id,
                        title, artist, duration_ms, timing_mode, chain_mode,
                        status, manual_flag, category_code, clock_slot_id, score, notes
                    ) VALUES (?,?,?,?,?,?,?,?,?,?, 'COMMITTED', 'AUTO', ?, ?, ?, ?)""",
                    (
                        daily_log_id,
                        position,
                        when.strftime("%Y-%m-%dT%H:%M:%S"),
                        et,
                        track_id,
                        title,
                        artist,
                        duration_ms,
                        timing,
                        chain,
                        cat,
                        slot.get("id"),
                        score,
                        slot.get("label"),
                    ),
                )
                generated += 1

            position += 1

    # Commit log
    conn.execute(
        "UPDATE daily_logs SET status='COMMITTED', generated_at=datetime('now') WHERE id=?",
        (daily_log_id,),
    )
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM log_events WHERE daily_log_id=?", (daily_log_id,)
    ).fetchone()["c"]
    conn.close()

    return {
        "daily_log_id": daily_log_id,
        "log_date": log_date,
        "events": total,
        "generated": generated,
        "preserved_manual": preserved,
        "force": force,
        "ruleset_id": rules_id,
    }

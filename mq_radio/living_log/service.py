"""Living Log read/query helpers for CLI and On-Air UI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection


def classify_ending(outro_ms: Optional[int], duration_ms: Optional[int] = None, has_track: bool = False) -> str:
    """Classify cart ending style from outro metadata.

    COLD  — hard/cold end (outro < 2.5s)
    SOFT  — soft finish (2.5s <= outro < 5s)
    FADE  — fade ending (outro >= 5s)

    Non-music imaging without track outro uses duration heuristics.
    """
    if outro_ms is not None and (has_track or outro_ms > 0):
        o = int(outro_ms)
        if o < 2500:
            return "COLD"
        if o >= 5000:
            return "FADE"
        return "SOFT"

    # Imaging / no track metadata: short carts cold-end, longer fade
    dur = int(duration_ms or 0)
    if dur > 0 and dur < 8000:
        return "COLD"
    return "FADE"


def ending_label(ending_type: str, outro_ms: Optional[int], intro_ms: Optional[int] = None) -> str:
    """Human readout e.g. 'FADE · 8.0s' or with intro 'INTRO 5.2s · FADE · 8.0s'."""
    parts: list[str] = []
    intro = int(intro_ms or 0)
    if intro > 0:
        parts.append(f"INTRO {intro / 1000:.1f}s")
    outro = int(outro_ms or 0)
    if ending_type:
        if outro > 0:
            parts.append(f"{ending_type} · {outro / 1000:.1f}s")
        else:
            parts.append(ending_type)
    return " · ".join(parts) if parts else (ending_type or "—")


def _enrich_event(e: dict) -> dict:
    """Attach intro_ms, outro_ms, ending_type, ending_label to an event dict."""
    intro = e.get("intro_ms")
    outro = e.get("outro_ms")
    has_track = e.get("track_id") is not None and e.get("track_id") != ""
    # When join didn't supply values, fall back to 0
    if intro is None:
        intro = 0
    if outro is None:
        outro = 0
    intro = int(intro or 0)
    outro = int(outro or 0)
    # For imaging without track, leave outro as 0 and classify from duration
    ending = classify_ending(
        outro if has_track else (outro if outro > 0 else None),
        duration_ms=e.get("duration_ms"),
        has_track=bool(has_track),
    )
    e["intro_ms"] = intro
    e["outro_ms"] = outro
    e["ending_type"] = ending
    e["ending_label"] = ending_label(ending, outro if (has_track or outro > 0) else None, intro)
    return e


def get_daily_log(log_date: str, db_path: Optional[Path] = None) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_events(
    log_date: str,
    db_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    conn = get_connection(db_path)
    sql = """
        SELECT e.*,
               COALESCE(t.intro_ms, 0) AS intro_ms,
               COALESCE(t.outro_ms, 0) AS outro_ms,
               COALESCE(t.file_path, '') AS file_path
        FROM log_events e
        JOIN daily_logs d ON d.id = e.daily_log_id
        LEFT JOIN tracks t ON t.id = e.track_id
        WHERE d.log_date = ?
        ORDER BY e.position
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, (log_date,)).fetchall()
    conn.close()
    events = [_enrich_event(dict(r)) for r in rows]
    try:
        from mq_radio.voice_tracker.service import attach_vt_to_events
        events = attach_vt_to_events(events, db_path=db_path)
    except Exception:
        pass
    return events


def now_and_upcoming(
    log_date: str,
    db_path: Optional[Path] = None,
    upcoming: int = 15,
) -> dict:
    events = list_events(log_date, db_path=db_path)
    now_playing = None
    for e in events:
        if e["status"] in ("ON_AIR",):
            now_playing = e
            break
    if now_playing is None:
        for e in events:
            if e["status"] in ("COMMITTED", "DRAFT") and e["event_type"] not in ("ETM",):
                now_playing = e
                break
    upcoming_rows = []
    if now_playing:
        upcoming_rows = [
            e for e in events if e["position"] > now_playing["position"]
        ][:upcoming]
    else:
        upcoming_rows = events[:upcoming]
    return {"now": now_playing, "upcoming": upcoming_rows, "total": len(events)}


# —— Editable Living Log (manual programming) ——

def _ensure_daily_log(conn, log_date: str) -> int:
    row = conn.execute(
        "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO daily_logs (log_date, status, generated_at, notes)
           VALUES (?, 'COMMITTED', datetime('now'), 'manual')""",
        (log_date,),
    )
    return int(cur.lastrowid)


def _renumber_positions(conn, daily_log_id: int) -> None:
    rows = conn.execute(
        "SELECT id FROM log_events WHERE daily_log_id = ? ORDER BY position, id",
        (daily_log_id,),
    ).fetchall()
    for i, r in enumerate(rows):
        conn.execute(
            "UPDATE log_events SET position = ? WHERE id = ?",
            (i, r["id"]),
        )


def _clear_event_dependents(conn, event_id: int) -> None:
    conn.execute("DELETE FROM as_played WHERE log_event_id = ?", (event_id,))
    try:
        conn.execute("DELETE FROM vt_scripts WHERE log_event_id = ?", (event_id,))
    except Exception:
        pass


def _track_row(conn, track_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT t.*, c.code AS category_code
           FROM tracks t
           LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.id = ?""",
        (track_id,),
    ).fetchone()
    return dict(row) if row else None


def list_library(
    q: Optional[str] = None,
    db_path: Optional[Path] = None,
    limit: int = 200,
) -> list[dict]:
    """List library tracks for the On-Air picker (id, artist, title, category, duration)."""
    conn = get_connection(db_path)
    params: list = []
    sql = """
        SELECT t.id, t.artist, t.title, t.duration_ms, t.event_type,
               COALESCE(t.intro_ms, 0) AS intro_ms,
               COALESCE(t.outro_ms, 0) AS outro_ms,
               COALESCE(c.code, t.rotation_category, '') AS category
        FROM tracks t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.active = 1
    """
    if q and q.strip():
        like = f"%{q.strip()}%"
        sql += " AND (t.title LIKE ? OR t.artist LIKE ? OR t.event_type LIKE ? OR COALESCE(c.code,'') LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY t.artist, t.title LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        {
            "id": int(r["id"]),
            "artist": r["artist"] or "",
            "title": r["title"] or "",
            "category": r["category"] or "",
            "duration_ms": int(r["duration_ms"] or 0),
            "event_type": r["event_type"] or "MUSIC",
            "intro_ms": int(r["intro_ms"] or 0),
            "outro_ms": int(r["outro_ms"] or 0),
            "end_pulse_ms": int(r["outro_ms"] or 0),
        }
        for r in rows
    ]


def delete_event(event_id: int, db_path: Optional[Path] = None) -> dict:
    """Delete a log event and shift subsequent positions down."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM log_events WHERE id = ?", (event_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"event {event_id} not found"}
    ev = dict(row)
    daily_log_id = int(ev["daily_log_id"])
    pos = int(ev["position"])
    _clear_event_dependents(conn, event_id)
    conn.execute("DELETE FROM log_events WHERE id = ?", (event_id,))
    # Renumber to close gaps (avoids UNIQUE(position) collisions mid-update)
    _renumber_positions(conn, daily_log_id)
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "deleted_id": event_id,
        "daily_log_id": daily_log_id,
        "position": pos,
    }


def insert_event(
    log_date: str,
    after_position: int,
    event_dict: Optional[dict] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Insert MUSIC/ID/SWEEPER/PROMO/VT after after_position; mark MANUAL.

    event_dict keys: track_id?, event_type?, title?, artist?, duration_ms?,
    chain_mode?, timing_mode?, notes?
    after_position=-1 inserts at the start (new position 0).
    """
    event_dict = dict(event_dict or {})
    conn = get_connection(db_path)
    daily_log_id = _ensure_daily_log(conn, log_date)

    track = None
    track_id = event_dict.get("track_id")
    if track_id is not None and track_id != "":
        track = _track_row(conn, int(track_id))
        if not track:
            conn.close()
            return {"ok": False, "error": f"track {track_id} not found"}

    raw_type = (event_dict.get("event_type") or "").upper().strip()
    if raw_type in ("VT", "VOICE TRACK"):
        raw_type = "VOICE_TRACK"
    if not raw_type and track:
        raw_type = (track.get("event_type") or "MUSIC").upper()
    if not raw_type:
        raw_type = "MUSIC"

    title = event_dict.get("title")
    artist = event_dict.get("artist")
    duration_ms = event_dict.get("duration_ms")
    category_code = event_dict.get("category_code")
    if track:
        title = title or track.get("title")
        artist = artist if artist is not None else track.get("artist")
        if duration_ms is None:
            duration_ms = int(track.get("duration_ms") or 0)
        category_code = category_code or track.get("category_code")
        track_id = int(track["id"])
    else:
        track_id = None
        title = title or raw_type
        artist = artist or ""
        if duration_ms is None:
            duration_ms = 8000 if raw_type == "VOICE_TRACK" else 5000

    # Resolve insert position
    after = int(after_position) if after_position is not None else -1
    new_pos = after + 1
    if new_pos < 0:
        new_pos = 0

    from datetime import datetime, timedelta

    when_str = f"{log_date}T12:00:00"
    if after >= 0:
        neighbor = conn.execute(
            """SELECT scheduled_at, duration_ms FROM log_events
               WHERE daily_log_id = ? AND position = ?""",
            (daily_log_id, after),
        ).fetchone()
        if neighbor:
            try:
                base = datetime.fromisoformat(neighbor["scheduled_at"])
                dur = int(neighbor["duration_ms"] or 0)
                when_str = (base + timedelta(milliseconds=max(dur, 1000))).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )
            except Exception:
                pass
    else:
        first = conn.execute(
            """SELECT scheduled_at FROM log_events
               WHERE daily_log_id = ? ORDER BY position LIMIT 1""",
            (daily_log_id,),
        ).fetchone()
        if first:
            try:
                when_str = (
                    datetime.fromisoformat(first["scheduled_at"]) - timedelta(seconds=5)
                ).strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                pass

    # Make room: shift positions >= new_pos up by 1
    # Do high-to-low to avoid UNIQUE(daily_log_id, position) collisions
    later = conn.execute(
        """SELECT id, position FROM log_events
           WHERE daily_log_id = ? AND position >= ?
           ORDER BY position DESC""",
        (daily_log_id, new_pos),
    ).fetchall()
    for r in later:
        conn.execute(
            "UPDATE log_events SET position = ? WHERE id = ?",
            (int(r["position"]) + 1, r["id"]),
        )

    chain = event_dict.get("chain_mode") or ("MIX" if raw_type == "MUSIC" else "AUTO")
    timing = event_dict.get("timing_mode") or "FLOAT"
    notes = event_dict.get("notes") or "manual insert"

    cur = conn.execute(
        """INSERT INTO log_events (
            daily_log_id, position, scheduled_at, event_type, track_id,
            title, artist, duration_ms, timing_mode, chain_mode,
            status, manual_flag, category_code, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?, 'COMMITTED', 'MANUAL', ?, ?)""",
        (
            daily_log_id,
            new_pos,
            when_str,
            raw_type,
            track_id,
            title,
            artist,
            int(duration_ms or 0),
            timing,
            chain,
            category_code,
            notes,
        ),
    )
    new_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "event_id": new_id,
        "position": new_pos,
        "daily_log_id": daily_log_id,
        "event_type": raw_type,
        "title": title,
        "artist": artist,
        "manual_flag": "MANUAL",
    }


def replace_event(event_id: int, track_id: int, db_path: Optional[Path] = None) -> dict:
    """Swap the cart on an existing log event from the library; mark MANUAL."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM log_events WHERE id = ?", (event_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"event {event_id} not found"}
    track = _track_row(conn, int(track_id))
    if not track:
        conn.close()
        return {"ok": False, "error": f"track {track_id} not found"}

    ev = dict(row)
    new_type = (track.get("event_type") or ev.get("event_type") or "MUSIC").upper()
    conn.execute(
        """UPDATE log_events SET
            track_id=?, title=?, artist=?, duration_ms=?,
            event_type=?, category_code=?, manual_flag='MANUAL',
            notes=COALESCE(notes, '') || CASE
                WHEN notes IS NULL OR notes = '' THEN 'manual replace'
                WHEN notes LIKE '%manual replace%' THEN ''
                ELSE ' | manual replace'
            END
           WHERE id=?""",
        (
            int(track["id"]),
            track.get("title"),
            track.get("artist"),
            int(track.get("duration_ms") or 0),
            new_type,
            track.get("category_code"),
            event_id,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "event_id": event_id,
        "track_id": int(track["id"]),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "event_type": new_type,
        "manual_flag": "MANUAL",
    }


def load_sample_hour(
    log_date: str,
    db_path: Optional[Path] = None,
    hour: int = 12,
    clear_day: bool = True,
) -> dict:
    """Replace (or seed) today's log with a clear 1-hour programmable sample block.

    Structure: ID → 10 MUSIC with ID/SWEEPER/PROMO/VT mixed in — all MANUAL so
    regenerate preserves them unless --force.
    """
    from datetime import datetime, timedelta

    conn = get_connection(db_path)
    daily_log_id = _ensure_daily_log(conn, log_date)

    if clear_day:
        ids = [
            int(r["id"])
            for r in conn.execute(
                "SELECT id FROM log_events WHERE daily_log_id = ?", (daily_log_id,)
            )
        ]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM as_played WHERE log_event_id IN ({placeholders})", ids)
            try:
                conn.execute(f"DELETE FROM vt_scripts WHERE log_event_id IN ({placeholders})", ids)
            except Exception:
                pass
            conn.execute("DELETE FROM log_events WHERE daily_log_id = ?", (daily_log_id,))

    music = [
        dict(r)
        for r in conn.execute(
            """SELECT t.*, c.code AS category_code FROM tracks t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.active = 1 AND t.event_type = 'MUSIC'
               ORDER BY t.id LIMIT 12"""
        ).fetchall()
    ]
    assets = {}
    for et in ("ID", "SWEEPER", "PROMO"):
        row = conn.execute(
            """SELECT t.*, c.code AS category_code FROM tracks t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.active = 1 AND t.event_type = ?
               ORDER BY t.id LIMIT 1""",
            (et,),
        ).fetchone()
        assets[et] = dict(row) if row else None

    if len(music) < 3:
        conn.close()
        return {
            "ok": False,
            "error": "Need demo library tracks — run: python -m mq_radio seed-demo",
        }

    # Build hour template (~10 songs + imaging + VT)
    # (event_type, source) where source is 'music' index or asset key or None for freeform VT
    plan = [
        ("ID", "ID"),
        ("MUSIC", 0),
        ("MUSIC", 1),
        ("SWEEPER", "SWEEPER"),
        ("MUSIC", 2),
        ("VOICE_TRACK", None),
        ("MUSIC", 3),
        ("MUSIC", 4),
        ("PROMO", "PROMO"),
        ("MUSIC", 5),
        ("SWEEPER", "SWEEPER"),
        ("MUSIC", 6),
        ("VOICE_TRACK", None),
        ("MUSIC", 7),
        ("MUSIC", 8),
        ("MUSIC", 9),
        ("ID", "ID"),
    ]

    base = datetime.strptime(log_date, "%Y-%m-%d") + timedelta(hours=int(hour))
    # Spread across ~55 minutes
    step = 55 * 60 / max(len(plan), 1)
    inserted = 0
    music_i = 0

    for pos, (et, src) in enumerate(plan):
        when = base + timedelta(seconds=step * pos)
        track_id = None
        title = et
        artist = "MQ DIGITAL"
        duration_ms = 5000
        category_code = None
        notes = "sample hour"

        if et == "MUSIC":
            idx = src if isinstance(src, int) else music_i
            idx = idx % len(music)
            t = music[idx]
            music_i = idx + 1
            track_id = int(t["id"])
            title = t["title"]
            artist = t["artist"]
            duration_ms = int(t["duration_ms"] or 15000)
            category_code = t.get("category_code")
        elif et == "VOICE_TRACK":
            title = "VT — sample break"
            artist = "MQ Digital"
            duration_ms = 8000
            category_code = "VT"
            notes = "sample hour VT placeholder"
        elif src in assets and assets[src]:
            t = assets[src]
            track_id = int(t["id"])
            title = t["title"]
            artist = t["artist"]
            duration_ms = int(t["duration_ms"] or 4000)
            category_code = t.get("category_code") or src[:2]
        else:
            title = f"Sample {et}"
            category_code = et[:2] if et != "VOICE_TRACK" else "VT"

        chain = "MIX" if et == "MUSIC" else "AUTO"
        timing = "HIT" if et == "ID" and pos == 0 else "FLOAT"

        conn.execute(
            """INSERT INTO log_events (
                daily_log_id, position, scheduled_at, event_type, track_id,
                title, artist, duration_ms, timing_mode, chain_mode,
                status, manual_flag, category_code, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?, 'COMMITTED', 'MANUAL', ?, ?)""",
            (
                daily_log_id,
                pos,
                when.strftime("%Y-%m-%dT%H:%M:%S"),
                et,
                track_id,
                title,
                artist,
                duration_ms,
                timing,
                chain,
                category_code,
                notes,
            ),
        )
        inserted += 1

    conn.execute(
        """UPDATE daily_logs SET status='COMMITTED', notes=?, generated_at=datetime('now')
           WHERE id=?""",
        (f"sample hour h{hour:02d}", daily_log_id),
    )
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM log_events WHERE daily_log_id=?", (daily_log_id,)
    ).fetchone()["c"]
    conn.close()
    return {
        "ok": True,
        "log_date": log_date,
        "daily_log_id": daily_log_id,
        "hour": hour,
        "inserted": inserted,
        "events": total,
        "cleared": clear_day,
        "manual": True,
    }

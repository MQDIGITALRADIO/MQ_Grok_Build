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
               COALESCE(t.outro_ms, 0) AS outro_ms
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

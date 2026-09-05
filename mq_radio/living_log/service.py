"""Living Log read/query helpers for CLI and On-Air UI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection


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
        SELECT e.* FROM log_events e
        JOIN daily_logs d ON d.id = e.daily_log_id
        WHERE d.log_date = ?
        ORDER BY e.position
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, (log_date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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

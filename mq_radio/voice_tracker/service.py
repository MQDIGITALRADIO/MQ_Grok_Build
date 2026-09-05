"""Approve / list voice-track scripts for the Living Log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection, init_db
from mq_radio.voice_tracker.inserter import _notes_payload, generate_ai_breaks
from mq_radio.voice_tracker.script_generator import STATION_DEFAULT, generate_script


def list_vt(
    log_date: Optional[str] = None,
    db_path: Optional[Path] = None,
    status: Optional[str] = None,
) -> list[dict]:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        sql = """
            SELECT v.*, e.position, e.scheduled_at, e.title AS event_title,
                   e.artist AS event_artist, e.duration_ms, e.status AS event_status,
                   e.notes, d.log_date
            FROM vt_scripts v
            JOIN log_events e ON e.id = v.log_event_id
            JOIN daily_logs d ON d.id = e.daily_log_id
            WHERE 1=1
        """
        params: list = []
        if log_date:
            sql += " AND d.log_date = ?"
            params.append(log_date)
        if status:
            sql += " AND v.status = ?"
            params.append(status)
        sql += " ORDER BY d.log_date, e.position"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def approve_ai_breaks(
    log_date: str,
    db_path: Optional[Path] = None,
    *,
    only_ids: Optional[list[int]] = None,
) -> dict:
    """Promote DRAFT vt_scripts (and their log_events) to APPROVED/COMMITTED."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        daily = conn.execute(
            "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
        ).fetchone()
        if not daily:
            return {"ok": False, "error": f"No living log for {log_date}", "approved": 0}

        sql = """
            SELECT v.id AS vt_id, v.log_event_id, v.variation, v.script_text,
                   v.daypart, v.style, v.station_name, v.source
            FROM vt_scripts v
            JOIN log_events e ON e.id = v.log_event_id
            WHERE e.daily_log_id = ? AND v.status = 'DRAFT'
        """
        params: list = [daily["id"]]
        if only_ids:
            placeholders = ",".join("?" * len(only_ids))
            sql += f" AND v.id IN ({placeholders})"
            params.extend(only_ids)

        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        approved = 0
        for r in rows:
            info = {
                "variation": r["variation"],
                "script": r["script_text"] or "",
                "daypart": r["daypart"],
                "style": r["style"],
                "station_name": r["station_name"] or STATION_DEFAULT,
                "source": r["source"],
                "skipped": not bool((r["script_text"] or "").strip()),
            }
            notes = _notes_payload(info, "APPROVED")
            conn.execute(
                """UPDATE vt_scripts SET status='APPROVED', updated_at=datetime('now')
                   WHERE id=?""",
                (r["vt_id"],),
            )
            # Silence drafts stay DRAFT on the event duration but committed status
            new_status = "COMMITTED"
            conn.execute(
                """UPDATE log_events SET status=?, notes=? WHERE id=?""",
                (new_status, notes, r["log_event_id"]),
            )
            approved += 1
        conn.commit()
        return {"ok": True, "log_date": log_date, "approved": approved}
    finally:
        conn.close()


def script_for_transition(
    *,
    prev_track: Optional[dict] = None,
    next_track: Optional[dict] = None,
    daypart: str = "day",
    station_name: str = STATION_DEFAULT,
    style: str = "warm",
    variation: Optional[str] = None,
) -> dict:
    """One-off script for the VT studio panel (does not write DB)."""
    return generate_script(
        prev_track=prev_track,
        next_track=next_track,
        daypart=daypart,
        station_name=station_name,
        style=style,
        variation=variation,
        seed_key=f"studio:{daypart}:{variation}",
    )


def attach_vt_to_events(events: list[dict], db_path: Optional[Path] = None) -> list[dict]:
    """Enrich log event dicts with vt_script / vt_status / vt_variation when present."""
    if not events:
        return events
    ids = [e["id"] for e in events if e.get("id") is not None]
    if not ids:
        return events
    conn = get_connection(db_path)
    try:
        # table may not exist on very old DBs before migrate — init_db handles that
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""SELECT log_event_id, variation, script_text, status, daypart, style
                FROM vt_scripts WHERE log_event_id IN ({placeholders})""",
            ids,
        ).fetchall()
        by_id = {int(r["log_event_id"]): dict(r) for r in rows}
    except Exception:
        by_id = {}
    finally:
        conn.close()

    for e in events:
        vt = by_id.get(int(e["id"])) if e.get("id") is not None else None
        if vt:
            e["vt_script"] = vt.get("script_text") or ""
            e["vt_status"] = vt.get("status")
            e["vt_variation"] = vt.get("variation")
            e["vt_daypart"] = vt.get("daypart")
            e["vt_style"] = vt.get("style")
            preview = e["vt_script"]
            if len(preview) > 80:
                preview = preview[:77] + "..."
            e["vt_preview"] = preview
        else:
            # fall back to notes preview
            notes = e.get("notes") or ""
            if "[AI VT" in notes:
                e["vt_preview"] = notes.split("|")[0].strip()
                try:
                    meta = json.loads(notes.split("|", 1)[1].strip())
                    e["vt_variation"] = meta.get("variation")
                    e["vt_status"] = meta.get("status")
                except Exception:
                    pass
    return events


# Re-export for CLI convenience
__all__ = [
    "list_vt",
    "approve_ai_breaks",
    "generate_ai_breaks",
    "script_for_transition",
    "attach_vt_to_events",
]

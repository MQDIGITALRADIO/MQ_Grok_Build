"""Insert / fill VOICE_TRACK events with AI announcer scripts on a Living Log."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection, init_db
from mq_radio.voice_tracker.script_generator import (
    STATION_DEFAULT,
    daypart_for_hour,
    generate_script,
)

# Density: at most one auto-inserted VT every N music-to-music gaps per hour
DEFAULT_MAX_INSERTS_PER_HOUR = 2
DEFAULT_MUSIC_GAP_STRIDE = 2  # insert on every Nth eligible MUSIC→MUSIC gap
PLACEHOLDER_TITLES = {
    "VOICE_TRACK",
    "VT",
    "Voice Track",
    "[UNFILLED VOICE_TRACK/-]",
    "[UNFILLED VOICE_TRACK/VT]",
}


def _parse_hour(scheduled_at: str) -> int:
    try:
        return datetime.fromisoformat(scheduled_at).hour
    except Exception:
        return 0


def _is_music(e: dict) -> bool:
    return (e.get("event_type") or "") == "MUSIC"


def _is_vt(e: dict) -> bool:
    return (e.get("event_type") or "") == "VOICE_TRACK"


def _track_ref(e: Optional[dict]) -> Optional[dict]:
    if not e:
        return None
    return {
        "title": e.get("title"),
        "artist": e.get("artist"),
        "id": e.get("track_id"),
    }


def _notes_payload(script_info: dict, status: str = "DRAFT") -> str:
    preview = script_info.get("script") or ""
    if len(preview) > 120:
        preview = preview[:117] + "..."
    meta = {
        "ai_vt": True,
        "variation": script_info.get("variation"),
        "status": status,
        "preview": preview,
    }
    return (
        f"[AI VT {status}] {script_info.get('variation')}: {preview} "
        f"| {json.dumps(meta, separators=(',', ':'))}"
    )


def _load_events(conn, log_date: str) -> tuple[Optional[int], list[dict]]:
    daily = conn.execute(
        "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    if not daily:
        return None, []
    rows = conn.execute(
        """SELECT * FROM log_events WHERE daily_log_id = ? ORDER BY position""",
        (daily["id"],),
    ).fetchall()
    return int(daily["id"]), [dict(r) for r in rows]


def _upsert_vt_script(
    conn,
    log_event_id: int,
    script_info: dict,
    prev: Optional[dict],
    nxt: Optional[dict],
    status: str = "DRAFT",
) -> int:
    existing = conn.execute(
        "SELECT id FROM vt_scripts WHERE log_event_id = ?", (log_event_id,)
    ).fetchone()
    prev_t = (prev or {}).get("title")
    prev_a = (prev or {}).get("artist")
    next_t = (nxt or {}).get("title")
    next_a = (nxt or {}).get("artist")
    vals = (
        script_info["variation"],
        script_info["script"],
        script_info.get("daypart"),
        script_info.get("style"),
        script_info.get("station_name") or STATION_DEFAULT,
        status,
        script_info.get("source") or "AI_TEMPLATE",
        prev_t,
        prev_a,
        next_t,
        next_a,
    )
    if existing:
        conn.execute(
            """UPDATE vt_scripts SET
                variation=?, script_text=?, daypart=?, style=?, station_name=?,
                status=?, source=?, prev_title=?, prev_artist=?, next_title=?, next_artist=?,
                updated_at=datetime('now')
               WHERE id=?""",
            vals + (existing["id"],),
        )
        return int(existing["id"])
    cur = conn.execute(
        """INSERT INTO vt_scripts (
            log_event_id, variation, script_text, daypart, style, station_name,
            status, source, prev_title, prev_artist, next_title, next_artist
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (log_event_id,) + vals,
    )
    return int(cur.lastrowid)


def _vt_needs_fill(e: dict, conn) -> bool:
    if not _is_vt(e):
        return False
    row = conn.execute(
        "SELECT id, script_text, status FROM vt_scripts WHERE log_event_id = ?",
        (e["id"],),
    ).fetchone()
    if not row:
        return True
    if not (row["script_text"] or "").strip() and row["status"] == "DRAFT":
        return True
    if row["status"] == "APPROVED":
        return False
    title = (e.get("title") or "").strip()
    if title in PLACEHOLDER_TITLES or title.startswith("[UNFILLED"):
        return True
    # empty notes / no AI marker → fill
    notes = e.get("notes") or ""
    if "[AI VT" not in notes:
        return True
    return False


def _neighbors(events: list[dict], idx: int) -> tuple[Optional[dict], Optional[dict]]:
    prev = None
    nxt = None
    for j in range(idx - 1, -1, -1):
        if _is_music(events[j]):
            prev = events[j]
            break
    for j in range(idx + 1, len(events)):
        if _is_music(events[j]):
            nxt = events[j]
            break
    return prev, nxt


def fill_placeholders(
    conn,
    events: list[dict],
    *,
    station_name: str,
    style: str,
) -> list[dict]:
    """Fill existing VOICE_TRACK rows that lack a script."""
    filled = []
    for idx, e in enumerate(events):
        if not _vt_needs_fill(e, conn):
            continue
        prev, nxt = _neighbors(events, idx)
        hour = _parse_hour(e["scheduled_at"])
        daypart = daypart_for_hour(hour)
        info = generate_script(
            prev_track=_track_ref(prev),
            next_track=_track_ref(nxt),
            daypart=daypart,
            station_name=station_name,
            style=style,
            seed_key=f"fill:{e['id']}:{e.get('scheduled_at')}",
        )
        status = "DRAFT"
        _upsert_vt_script(conn, e["id"], info, _track_ref(prev), _track_ref(nxt), status)
        title = "AI Voice Track" if not info["skipped"] else "AI VT (silence)"
        notes = _notes_payload(info, status)
        conn.execute(
            """UPDATE log_events SET title=?, artist=?, duration_ms=?, notes=?, status='DRAFT'
               WHERE id=?""",
            (
                title,
                station_name,
                0 if info["skipped"] else info["duration_ms"],
                notes,
                e["id"],
            ),
        )
        filled.append({"log_event_id": e["id"], "position": e["position"], **info})
    return filled


def _eligible_insert_gaps(events: list[dict]) -> list[int]:
    """Indices of MUSIC events followed immediately by another MUSIC."""
    gaps = []
    for i in range(len(events) - 1):
        if _is_music(events[i]) and _is_music(events[i + 1]):
            gaps.append(i)
    return gaps


def insert_between_music(
    conn,
    daily_log_id: int,
    events: list[dict],
    *,
    station_name: str,
    style: str,
    max_per_hour: int = DEFAULT_MAX_INSERTS_PER_HOUR,
    stride: int = DEFAULT_MUSIC_GAP_STRIDE,
) -> list[dict]:
    """Insert new VOICE_TRACK rows between adjacent MUSIC events (density-capped)."""
    gaps = _eligible_insert_gaps(events)
    per_hour: dict[int, int] = {}
    chosen: list[int] = []
    gap_ordinal = 0
    for gi in gaps:
        gap_ordinal += 1
        if stride > 1 and (gap_ordinal % stride) != 0:
            continue
        hour = _parse_hour(events[gi]["scheduled_at"])
        if per_hour.get(hour, 0) >= max_per_hour:
            continue
        per_hour[hour] = per_hour.get(hour, 0) + 1
        chosen.append(gi)

    if not chosen:
        return []

    new_rows: list[dict] = []
    chosen_set = set(chosen)

    for i, e in enumerate(events):
        new_rows.append({"kind": "existing", "event": e})
        if i not in chosen_set:
            continue
        prev = events[i]
        nxt = events[i + 1]
        try:
            t0 = datetime.fromisoformat(prev["scheduled_at"])
            t1 = datetime.fromisoformat(nxt["scheduled_at"])
            mid = t0 + (t1 - t0) / 2
        except Exception:
            mid = datetime.fromisoformat(prev["scheduled_at"]) + timedelta(seconds=5)
        daypart = daypart_for_hour(mid.hour)
        info = generate_script(
            prev_track=_track_ref(prev),
            next_track=_track_ref(nxt),
            daypart=daypart,
            station_name=station_name,
            style=style,
            seed_key=f"ins:{daily_log_id}:{prev['position']}:{nxt['position']}",
        )
        vt_row = {
            "scheduled_at": mid.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "VOICE_TRACK",
            "track_id": None,
            "title": "AI Voice Track" if not info["skipped"] else "AI VT (silence)",
            "artist": station_name,
            "duration_ms": 0 if info["skipped"] else info["duration_ms"],
            "timing_mode": "FLOAT",
            "chain_mode": "AUTO",
            "status": "DRAFT",
            "manual_flag": "AUTO",
            "category_code": "VT",
            "clock_slot_id": None,
            "score": None,
            "notes": _notes_payload(info, "DRAFT"),
            "_script": info,
            "_prev": _track_ref(prev),
            "_next": _track_ref(nxt),
        }
        new_rows.append({"kind": "insert", "event": vt_row})

    # Avoid UNIQUE(position) collisions while renumbering
    conn.execute(
        "UPDATE log_events SET position = position + 100000 WHERE daily_log_id = ?",
        (daily_log_id,),
    )

    result = []
    pos = 0
    for item in new_rows:
        e = item["event"]
        if item["kind"] == "existing":
            conn.execute(
                "UPDATE log_events SET position = ? WHERE id = ?",
                (pos, e["id"]),
            )
            pos += 1
            continue

        info = e.pop("_script")
        prev = e.pop("_prev")
        nxt = e.pop("_next")
        cur = conn.execute(
            """INSERT INTO log_events (
                daily_log_id, position, scheduled_at, event_type, track_id,
                title, artist, duration_ms, timing_mode, chain_mode,
                status, manual_flag, category_code, clock_slot_id, score, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                daily_log_id,
                pos,
                e["scheduled_at"],
                e["event_type"],
                e["track_id"],
                e["title"],
                e["artist"],
                e["duration_ms"],
                e["timing_mode"],
                e["chain_mode"],
                e["status"],
                e["manual_flag"],
                e["category_code"],
                e["clock_slot_id"],
                e["score"],
                e["notes"],
            ),
        )
        eid = int(cur.lastrowid)
        _upsert_vt_script(conn, eid, info, prev, nxt, "DRAFT")
        result.append({"log_event_id": eid, "position": pos, **info})
        pos += 1

    return result


def generate_ai_breaks(
    log_date: str,
    db_path: Optional[Path] = None,
    *,
    station_name: str = STATION_DEFAULT,
    style: str = "warm",
    insert_gaps: bool = True,
    max_per_hour: int = DEFAULT_MAX_INSERTS_PER_HOUR,
    stride: int = DEFAULT_MUSIC_GAP_STRIDE,
) -> dict:
    """
    Fill VT placeholders and optionally insert VOICE_TRACK events between music.
    Scripts land as DRAFT until approve-ai-breaks.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        daily_log_id, events = _load_events(conn, log_date)
        if daily_log_id is None:
            return {
                "ok": False,
                "error": f"No living log for {log_date}. Run generate-log first.",
                "log_date": log_date,
            }
        filled = fill_placeholders(
            conn, events, station_name=station_name, style=style
        )
        _, events = _load_events(conn, log_date)
        inserted: list[dict] = []
        if insert_gaps:
            inserted = insert_between_music(
                conn,
                daily_log_id,
                events,
                station_name=station_name,
                style=style,
                max_per_hour=max_per_hour,
                stride=stride,
            )
        conn.commit()
        drafts = conn.execute(
            """SELECT COUNT(*) AS c FROM vt_scripts v
               JOIN log_events e ON e.id = v.log_event_id
               JOIN daily_logs d ON d.id = e.daily_log_id
               WHERE d.log_date = ? AND v.status = 'DRAFT'""",
            (log_date,),
        ).fetchone()["c"]
        return {
            "ok": True,
            "log_date": log_date,
            "filled": len(filled),
            "inserted": len(inserted),
            "drafts": drafts,
            "filled_detail": filled,
            "inserted_detail": inserted,
        }
    finally:
        conn.close()

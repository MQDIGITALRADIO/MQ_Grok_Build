"""Segue Editor — outgoing cart → optional VT → incoming with duck/marks."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.living_log.service import _enrich_event

DEFAULT_DUCK_DB = -11.0


def _event_by_id(conn, event_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT e.*,
                  COALESCE(t.intro_ms, 0) AS intro_ms,
                  COALESCE(t.outro_ms, 0) AS outro_ms
           FROM log_events e
           LEFT JOIN tracks t ON t.id = e.track_id
           WHERE e.id = ?""",
        (event_id,),
    ).fetchone()
    return _enrich_event(dict(row)) if row else None


def get_segue(
    from_event_id: int,
    to_event_id: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    conn = get_connection(db_path)
    if to_event_id is not None:
        row = conn.execute(
            """SELECT * FROM segue_links
               WHERE from_event_id = ? AND to_event_id = ?""",
            (from_event_id, to_event_id),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM segue_links WHERE from_event_id = ?
               ORDER BY id DESC LIMIT 1""",
            (from_event_id,),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_segue(payload: dict, db_path: Optional[Path] = None) -> dict:
    """Upsert a segue link between from_event_id and to_event_id."""
    from_id = payload.get("from_event_id")
    to_id = payload.get("to_event_id")
    if not from_id or not to_id:
        return {"ok": False, "error": "from_event_id and to_event_id required"}

    conn = get_connection(db_path)
    for eid in (from_id, to_id, payload.get("vt_event_id")):
        if eid is None:
            continue
        exists = conn.execute(
            "SELECT 1 FROM log_events WHERE id = ?", (int(eid),)
        ).fetchone()
        if not exists:
            conn.close()
            return {"ok": False, "error": f"event {eid} not found"}

    duck = payload.get("duck_db")
    if duck is None:
        duck = DEFAULT_DUCK_DB
    fields = (
        payload.get("vt_event_id"),
        int(payload.get("from_outro_mark_ms") or 0),
        int(payload.get("to_intro_mark_ms") or 0),
        int(payload.get("vt_in_ms") or 0),
        payload.get("vt_out_ms"),
        float(duck),
        int(payload.get("crossfade_ms") or 0),
        payload.get("notes") or "",
    )
    existing = conn.execute(
        "SELECT id FROM segue_links WHERE from_event_id=? AND to_event_id=?",
        (int(from_id), int(to_id)),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE segue_links SET
                vt_event_id=?, from_outro_mark_ms=?, to_intro_mark_ms=?,
                vt_in_ms=?, vt_out_ms=?, duck_db=?, crossfade_ms=?, notes=?,
                updated_at=datetime('now')
               WHERE id=?""",
            fields + (existing["id"],),
        )
        segue_id = int(existing["id"])
    else:
        cur = conn.execute(
            """INSERT INTO segue_links (
                vt_event_id, from_outro_mark_ms, to_intro_mark_ms,
                vt_in_ms, vt_out_ms, duck_db, crossfade_ms, notes,
                from_event_id, to_event_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            fields + (int(from_id), int(to_id)),
        )
        segue_id = int(cur.lastrowid)
    conn.commit()
    row = conn.execute("SELECT * FROM segue_links WHERE id=?", (segue_id,)).fetchone()
    conn.close()
    return {"ok": True, "segue": dict(row)}


def segue_context_for_event(event_id: int, db_path: Optional[Path] = None) -> dict:
    """Build outgoing / VT / incoming context for the Segue Editor UI."""
    conn = get_connection(db_path)
    center = _event_by_id(conn, event_id)
    if not center:
        conn.close()
        return {"ok": False, "error": f"event {event_id} not found"}

    daily_log_id = int(center["daily_log_id"])
    rows = conn.execute(
        """SELECT e.*,
                  COALESCE(t.intro_ms, 0) AS intro_ms,
                  COALESCE(t.outro_ms, 0) AS outro_ms
           FROM log_events e
           LEFT JOIN tracks t ON t.id = e.track_id
           WHERE e.daily_log_id = ?
           ORDER BY e.position""",
        (daily_log_id,),
    ).fetchall()
    events = [_enrich_event(dict(r)) for r in rows]
    idx = next((i for i, e in enumerate(events) if e["id"] == event_id), None)
    if idx is None:
        conn.close()
        return {"ok": False, "error": "event not in log"}

    outgoing = center
    vt_ev = None
    incoming = None

    if center["event_type"] == "VOICE_TRACK":
        vt_ev = center
        for i in range(idx - 1, -1, -1):
            if events[i]["event_type"] == "MUSIC":
                outgoing = events[i]
                break
        for i in range(idx + 1, len(events)):
            if events[i]["event_type"] == "MUSIC":
                incoming = events[i]
                break
    else:
        for i in range(idx + 1, len(events)):
            et = events[i]["event_type"]
            if et == "VOICE_TRACK" and vt_ev is None:
                vt_ev = events[i]
                continue
            if et == "MUSIC":
                incoming = events[i]
                break

    link = None
    if outgoing and incoming:
        row = conn.execute(
            """SELECT * FROM segue_links WHERE from_event_id=? AND to_event_id=?""",
            (outgoing["id"], incoming["id"]),
        ).fetchone()
        link = dict(row) if row else None
    conn.close()

    default_outro = int((outgoing or {}).get("outro_ms") or 0)
    default_intro = int((incoming or {}).get("intro_ms") or 0)
    if link is None and outgoing and incoming:
        link = {
            "from_event_id": outgoing["id"],
            "to_event_id": incoming["id"],
            "vt_event_id": vt_ev["id"] if vt_ev else None,
            "from_outro_mark_ms": default_outro,
            "to_intro_mark_ms": default_intro,
            "vt_in_ms": 0,
            "vt_out_ms": (vt_ev or {}).get("duration_ms"),
            "duck_db": DEFAULT_DUCK_DB,
            "crossfade_ms": 0,
            "notes": "",
        }

    return {
        "ok": True,
        "outgoing": outgoing,
        "voice_track": vt_ev,
        "incoming": incoming,
        "segue": link,
        "defaults": {
            "duck_db": DEFAULT_DUCK_DB,
            "from_outro_mark_ms": default_outro,
            "to_intro_mark_ms": default_intro,
        },
    }

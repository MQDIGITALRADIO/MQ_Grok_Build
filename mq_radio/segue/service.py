"""Segue Editor — outgoing cart → optional VT → incoming with duck/marks."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.living_log.service import _enrich_event
from mq_radio.web.media import playable_url

DEFAULT_DUCK_DB = -11.0

def _with_media(ev: Optional[dict]) -> Optional[dict]:
    """Attach playable_url for Segue Editor audition / desk preview."""
    if not ev:
        return ev
    out = dict(ev)
    tid = out.get("track_id")
    fpath = out.get("file_path") or out.get("audio_path")
    # Prefer track_id media route when present
    url = None
    if tid is not None:
        try:
            url = playable_url(None, int(tid))
        except Exception:
            url = None
    if not url and fpath:
        url = playable_url(fpath)
    out["playable_url"] = url
    return out




def _event_by_id(conn, event_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT e.*,
                  COALESCE(t.intro_ms, 0) AS intro_ms,
                  COALESCE(t.outro_ms, 0) AS outro_ms,
                  t.file_path AS file_path
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
    if from_id is None or to_id is None or from_id == "" or to_id == "":
        return {"ok": False, "error": "from_event_id and to_event_id required"}
    try:
        from_id = int(from_id)
        to_id = int(to_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "from_event_id and to_event_id must be integers"}
    if from_id == to_id:
        return {"ok": False, "error": "from_event_id and to_event_id must differ"}

    conn = get_connection(db_path)
    vt_raw = payload.get("vt_event_id")
    vt_id = None
    if vt_raw is not None and vt_raw != "":
        try:
            vt_id = int(vt_raw)
        except (TypeError, ValueError):
            conn.close()
            return {"ok": False, "error": "vt_event_id must be an integer"}
    for eid in (from_id, to_id, vt_id):
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
    try:
        duck_f = float(duck)
    except (TypeError, ValueError):
        conn.close()
        return {"ok": False, "error": "duck_db must be a number"}
    # Broadcast-sensible duck range (0 = no duck, down to -40 dB)
    duck_f = max(-40.0, min(0.0, duck_f))
    try:
        from_outro = max(0, int(payload.get("from_outro_mark_ms") or 0))
        to_intro = max(0, int(payload.get("to_intro_mark_ms") or 0))
        vt_in = max(0, int(payload.get("vt_in_ms") or 0))
        xfade = int(payload.get("crossfade_ms") or 0)
    except (TypeError, ValueError):
        conn.close()
        return {"ok": False, "error": "marker / crossfade values must be integers"}
    xfade = max(0, min(xfade, 12000))
    vt_out = payload.get("vt_out_ms")
    if vt_out is not None and vt_out != "":
        try:
            vt_out = max(0, int(vt_out))
        except (TypeError, ValueError):
            conn.close()
            return {"ok": False, "error": "vt_out_ms must be an integer"}
        if vt_out < vt_in:
            conn.close()
            return {"ok": False, "error": "vt_out_ms must be >= vt_in_ms"}
    else:
        vt_out = None
    fields = (
        vt_id,
        from_outro,
        to_intro,
        vt_in,
        vt_out,
        duck_f,
        xfade,
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
                  COALESCE(t.outro_ms, 0) AS outro_ms,
                  t.file_path AS file_path
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
        "outgoing": _with_media(outgoing),
        "voice_track": _with_media(vt_ev),
        "incoming": _with_media(incoming),
        "segue": link,
        "defaults": {
            "duck_db": DEFAULT_DUCK_DB,
            "from_outro_mark_ms": default_outro,
            "to_intro_mark_ms": default_intro,
        },
    }


def resolve_overlap_params(
    from_event_id: Optional[int],
    to_event_id: Optional[int],
    *,
    end_pulse_ms: int = 0,
    from_outro_ms: int = 0,
    to_intro_ms: int = 0,
    next_event_type: str = "",
    db_path: Optional[Path] = None,
) -> dict:
    """Resolve crossfade/duck/marks for an overlapping dual-deck segue.

    Prefers Segue Editor row when present; otherwise derives a broadcast-sensible
    default from end-pulse / outro / intro marks.
    """
    from mq_radio.engine.session import DEFAULT_CROSSFADE_MS

    link = None
    if from_event_id and to_event_id:
        link = get_segue(int(from_event_id), int(to_event_id), db_path=db_path)

    duck = DEFAULT_DUCK_DB
    crossfade = 0
    from_outro_mark = int(from_outro_ms or 0)
    to_intro_mark = int(to_intro_ms or 0)
    vt_event_id = None
    vt_in_ms = 0
    vt_out_ms = None
    notes = ""

    if link:
        duck = float(link.get("duck_db") if link.get("duck_db") is not None else DEFAULT_DUCK_DB)
        crossfade = int(link.get("crossfade_ms") or 0)
        from_outro_mark = int(link.get("from_outro_mark_ms") or from_outro_mark or 0)
        to_intro_mark = int(link.get("to_intro_mark_ms") or to_intro_mark or 0)
        vt_event_id = link.get("vt_event_id")
        vt_in_ms = int(link.get("vt_in_ms") or 0)
        vt_out_ms = link.get("vt_out_ms")
        notes = link.get("notes") or ""

    # Derive crossfade when editor left it at 0
    if crossfade <= 0:
        candidates = [p for p in (from_outro_mark, int(end_pulse_ms or 0)) if p and p > 0]
        if candidates:
            crossfade = min(max(candidates), 8000)
        elif (next_event_type or "").upper() == "VOICE_TRACK":
            crossfade = 800
        else:
            crossfade = DEFAULT_CROSSFADE_MS
    crossfade = max(120, min(int(crossfade), 12000))

    # Without an editor link, music→music uses equal-power only (no bed duck).
    # Editor duck_db always wins when a segue_links row exists; VT beds keep default -11.
    et = (next_event_type or "").upper()
    if link is None and vt_event_id is None and et != "VOICE_TRACK":
        duck = 0.0

    return {
        "from_event_id": from_event_id,
        "to_event_id": to_event_id,
        "vt_event_id": int(vt_event_id) if vt_event_id is not None else None,
        "from_outro_mark_ms": from_outro_mark,
        "to_intro_mark_ms": to_intro_mark,
        "vt_in_ms": vt_in_ms,
        "vt_out_ms": int(vt_out_ms) if vt_out_ms is not None else None,
        "duck_db": float(duck),
        "crossfade_ms": crossfade,
        "notes": notes,
        "has_editor_link": link is not None,
    }

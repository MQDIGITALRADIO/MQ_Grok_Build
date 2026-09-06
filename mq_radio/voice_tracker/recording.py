"""Save browser-recorded VT audio into station data and attach to log events."""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mq_radio.config import DATA_DIR
from mq_radio.db.connection import get_connection


def vt_audio_dir(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir else DATA_DIR
    d = root / "vt"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_vt_recording(
    log_event_id: int,
    *,
    audio_b64: str,
    mime: str = "audio/webm",
    trim_in_ms: int = 0,
    trim_out_ms: Optional[int] = None,
    script_text: Optional[str] = None,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> dict:
    """Decode base64 audio, write under data/vt/, attach path to vt_scripts + log notes."""
    if not audio_b64:
        return {"ok": False, "error": "audio_b64 required"}

    conn = get_connection(db_path)
    ev = conn.execute("SELECT * FROM log_events WHERE id = ?", (log_event_id,)).fetchone()
    if not ev:
        conn.close()
        return {"ok": False, "error": f"event {log_event_id} not found"}

    raw = audio_b64
    if "," in raw and raw.strip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw)
    except Exception as exc:
        conn.close()
        return {"ok": False, "error": f"invalid base64: {exc}"}

    ext = "webm"
    mime_l = (mime or "").lower()
    if "wav" in mime_l:
        ext = "wav"
    elif "ogg" in mime_l:
        ext = "ogg"
    elif "mp4" in mime_l or "m4a" in mime_l:
        ext = "m4a"
    elif "mpeg" in mime_l or "mp3" in mime_l:
        ext = "mp3"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fname = f"vt_{log_event_id}_{stamp}.{ext}"
    out_dir = vt_audio_dir(data_dir)
    out_path = out_dir / fname
    out_path.write_bytes(blob)

    # Server-side trim: cut/re-encode when ffmpeg + IN/OUT; else markers-only
    # (manual announcer path: Record → mark in/out → Save take)
    tin = int(trim_in_ms or 0)
    tout = int(trim_out_ms) if trim_out_ms is not None else None
    cleaned_path = None
    trim_mode = "raw"
    trim_note = None
    has_trim = tout is not None and tout > tin
    try:
        from mq_radio.library.ingest import cut_segment, ffmpeg_available

        if has_trim and ffmpeg_available():
            clean = out_dir / f"vt_{log_event_id}_{stamp}_clean.wav"
            cut = cut_segment(out_path, clean, in_ms=tin, out_ms=tout)
            if cut.get("ok"):
                cleaned_path = clean
                out_path = clean
                ext = "wav"
                trim_mode = "cut"
            else:
                trim_mode = "markers_only"
                trim_note = cut.get("error") or "ffmpeg cut failed"
        elif has_trim:
            trim_mode = "markers_only"
            trim_note = "ffmpeg not on PATH — trim stored as markers only"
        else:
            trim_mode = "raw"
    except Exception as exc:
        cleaned_path = None
        if has_trim:
            trim_mode = "markers_only"
            trim_note = f"trim cut error: {exc}"

    rel = str(out_path)
    try:
        root = Path(data_dir) if data_dir else DATA_DIR
        rel = str(out_path.relative_to(root))
    except Exception:
        pass

    existing = conn.execute(
        "SELECT id, script_text FROM vt_scripts WHERE log_event_id = ?",
        (log_event_id,),
    ).fetchone()
    script = script_text if script_text is not None else (
        (existing["script_text"] if existing else None) or ev["title"] or "Recorded VT"
    )
    if existing:
        conn.execute(
            """UPDATE vt_scripts SET
                audio_path=?, trim_in_ms=?, trim_out_ms=?, recorded_at=datetime('now'),
                script_text=COALESCE(?, script_text), status='APPROVED',
                source='MIC_RECORD', updated_at=datetime('now')
               WHERE id=?""",
            (rel, int(trim_in_ms or 0), trim_out_ms, script, existing["id"]),
        )
        vt_id = int(existing["id"])
    else:
        cur = conn.execute(
            """INSERT INTO vt_scripts (
                log_event_id, variation, script_text, status, source,
                audio_path, trim_in_ms, trim_out_ms, recorded_at
            ) VALUES (?, 'recorded', ?, 'APPROVED', 'MIC_RECORD', ?, ?, ?, datetime('now'))""",
            (log_event_id, script or "Recorded VT", rel, int(trim_in_ms or 0), trim_out_ms),
        )
        vt_id = int(cur.lastrowid)

    notes = ev["notes"] or ""
    marker = f"[VT AUDIO {rel}]"
    if marker not in notes:
        notes = (notes + " " + marker).strip() if notes else marker
    conn.execute(
        """UPDATE log_events SET
            notes=?, manual_flag='MANUAL',
            title=CASE WHEN title IS NULL OR title IN ('VOICE_TRACK','VT — sample break')
                       THEN 'Recorded Voice Track' ELSE title END,
            event_type='VOICE_TRACK'
           WHERE id=?""",
        (notes, log_event_id),
    )
    # Register cleaned (or raw) take as a library VOICE_TRACK cart for Segment Editor
    track_id = None
    try:
        from mq_radio.library.ingest import upsert_track, probe_duration_ms

        dur = probe_duration_ms(Path(out_path))
        if tout is not None and tin is not None and tout > tin and cleaned_path:
            dur = tout - tin
        cart = upsert_track(
            Path(out_path),
            title=script or "Recorded Voice Track",
            artist="Announcer",
            event_type="VOICE_TRACK",
            duration_ms=dur or None,
            rotation_category="VT",
            notes_album=f"vt take event {log_event_id}",
            db_path=db_path,
        )
        if cart.get("ok"):
            track_id = cart["track_id"]
            # Point log event at this cart when empty track_id
            if not ev["track_id"]:
                conn.execute(
                    "UPDATE log_events SET track_id=? WHERE id=?",
                    (track_id, log_event_id),
                )
    except Exception:
        track_id = None

    conn.commit()
    conn.close()
    return {
        "ok": True,
        "vt_script_id": vt_id,
        "log_event_id": log_event_id,
        "audio_path": rel,
        "absolute_path": str(out_path),
        "trim_in_ms": int(trim_in_ms or 0),
        "trim_out_ms": trim_out_ms,
        "bytes": len(blob),
        "mime": mime if not cleaned_path else "audio/wav",
        "cleaned": bool(cleaned_path),
        "cut": bool(cleaned_path),
        "trim_mode": trim_mode,
        "trim_note": trim_note,
        "ffmpeg": trim_mode == "cut",
        "track_id": track_id,
        "message": (
            f"VT take saved ({trim_mode})"
            + (f" — {trim_note}" if trim_note else "")
        ),
    }



def attach_vt_cart(
    log_event_id: int,
    track_id: int,
    *,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> dict:
    """Attach an existing library cart (e.g. Segment Editor output) to a VT log event."""
    conn = get_connection(db_path)
    ev = conn.execute("SELECT * FROM log_events WHERE id = ?", (log_event_id,)).fetchone()
    if not ev:
        conn.close()
        return {"ok": False, "error": f"event {log_event_id} not found"}
    tr = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not tr:
        conn.close()
        return {"ok": False, "error": f"track {track_id} not found"}

    audio_path = tr["file_path"] or ""
    rel = audio_path
    try:
        root = Path(data_dir) if data_dir else DATA_DIR
        rel = str(Path(audio_path).resolve().relative_to(root.resolve()))
    except Exception:
        pass

    existing = conn.execute(
        "SELECT id FROM vt_scripts WHERE log_event_id = ?", (log_event_id,)
    ).fetchone()
    title = tr["title"] or "Voice Track"
    if existing:
        conn.execute(
            """UPDATE vt_scripts SET audio_path=?, recorded_at=datetime('now'),
               status='APPROVED', source='SEGMENT_EDITOR',
               script_text=COALESCE(NULLIF(script_text,''), ?),
               updated_at=datetime('now') WHERE id=?""",
            (rel, title, existing["id"]),
        )
        vt_id = int(existing["id"])
    else:
        cur = conn.execute(
            """INSERT INTO vt_scripts (
                log_event_id, variation, script_text, status, source, audio_path, recorded_at
            ) VALUES (?, 'segment', ?, 'APPROVED', 'SEGMENT_EDITOR', ?, datetime('now'))""",
            (log_event_id, title, rel),
        )
        vt_id = int(cur.lastrowid)

    notes = ev["notes"] or ""
    marker = f"[VT AUDIO {rel}]"
    if marker not in notes:
        notes = (notes + " " + marker).strip() if notes else marker
    conn.execute(
        """UPDATE log_events SET
            track_id=?, title=?, artist=?, duration_ms=?,
            event_type='VOICE_TRACK', manual_flag='MANUAL', notes=?
           WHERE id=?""",
        (
            track_id,
            title,
            tr["artist"] or "Announcer",
            int(tr["duration_ms"] or 0),
            notes,
            log_event_id,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "vt_script_id": vt_id,
        "log_event_id": log_event_id,
        "track_id": track_id,
        "audio_path": rel,
    }

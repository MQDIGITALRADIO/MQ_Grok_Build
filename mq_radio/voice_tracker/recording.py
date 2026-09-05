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
        "mime": mime,
    }

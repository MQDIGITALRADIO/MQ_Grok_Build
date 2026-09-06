"""Placeholder voice-track render for PD assist / overnight operator path.

Vocloner remains the default *real* voice renderer (clipboard + open URL; no
public API). Until a Vocloner WAV is dropped, operators (and CI) can attach a
honest PCM placeholder bed so the Living Log has a playable VOICE_TRACK cart.

AI stays upstairs only — this never picks MUSIC or mutates the music clock.
"""

from __future__ import annotations

import math
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mq_radio.config import DATA_DIR
from mq_radio.db.connection import get_connection, init_db
from mq_radio.voice_tracker.recording import attach_vt_cart, vt_audio_dir
from mq_radio.voice_tracker.script_generator import estimate_duration_ms

PLACEHOLDER_SOURCE = "PLACEHOLDER_RENDER"
_SAMPLE_RATE = 44_100
_MIN_MS = 2_000
_MAX_MS = 18_000
_BEEP_MS = 180
_BEEP_HZ = 440.0
_BEEP_AMP = 0.18


def write_placeholder_wav(
    path: Path,
    duration_ms: int,
    *,
    script_text: Optional[str] = None,
) -> dict:
    """Write a short audible marker + silence bed as 16-bit mono PCM WAV.

    Not a Vocloner voice — operator-clear placeholder so AUTO can advance a
    real cart until the true render is attached.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ms = int(duration_ms or 0)
    if ms <= 0 and script_text:
        ms = estimate_duration_ms(script_text)
    ms = max(_MIN_MS, min(ms if ms > 0 else _MIN_MS, _MAX_MS))
    n_frames = max(1, int(_SAMPLE_RATE * (ms / 1000.0)))
    beep_frames = min(int(_SAMPLE_RATE * (_BEEP_MS / 1000.0)), n_frames)
    samples: list[int] = []
    for i in range(n_frames):
        if i < beep_frames:
            t = i / _SAMPLE_RATE
            env = 1.0
            edge = int(_SAMPLE_RATE * 0.015)
            if i < edge:
                env = i / max(edge, 1)
            elif i > beep_frames - edge:
                env = max(0.0, (beep_frames - i) / max(edge, 1))
            val = _BEEP_AMP * env * math.sin(2.0 * math.pi * _BEEP_HZ * t)
            samples.append(int(round(val * 32767.0)))
        else:
            samples.append(0)
    raw = struct.pack("<" + "h" * len(samples), *samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(raw)
    return {
        "ok": True,
        "path": str(path),
        "duration_ms": ms,
        "sample_rate": _SAMPLE_RATE,
        "bytes": path.stat().st_size,
        "source": PLACEHOLDER_SOURCE,
        "note": "PCM placeholder (not Vocloner voice) — replace with Vocloner WAV when ready",
    }


def _event_script_row(conn, log_event_id: int) -> tuple[Optional[dict], Optional[dict]]:
    ev = conn.execute("SELECT * FROM log_events WHERE id = ?", (log_event_id,)).fetchone()
    if not ev:
        return None, None
    vt = conn.execute(
        "SELECT * FROM vt_scripts WHERE log_event_id = ?", (log_event_id,)
    ).fetchone()
    return dict(ev), (dict(vt) if vt else None)


def render_placeholder_vt(
    log_event_id: int,
    *,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    force: bool = False,
    duration_ms: Optional[int] = None,
) -> dict:
    """Render placeholder WAV for one VT event and attach it to the Living Log."""
    init_db(db_path)
    root = Path(data_dir) if data_dir else DATA_DIR
    conn = get_connection(db_path)
    try:
        ev, vt = _event_script_row(conn, int(log_event_id))
        if not ev:
            return {"ok": False, "error": f"event {log_event_id} not found"}
        if (ev.get("event_type") or "") != "VOICE_TRACK":
            return {
                "ok": False,
                "error": f"event {log_event_id} is {ev.get('event_type')}, not VOICE_TRACK",
            }

        script = ""
        status = None
        variation = "placeholder"
        if vt:
            script = (vt.get("script_text") or "").strip()
            status = (vt.get("status") or "").upper()
            variation = vt.get("variation") or variation
            existing_audio = (vt.get("audio_path") or "").strip()
            existing_source = (vt.get("source") or "").upper()
            if existing_audio and not force:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_has_audio",
                    "log_event_id": int(log_event_id),
                    "audio_path": existing_audio,
                    "source": vt.get("source"),
                    "message": "VT already has audio — pass force=true to replace",
                }
            if existing_audio and force and existing_source not in (
                PLACEHOLDER_SOURCE,
                "",
            ):
                # Protect real Vocloner / mic takes unless explicitly forced later
                if existing_source in ("MIC_RECORD", "SEGMENT_EDITOR", "VOCLONER"):
                    return {
                        "ok": True,
                        "skipped": True,
                        "reason": "protect_real_take",
                        "log_event_id": int(log_event_id),
                        "source": vt.get("source"),
                        "message": f"Refusing to overwrite {existing_source} take with placeholder",
                    }
            if status == "DRAFT":
                return {
                    "ok": False,
                    "error": "Approve the VT draft before placeholder render (AI upstairs → approve → render)",
                }
            if (variation or "").lower() == "silence" or not script:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "silence",
                    "log_event_id": int(log_event_id),
                    "message": "Silence / empty script — no placeholder cart",
                }
            if status and status != "APPROVED":
                return {
                    "ok": False,
                    "error": f"VT status is {status}; approve drafts before placeholder render",
                }
        else:
            script = (ev.get("title") or "").strip()
            if script in ("VOICE_TRACK", "VT", "AI Voice Track", "AI VT (silence)"):
                script = ""
            if not script:
                notes = ev.get("notes") or ""
                script = notes[:200].strip() if notes else ""
            if not script:
                return {
                    "ok": False,
                    "error": "No script on event — generate/approve AI breaks first",
                }
    finally:
        conn.close()

    dur = int(duration_ms) if duration_ms is not None else estimate_duration_ms(script)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = vt_audio_dir(root)
    out_path = out_dir / f"vt_placeholder_{log_event_id}_{stamp}.wav"
    written = write_placeholder_wav(out_path, dur, script_text=script)
    if not written.get("ok"):
        return written

    from mq_radio.library.ingest import upsert_track

    title = script if len(script) <= 80 else script[:77] + "..."
    cart = upsert_track(
        out_path,
        title=f"[Placeholder] {title}",
        artist="MQ Digital (placeholder)",
        event_type="VOICE_TRACK",
        duration_ms=int(written["duration_ms"]),
        rotation_category="VT",
        notes_album=f"placeholder render event {log_event_id} — not Vocloner",
        db_path=db_path,
    )
    if not cart.get("ok"):
        return {"ok": False, "error": cart.get("error") or "library upsert failed", **written}

    attached = attach_vt_cart(
        int(log_event_id),
        int(cart["track_id"]),
        db_path=db_path,
        data_dir=root,
    )
    if not attached.get("ok"):
        return {"ok": False, "error": attached.get("error") or "attach failed", **written, **cart}

    conn = get_connection(db_path)
    try:
        conn.execute(
            """UPDATE vt_scripts SET source=?, status='APPROVED',
               script_text=COALESCE(NULLIF(script_text,''), ?),
               updated_at=datetime('now')
               WHERE log_event_id=?""",
            (PLACEHOLDER_SOURCE, script, int(log_event_id)),
        )
        conn.execute(
            """UPDATE log_events SET
                title=CASE
                    WHEN title IS NULL OR title IN ('VOICE_TRACK','VT','AI Voice Track','AI VT (silence)')
                    THEN ? ELSE title END,
                notes=CASE
                    WHEN notes LIKE '%[VT PLACEHOLDER]%' THEN notes
                    ELSE trim(COALESCE(notes,'') || ' [VT PLACEHOLDER — replace with Vocloner WAV]')
                END,
                manual_flag='MANUAL'
               WHERE id=?""",
            (f"[Placeholder] {title}", int(log_event_id)),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "skipped": False,
        "log_event_id": int(log_event_id),
        "track_id": int(cart["track_id"]),
        "vt_script_id": attached.get("vt_script_id"),
        "audio_path": attached.get("audio_path"),
        "absolute_path": str(out_path),
        "duration_ms": int(written["duration_ms"]),
        "source": PLACEHOLDER_SOURCE,
        "variation": variation,
        "script_preview": title,
        "message": (
            "Placeholder PCM attached to Living Log — replace with Vocloner WAV when ready. "
            "AI never picks MUSIC live."
        ),
    }


def render_placeholders_for_date(
    log_date: str,
    *,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    force: bool = False,
    only_approved: bool = True,
    limit: Optional[int] = None,
) -> dict:
    """Batch placeholder render for APPROVED VTs lacking audio on a Living Log date."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        daily = conn.execute(
            "SELECT id FROM daily_logs WHERE log_date = ?", (log_date,)
        ).fetchone()
        if not daily:
            return {
                "ok": False,
                "error": f"No living log for {log_date}. Run generate-log first.",
                "log_date": log_date,
                "rendered": 0,
                "skipped": 0,
            }
        sql = """
            SELECT e.id AS log_event_id, v.status, v.audio_path, v.variation, v.script_text
            FROM log_events e
            LEFT JOIN vt_scripts v ON v.log_event_id = e.id
            WHERE e.daily_log_id = ? AND e.event_type = 'VOICE_TRACK'
            ORDER BY e.position
        """
        rows = [dict(r) for r in conn.execute(sql, (daily["id"],)).fetchall()]
    finally:
        conn.close()

    rendered: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for row in rows:
        if only_approved:
            st = (row.get("status") or "").upper()
            if st and st != "APPROVED":
                skipped.append(
                    {"log_event_id": row["log_event_id"], "reason": f"status_{st or 'missing'}"}
                )
                continue
            if not st:
                skipped.append({"log_event_id": row["log_event_id"], "reason": "no_vt_script"})
                continue
        if limit is not None and len(rendered) >= int(limit):
            break
        result = render_placeholder_vt(
            int(row["log_event_id"]),
            db_path=db_path,
            data_dir=data_dir,
            force=force,
        )
        if result.get("ok") and result.get("skipped"):
            skipped.append(result)
        elif result.get("ok"):
            rendered.append(result)
        else:
            errors.append(result)

    return {
        "ok": len(errors) == 0,
        "log_date": log_date,
        "rendered": len(rendered),
        "skipped": len(skipped),
        "errors": len(errors),
        "rendered_detail": rendered,
        "skipped_detail": skipped,
        "error_detail": errors,
        "source": PLACEHOLDER_SOURCE,
        "message": (
            f"Placeholder render: {len(rendered)} attached, {len(skipped)} skipped, "
            f"{len(errors)} errors — Vocloner still the real voice path"
        ),
    }


def run_pd_assist_operator_path(
    log_date: str,
    *,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    station_name: str = "MQ Digital",
    style: str = "warm",
    insert_gaps: bool = True,
    approve: bool = True,
    render_placeholders: bool = True,
    force_placeholder: bool = False,
    max_per_hour: int = 2,
    stride: int = 2,
) -> dict:
    """Overnight / PD assist: AI scripts → approve → placeholder attach.

    Music selection stays with the deterministic scheduler (already on the log).
    This path only touches VOICE_TRACK / vt_scripts — AI upstairs only.
    """
    from mq_radio.voice_tracker.inserter import generate_ai_breaks
    from mq_radio.voice_tracker.service import approve_ai_breaks

    gen = generate_ai_breaks(
        log_date,
        db_path=db_path,
        station_name=station_name,
        style=style,
        insert_gaps=insert_gaps,
        max_per_hour=max_per_hour,
        stride=stride,
    )
    if not gen.get("ok"):
        return {
            "ok": False,
            "log_date": log_date,
            "step": "generate_ai_breaks",
            "generate": gen,
            "error": gen.get("error") or "generate_ai_breaks failed",
            "ai_upstairs_only": True,
        }

    approved = {"ok": True, "approved": 0, "skipped": True, "reason": "approve_disabled"}
    if approve:
        approved = approve_ai_breaks(log_date, db_path=db_path)
        if not approved.get("ok"):
            return {
                "ok": False,
                "log_date": log_date,
                "step": "approve_ai_breaks",
                "generate": gen,
                "approve": approved,
                "error": approved.get("error") or "approve failed",
                "ai_upstairs_only": True,
            }

    rendered = {"ok": True, "rendered": 0, "skipped": True, "reason": "render_disabled"}
    if render_placeholders:
        rendered = render_placeholders_for_date(
            log_date,
            db_path=db_path,
            data_dir=data_dir,
            force=force_placeholder,
            only_approved=True,
        )

    ok = bool(gen.get("ok")) and bool(approved.get("ok")) and bool(rendered.get("ok"))
    return {
        "ok": ok,
        "log_date": log_date,
        "ai_upstairs_only": True,
        "music_live_pick": False,
        "generate": {
            "filled": gen.get("filled"),
            "inserted": gen.get("inserted"),
            "drafts": gen.get("drafts"),
        },
        "approve": {"approved": approved.get("approved", 0)},
        "placeholder_render": {
            "rendered": rendered.get("rendered", 0),
            "skipped": rendered.get("skipped", 0),
            "errors": rendered.get("errors", 0),
            "source": PLACEHOLDER_SOURCE,
        },
        "next_operator_step": (
            "Open approved VT → Render in Vocloner → drop WAV into library/VT slot "
            "(or Import VT inbox). Placeholder carts keep AUTO moving until then."
        ),
        "message": (
            f"PD assist path: filled {gen.get('filled')}, inserted {gen.get('inserted')}, "
            f"approved {approved.get('approved', 0)}, placeholders {rendered.get('rendered', 0)}. "
            "AI never picks MUSIC live."
        ),
    }


__all__ = [
    "PLACEHOLDER_SOURCE",
    "write_placeholder_wav",
    "render_placeholder_vt",
    "render_placeholders_for_date",
    "run_pd_assist_operator_path",
]

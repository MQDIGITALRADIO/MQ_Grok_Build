"""Vocloner operator path — clipboard / script export (no public API).

Honest scope
------------
Vocloner has **no public API**. MQ never pretends to call one. The operator path is:

1. Approve VT script (Living Log / CLI).
2. **Copy** clipboard text (or export ``.txt``) from MQ.
3. Open Vocloner → **paste** → generate → export **WAV**.
4. Drop WAV into library / VT slot, or **Import VT folder** (inbox).

This module builds clipboard-ready payloads and optional on-disk ``.txt`` packages
under ``data/vocloner-export/`` so paste still works when the browser clipboard
is blocked (Electron / insecure context / permissions).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR
from mq_radio.db.connection import get_connection, init_db
from mq_radio.web.settings_store import load_vocloner

VOCLONER_URL = "https://vocloner.com/"
VOCLONER_SOURCE = "VOCLONER"
PUBLIC_API = False  # hard rule — never claim a Vocloner HTTP API

OPERATOR_STEPS: tuple[str, ...] = (
    "Approve the VT script (Living Log → Approve drafts, or CLI approve-ai-breaks).",
    "Copy script (Render in Vocloner / Copy script) or Export .txt from MQ.",
    "Open Vocloner → paste the script → generate with your preferred model/voice.",
    "Export WAV from Vocloner.",
    "Import WAV: drop onto desk Import audio, or Settings VT inbox → Import VT folder "
    "(select the Living Log VT row to attach).",
)

DESK_FLOW_SHORT = (
    "paste into Vocloner → export WAV → Import VT folder / drop into library"
)


def _slug(text: str, *, max_len: int = 48) -> str:
    raw = (text or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not raw:
        raw = "vt-script"
    return raw[:max_len].rstrip("-")


def vocloner_export_dir(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    d = root / "vocloner-export"
    d.mkdir(parents=True, exist_ok=True)
    return d


def operator_desk_flow(*, preferred_model: str = "") -> dict[str, Any]:
    """Clear desk-facing operator flow (no fake API)."""
    model = (preferred_model or "").strip()
    return {
        "ok": True,
        "voice_renderer": "vocloner",
        "public_api": PUBLIC_API,
        "url": VOCLONER_URL,
        "preferred_model": model,
        "desk_flow": DESK_FLOW_SHORT,
        "steps": list(OPERATOR_STEPS),
        "clipboard": "MQ copies the approved script; paste inside Vocloner (no API).",
        "import_wav": (
            "After Vocloner exports WAV: desk Import audio, or Import VT folder "
            "(attaches to selected Living Log VT when selected)."
        ),
        "message": (
            "No Vocloner public API — clipboard/script export → paste → WAV → import."
        ),
    }


def build_clipboard_text(
    script_text: str,
    *,
    meta: Optional[dict[str, Any]] = None,
    preferred_model: str = "",
    include_header: bool = True,
) -> str:
    """Plain text for clipboard paste into Vocloner.

    Body is the script alone when ``include_header`` is False (best for paste).
    With header, a short MQ operator banner sits above a clear PASTE BELOW marker.
    """
    script = (script_text or "").strip()
    if not include_header:
        return script

    meta = meta or {}
    lines = [
        "=== MQ Radio → Vocloner (paste below) ===",
        f"No public API — paste into Vocloner, export WAV, import back. {VOCLONER_URL}",
    ]
    if preferred_model:
        lines.append(f"Preferred model/voice: {preferred_model}")
    eid = meta.get("log_event_id") or meta.get("event_id")
    if eid is not None:
        lines.append(f"Living Log event: {eid}")
    if meta.get("log_date"):
        lines.append(f"Log date: {meta['log_date']}")
    if meta.get("variation"):
        lines.append(f"Variation: {meta['variation']}")
    if meta.get("daypart"):
        lines.append(f"Daypart: {meta['daypart']}")
    if meta.get("vt_id"):
        lines.append(f"vt_scripts id: {meta['vt_id']}")
    lines.append("--- PASTE BELOW INTO VOCLONER ---")
    lines.append(script)
    lines.append("--- END SCRIPT ---")
    lines.append(
        "Next: Vocloner → export WAV → MQ desk Import audio / Import VT folder."
    )
    return "\n".join(lines)


def build_paste_body(script_text: str) -> str:
    """Script-only body — what operators usually paste into Vocloner."""
    return (script_text or "").strip()


def export_script_package(
    script_text: str,
    *,
    data_dir: Optional[Path] = None,
    meta: Optional[dict[str, Any]] = None,
    preferred_model: str = "",
    filename_stem: Optional[str] = None,
    write_sidecar: bool = True,
) -> dict[str, Any]:
    """Write clipboard-ready ``.txt`` (+ optional JSON sidecar) under vocloner-export/.

    Returns clipboard_text (paste body) + clipboard_packet (headered) + paths.
    """
    script = (script_text or "").strip()
    if not script:
        return {
            "ok": False,
            "error": "No script to export — approve/generate a VT first",
            "public_api": PUBLIC_API,
        }

    meta = dict(meta or {})
    cfg = load_vocloner(data_dir)
    model = (preferred_model or cfg.get("preferred_model") or "").strip()
    out_dir = vocloner_export_dir(data_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = filename_stem or _slug(
        f"vt-{meta.get('log_event_id') or meta.get('vt_id') or 'script'}-"
        f"{meta.get('variation') or 'break'}"
    )
    base = f"{stamp}_{stem}"
    txt_path = out_dir / f"{base}.txt"
    paste_body = build_paste_body(script)
    packet = build_clipboard_text(
        script, meta=meta, preferred_model=model, include_header=True
    )
    # File holds paste body first (easy select-all), then a short footer for humans
    file_body = (
        paste_body
        + "\n\n"
        + "# MQ Radio Vocloner export — paste the script above into Vocloner.\n"
        + f"# Then: export WAV → Import VT folder / drop into library. URL: {VOCLONER_URL}\n"
    )
    if model:
        file_body += f"# Preferred model/voice: {model}\n"
    txt_path.write_text(file_body, encoding="utf-8")

    sidecar_path = None
    if write_sidecar:
        sidecar_path = out_dir / f"{base}.json"
        sidecar = {
            "ok": True,
            "public_api": PUBLIC_API,
            "voice_renderer": "vocloner",
            "url": cfg.get("url") or VOCLONER_URL,
            "preferred_model": model,
            "script_chars": len(paste_body),
            "meta": meta,
            "txt_path": str(txt_path),
            "desk_flow": DESK_FLOW_SHORT,
            "steps": list(OPERATOR_STEPS),
            "exported_at": stamp,
        }
        sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "public_api": PUBLIC_API,
        "voice_renderer": "vocloner",
        "url": cfg.get("url") or VOCLONER_URL,
        "preferred_model": model,
        "clipboard_text": paste_body,
        "clipboard_packet": packet,
        "script_chars": len(paste_body),
        "txt_path": str(txt_path),
        "sidecar_path": str(sidecar_path) if sidecar_path else None,
        "export_dir": str(out_dir),
        "desk_flow": DESK_FLOW_SHORT,
        "steps": list(OPERATOR_STEPS),
        "meta": meta,
        "message": (
            "Script exported — copy/paste into Vocloner → export WAV → Import VT folder. "
            "No Vocloner public API."
        ),
    }


def export_vt_script(
    *,
    log_event_id: Optional[int] = None,
    vt_id: Optional[int] = None,
    script_text: Optional[str] = None,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    preferred_model: str = "",
    require_approved: bool = False,
) -> dict[str, Any]:
    """Resolve a VT row (or raw script) and export the Vocloner package."""
    meta: dict[str, Any] = {}
    text = (script_text or "").strip()
    status = None

    if (log_event_id is not None or vt_id is not None) and not text:
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            if vt_id is not None:
                row = conn.execute(
                    """
                    SELECT v.*, e.position, e.scheduled_at, d.log_date
                    FROM vt_scripts v
                    JOIN log_events e ON e.id = v.log_event_id
                    JOIN daily_logs d ON d.id = e.daily_log_id
                    WHERE v.id = ?
                    """,
                    (int(vt_id),),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT v.*, e.position, e.scheduled_at, d.log_date
                    FROM vt_scripts v
                    JOIN log_events e ON e.id = v.log_event_id
                    JOIN daily_logs d ON d.id = e.daily_log_id
                    WHERE v.log_event_id = ?
                    """,
                    (int(log_event_id),),
                ).fetchone()
            if not row:
                return {
                    "ok": False,
                    "error": "VT script not found",
                    "public_api": PUBLIC_API,
                }
            r = dict(row)
            text = (r.get("script_text") or "").strip()
            status = (r.get("status") or "").upper()
            meta = {
                "vt_id": int(r["id"]),
                "log_event_id": int(r["log_event_id"]),
                "log_date": r.get("log_date"),
                "variation": r.get("variation"),
                "daypart": r.get("daypart"),
                "status": status,
                "position": r.get("position"),
            }
        finally:
            conn.close()

    if require_approved and status and status != "APPROVED":
        return {
            "ok": False,
            "error": f"VT status is {status} — approve before Vocloner export",
            "public_api": PUBLIC_API,
            "meta": meta,
        }

    if log_event_id is not None and "log_event_id" not in meta:
        meta["log_event_id"] = int(log_event_id)

    return export_script_package(
        text,
        data_dir=data_dir,
        meta=meta,
        preferred_model=preferred_model,
    )


def export_approved_for_date(
    log_date: str,
    *,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    preferred_model: str = "",
    limit: Optional[int] = None,
    skip_silence: bool = True,
) -> dict[str, Any]:
    """Export all APPROVED non-empty VT scripts for a Living Log date."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT v.*, e.position, e.scheduled_at, d.log_date
                FROM vt_scripts v
                JOIN log_events e ON e.id = v.log_event_id
                JOIN daily_logs d ON d.id = e.daily_log_id
                WHERE d.log_date = ? AND v.status = 'APPROVED'
                ORDER BY e.position
                """,
                (log_date,),
            ).fetchall()
        ]
    finally:
        conn.close()

    exported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for r in rows:
        text = (r.get("script_text") or "").strip()
        variation = (r.get("variation") or "").lower()
        if skip_silence and (variation == "silence" or not text):
            skipped.append(
                {
                    "vt_id": int(r["id"]),
                    "log_event_id": int(r["log_event_id"]),
                    "reason": "silence_or_empty",
                }
            )
            continue
        if not text:
            skipped.append(
                {
                    "vt_id": int(r["id"]),
                    "log_event_id": int(r["log_event_id"]),
                    "reason": "empty_script",
                }
            )
            continue
        meta = {
            "vt_id": int(r["id"]),
            "log_event_id": int(r["log_event_id"]),
            "log_date": r.get("log_date") or log_date,
            "variation": r.get("variation"),
            "daypart": r.get("daypart"),
            "status": "APPROVED",
            "position": r.get("position"),
        }
        one = export_script_package(
            text,
            data_dir=data_dir,
            meta=meta,
            preferred_model=preferred_model,
        )
        if one.get("ok"):
            exported.append(one)
        else:
            skipped.append(
                {
                    "vt_id": int(r["id"]),
                    "log_event_id": int(r["log_event_id"]),
                    "reason": one.get("error") or "export_failed",
                }
            )
        if limit is not None and len(exported) >= int(limit):
            break

    cfg = load_vocloner(data_dir)
    return {
        "ok": True,
        "public_api": PUBLIC_API,
        "log_date": log_date,
        "exported": len(exported),
        "skipped": len(skipped),
        "items": exported,
        "skipped_items": skipped,
        "export_dir": str(vocloner_export_dir(data_dir)),
        "url": cfg.get("url") or VOCLONER_URL,
        "preferred_model": (preferred_model or cfg.get("preferred_model") or "").strip(),
        "desk_flow": DESK_FLOW_SHORT,
        "steps": list(OPERATOR_STEPS),
        "message": (
            f"Exported {len(exported)} approved VT script(s) for Vocloner paste. "
            "No public API — paste → WAV → Import VT folder."
        ),
    }


def library_root_status(data_dir: Optional[Path] = None) -> dict[str, Any]:
    """Settings empty-state clarity for MQ Digital library root."""
    from mq_radio.library.ingest import library_audio_dir, library_root_config_path

    root = Path(data_dir) if data_dir is not None else DATA_DIR
    path = library_audio_dir(data_dir)
    cfg = library_root_config_path(data_dir)
    default_path = (root / "library").resolve()
    try:
        is_default = path.resolve() == default_path
    except OSError:
        is_default = str(path).endswith("/library") or str(path).endswith("\\library")
    exists = path.is_dir()
    audio_n = 0
    if exists:
        for pat in ("*.wav", "*.mp3", "*.flac", "*.m4a", "*.ogg"):
            audio_n += len(list(path.glob(pat)))
    empty = (not exists) or audio_n == 0
    if not exists:
        empty_hint = "Library folder missing — Save Settings to create, or set a path."
    elif empty:
        empty_hint = (
            "Library root is empty — Import audio / drop carts, or run seed-demo. "
            "Vocloner WAVs land here (or under vt/) when imported."
        )
    else:
        empty_hint = ""
    source = "env" if __import__("os").environ.get("MQ_RADIO_LIBRARY_ROOT") else (
        "config" if cfg.exists() else "default"
    )
    return {
        "ok": True,
        "path": str(path),
        "exists": exists,
        "is_default": is_default,
        "source": source,
        "audio_files": audio_n,
        "empty": empty,
        "empty_hint": empty_hint,
        "config": str(cfg) if cfg.exists() else None,
        "operator_message": empty_hint
        or (
            f"Library root ready ({audio_n} audio file(s))"
            + (" · default data/library" if is_default else f" · custom ({source})")
        ),
    }


__all__ = [
    "DESK_FLOW_SHORT",
    "OPERATOR_STEPS",
    "PUBLIC_API",
    "VOCLONER_SOURCE",
    "VOCLONER_URL",
    "build_clipboard_text",
    "build_paste_body",
    "export_approved_for_date",
    "export_script_package",
    "export_vt_script",
    "library_root_status",
    "operator_desk_flow",
    "vocloner_export_dir",
]

"""Persist On-Air UI settings (routing matrix, Vocloner, AU insert stub) under data/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mq_radio.config import DATA_DIR
from mq_radio.engine.audio_devices import (
    MOCK_INPUT_DEVICES,
    MOCK_OUTPUT_DEVICES,
    NATIVE_INSERT_OPTIONS,
    list_audio_devices,
)
from mq_radio.engine.audio_router import apply_audio_route_from_settings

SETTINGS_FILE = DATA_DIR / "audio_outputs.json"

# Studio routing matrix — Program is always the processed on-air bus.
DEFAULT_OUTPUTS = {
    "program": "builtin",          # Program / On-Air (processed)
    "monitor": "builtin",          # Monitor / Cue
    "headphones": "usb",           # Headphones / Talent
    "aux1": "none",                # Aux send 1
    "aux2": "none",                # Aux send 2
    "mix_minus": "usb",            # Mix-minus out (caller hears program − their return)
    "stream": "same_as_program",   # Stream encode
    "record": "none",              # Record bus
}

# Inputs (paired with mix-minus for Zoom/phone)
DEFAULT_INPUTS = {
    "aux_in": "none",              # Aux / caller return (Zoom, phone hybrid, etc.)
    "mic": "none",                 # Talent mic (stub for later)
}

# Optional AU insert on Program path — empty = native processing is main output.
# Real AU hosting is Mac-later / production-bus; web demo is config + UI only.
DEFAULT_INSERT = {
    "slot": "none",                # none | native_only | (future au:<id>)
    "mode": "native_when_empty",   # when slot empty → native chain; when AU present → plugin then/instead
    "label": "(none) — Native processing",
}

# Back-compat aliases used by tests / older callers
MOCK_DEVICES = list(MOCK_OUTPUT_DEVICES)
MOCK_INPUTS = list(MOCK_INPUT_DEVICES)
INSERT_OPTIONS = list(NATIVE_INSERT_OPTIONS)


def _path(db_dir: Path | None = None) -> Path:
    if db_dir is not None:
        return Path(db_dir) / "audio_outputs.json"
    return SETTINGS_FILE


def _clean_map(defaults: dict[str, str], incoming: dict | None) -> dict[str, str]:
    cleaned = dict(defaults)
    if not isinstance(incoming, dict):
        return cleaned
    for key in defaults:
        if key in incoming and isinstance(incoming[key], str):
            cleaned[key] = incoming[key]
    return cleaned


def _device_catalogue() -> dict[str, Any]:
    """Live CoreAudio or mock catalogue for Settings dropdowns."""
    try:
        return list_audio_devices(include_audio_units=True)
    except Exception as exc:  # pragma: no cover — never break Settings load
        return {
            "source": "mock",
            "platform": "unknown",
            "devices": list(MOCK_DEVICES),
            "input_devices": list(MOCK_INPUTS),
            "audio_units": [],
            "insert_options": list(INSERT_OPTIONS),
            "note": f"Device enum failed ({exc}); using mock catalogue.",
            "backend": "mock",
        }


def _envelope(
    outputs: dict[str, str],
    inputs: dict[str, str],
    insert: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    catalogue = _device_catalogue()
    insert_options = catalogue.get("insert_options") or list(INSERT_OPTIONS)
    # Sync label from slot against live options (includes discovered AUs on Mac)
    for opt in insert_options:
        if opt.get("id") == insert.get("slot"):
            insert = {**insert, "label": opt.get("label") or insert.get("label")}
            break
    envelope = {
        "outputs": outputs,
        "inputs": inputs,
        "insert": insert,
        "devices": catalogue.get("devices") or list(MOCK_DEVICES),
        "input_devices": catalogue.get("input_devices") or list(MOCK_INPUTS),
        "insert_options": insert_options,
        "device_source": catalogue.get("source") or "mock",
        "device_platform": catalogue.get("platform"),
        "device_backend": catalogue.get("backend"),
        "device_note": catalogue.get("note"),
        "audio_units": catalogue.get("audio_units") or [],
        "mix_minus": {
            "output_role": "mix_minus",
            "paired_input_role": "aux_in",
            "paired_input_device": inputs.get("aux_in", "none"),
            "output_device": outputs.get("mix_minus", "none"),
            "description": (
                "Mix-minus = Program (processed) minus Aux input return — "
                "caller/Zoom hears the show without their own voice."
            ),
        },
        "source": source,
    }
    # Reflect current router status (do not re-apply on every load — save applies)
    try:
        from mq_radio.engine.audio_router import get_audio_router

        envelope["audio_route"] = get_audio_router().status()
    except Exception:
        envelope["audio_route"] = {
            "program": {"device_id": outputs.get("program"), "state": "idle"},
            "source": catalogue.get("source") or "mock",
            "active": False,
        }
    return envelope


def load_audio_outputs(db_dir: Path | None = None) -> dict[str, Any]:
    path = _path(db_dir)
    if not path.exists():
        return _envelope(
            dict(DEFAULT_OUTPUTS),
            dict(DEFAULT_INPUTS),
            dict(DEFAULT_INSERT),
            source="defaults",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_out = data.get("outputs") or data
        # Ignore non-output keys if old flat format
        outputs = _clean_map(DEFAULT_OUTPUTS, raw_out if isinstance(raw_out, dict) else {})
        inputs = _clean_map(
            DEFAULT_INPUTS,
            data.get("inputs") if isinstance(data.get("inputs"), dict) else {},
        )
        insert_in = data.get("insert") if isinstance(data.get("insert"), dict) else {}
        insert = {**DEFAULT_INSERT, **{k: insert_in[k] for k in DEFAULT_INSERT if k in insert_in}}
        return _envelope(outputs, inputs, insert, source=str(path))
    except (OSError, json.JSONDecodeError):
        return _envelope(
            dict(DEFAULT_OUTPUTS),
            dict(DEFAULT_INPUTS),
            dict(DEFAULT_INSERT),
            source="defaults",
        )


def save_audio_outputs(payload: dict[str, Any], db_dir: Path | None = None) -> dict[str, Any]:
    """Save outputs and optional inputs/insert. Accepts legacy flat outputs dict."""
    path = _path(db_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    if "outputs" in payload and isinstance(payload["outputs"], dict):
        outputs_in = payload["outputs"]
    else:
        # Legacy: entire payload is outputs map (filter known keys)
        outputs_in = {k: v for k, v in payload.items() if k in DEFAULT_OUTPUTS and isinstance(v, str)}

    outputs = _clean_map(DEFAULT_OUTPUTS, outputs_in)
    inputs = _clean_map(
        DEFAULT_INPUTS,
        payload.get("inputs") if isinstance(payload.get("inputs"), dict) else None,
    )
    insert_in = payload.get("insert") if isinstance(payload.get("insert"), dict) else {}
    insert = dict(DEFAULT_INSERT)
    if isinstance(insert_in.get("slot"), str):
        insert["slot"] = insert_in["slot"]
    if isinstance(insert_in.get("mode"), str):
        insert["mode"] = insert_in["mode"]

    # Resolve label from live insert options (native + optional Mac AU list)
    catalogue = _device_catalogue()
    for opt in catalogue.get("insert_options") or INSERT_OPTIONS:
        if opt.get("id") == insert["slot"]:
            insert["label"] = opt.get("label") or insert["label"]
            break

    stored = {"outputs": outputs, "inputs": inputs, "insert": insert}
    path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    loaded = load_audio_outputs(db_dir)
    # Apply CoreAudio / mock router so Program follows selected device
    try:
        route = apply_audio_route_from_settings(loaded)
        loaded = {**loaded, "audio_route": route}
    except Exception as exc:  # pragma: no cover
        loaded = {
            **loaded,
            "audio_route": {
                "program": {"device_id": outputs.get("program"), "state": "error"},
                "active": False,
                "error": str(exc),
                "source": loaded.get("device_source") or "mock",
            },
        }
    return {"ok": True, **loaded, "path": str(path)}


VOCLONER_FILE = DATA_DIR / "vocloner.json"

DEFAULT_VOCLONER = {
    "voice_renderer": "vocloner",
    "preferred_model": "",
    "notes": (
        "Matt Vocloner Basic Yearly (~1.2M chars/year). "
        "Default voice renderer — no public API; paste approved script in Vocloner, "
        "export WAV, drop into library/VT slot."
    ),
    "url": "https://vocloner.com/",
}


def _vocloner_path(db_dir: Path | None = None) -> Path:
    if db_dir is not None:
        return Path(db_dir) / "vocloner.json"
    return VOCLONER_FILE


def load_vocloner(db_dir: Path | None = None) -> dict[str, Any]:
    path = _vocloner_path(db_dir)
    if not path.exists():
        return {**DEFAULT_VOCLONER, "source": "defaults"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {**DEFAULT_VOCLONER, "source": "defaults"}
        merged = {**DEFAULT_VOCLONER, **data}
        merged["voice_renderer"] = "vocloner"
        return {**merged, "source": str(path)}
    except (OSError, json.JSONDecodeError):
        return {**DEFAULT_VOCLONER, "source": "defaults"}


def save_vocloner(payload: dict[str, Any], db_dir: Path | None = None) -> dict[str, Any]:
    path = _vocloner_path(db_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_vocloner(db_dir)
    cleaned = {
        "voice_renderer": "vocloner",
        "preferred_model": str(
            payload.get("preferred_model", current.get("preferred_model", "")) or ""
        ).strip(),
        "notes": str(payload.get("notes", current.get("notes", "")) or "").strip(),
        "url": str(payload.get("url", current.get("url", DEFAULT_VOCLONER["url"])) or DEFAULT_VOCLONER["url"]).strip()
        or DEFAULT_VOCLONER["url"],
    }
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **cleaned, "path": str(path)}

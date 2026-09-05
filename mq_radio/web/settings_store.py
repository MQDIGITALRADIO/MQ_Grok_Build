"""Persist On-Air UI settings (audio outputs + Vocloner voice renderer) to JSON under data/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mq_radio.config import DATA_DIR

SETTINGS_FILE = DATA_DIR / "audio_outputs.json"

DEFAULT_OUTPUTS = {
    "program": "builtin",
    "monitor": "builtin",
    "headphones": "usb",
    "stream": "same_as_program",
    "record": "none",
}

MOCK_DEVICES = [
    {"id": "builtin", "label": "Built-in Output"},
    {"id": "usb", "label": "USB Interface"},
    {"id": "aggregate", "label": "Aggregate Device"},
    {"id": "blackhole", "label": "BlackHole 2ch"},
    {"id": "none", "label": "None"},
    {"id": "same_as_program", "label": "Same as Program"},
]


def _path(db_dir: Path | None = None) -> Path:
    if db_dir is not None:
        return Path(db_dir) / "audio_outputs.json"
    return SETTINGS_FILE


def load_audio_outputs(db_dir: Path | None = None) -> dict[str, Any]:
    path = _path(db_dir)
    if not path.exists():
        return {
            "outputs": dict(DEFAULT_OUTPUTS),
            "devices": list(MOCK_DEVICES),
            "source": "defaults",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        outputs = {**DEFAULT_OUTPUTS, **(data.get("outputs") or data)}
        return {
            "outputs": outputs,
            "devices": list(MOCK_DEVICES),
            "source": str(path),
        }
    except (OSError, json.JSONDecodeError):
        return {
            "outputs": dict(DEFAULT_OUTPUTS),
            "devices": list(MOCK_DEVICES),
            "source": "defaults",
        }


def save_audio_outputs(outputs: dict[str, str], db_dir: Path | None = None) -> dict[str, Any]:
    path = _path(db_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {**DEFAULT_OUTPUTS}
    for key in DEFAULT_OUTPUTS:
        if key in outputs and isinstance(outputs[key], str):
            cleaned[key] = outputs[key]
    payload = {"outputs": cleaned}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "outputs": cleaned, "path": str(path)}

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

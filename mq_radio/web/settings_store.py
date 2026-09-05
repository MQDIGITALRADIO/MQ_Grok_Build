"""Persist On-Air UI settings (audio output routing) to JSON under data/."""

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

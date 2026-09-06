"""AI DJ / overnight volume ramp profiles for the program play path.

Profiles drive Web Audio GainNode automation (and a future engine).
In/out times are milliseconds; curve is linear or equal-power.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR

RAMPS_FILE = "ramps.json"

DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "id": "default",
        "label": "Default",
        "fade_in_ms": 40,
        "fade_out_ms": 80,
        "curve": "linear",
        "peak_gain": 1.0,
    },
    "soft": {
        "id": "soft",
        "label": "Soft in/out",
        "fade_in_ms": 800,
        "fade_out_ms": 1600,
        "curve": "equal_power",
        "peak_gain": 1.0,
    },
    "overnight": {
        "id": "overnight",
        "label": "Overnight / AI DJ",
        "fade_in_ms": 1200,
        "fade_out_ms": 2500,
        "curve": "equal_power",
        "peak_gain": 0.92,
        "ai_dj": True,
    },
    "imaging": {
        "id": "imaging",
        "label": "Imaging / sweeper",
        "fade_in_ms": 8,
        "fade_out_ms": 40,
        "curve": "linear",
        "peak_gain": 1.0,
    },
    "hard": {
        "id": "hard",
        "label": "Hard cut",
        "fade_in_ms": 0,
        "fade_out_ms": 0,
        "curve": "linear",
        "peak_gain": 1.0,
    },
}

DEFAULT_STATE = {
    "active_profile": "default",
    "ai_dj_profile": "overnight",
    "profiles": copy.deepcopy(DEFAULT_PROFILES),
}


def _path(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    return root / RAMPS_FILE


def default_ramps() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_STATE)


def normalize_ramps(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_ramps()
    if not payload or not isinstance(payload, dict):
        return base
    profiles = copy.deepcopy(DEFAULT_PROFILES)
    incoming = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {}
    for key, val in incoming.items():
        if isinstance(val, dict):
            cur = profiles.get(key, {"id": key, "label": key})
            profiles[key] = {**cur, **val, "id": key}
    active = str(payload.get("active_profile") or base["active_profile"])
    if active not in profiles:
        active = "default"
    ai = str(payload.get("ai_dj_profile") or base["ai_dj_profile"])
    if ai not in profiles:
        ai = "overnight"
    return {
        "active_profile": active,
        "ai_dj_profile": ai,
        "profiles": profiles,
        "active": profiles[active],
        "ai_dj": profiles[ai],
    }


def load_ramps(data_dir: Optional[Path] = None) -> dict[str, Any]:
    path = _path(data_dir)
    if not path.exists():
        out = default_ramps()
        out["active"] = out["profiles"][out["active_profile"]]
        out["ai_dj"] = out["profiles"][out["ai_dj_profile"]]
        out["source"] = "defaults"
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = normalize_ramps(data if isinstance(data, dict) else {})
        out["source"] = str(path)
        return out
    except (OSError, json.JSONDecodeError):
        out = default_ramps()
        out["active"] = out["profiles"][out["active_profile"]]
        out["ai_dj"] = out["profiles"][out["ai_dj_profile"]]
        out["source"] = "defaults"
        return out


def save_ramps(payload: dict[str, Any], data_dir: Optional[Path] = None) -> dict[str, Any]:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    chain = normalize_ramps(payload)
    to_store = {
        "active_profile": chain["active_profile"],
        "ai_dj_profile": chain["ai_dj_profile"],
        "profiles": chain["profiles"],
    }
    path.write_text(json.dumps(to_store, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **chain, "path": str(path)}


def profile_for_context(
    *,
    event_type: str = "",
    daypart: str = "",
    ai_dj: bool = False,
    near_vt: bool = False,
    neighbor_event_type: str = "",
    playout_mode: str = "AUTO",
    data_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Pick a ramp profile for the current cart / overnight AI path.

    In AUTO overnight, MUSIC adjacent to a VOICE_TRACK uses the AI DJ ramp so
    fades into/out of VT breaks stay smooth without touching song selection.
    """
    ramps = load_ramps(data_dir)
    et = (event_type or "").upper()
    dp = (daypart or "").lower()
    mode = (playout_mode or "AUTO").upper()
    neighbor = (neighbor_event_type or "").upper()
    adjacent_vt = near_vt or neighbor == "VOICE_TRACK" or et == "VOICE_TRACK"

    if ai_dj or dp == "overnight":
        # Overnight / AI DJ path — VT and music around VT share the overnight curve
        if adjacent_vt or et in ("MUSIC", "VOICE_TRACK", ""):
            return dict(ramps.get("ai_dj") or ramps["profiles"]["overnight"])
        return dict(ramps.get("ai_dj") or ramps["profiles"]["overnight"])

    if mode == "AUTO" and adjacent_vt and et in ("MUSIC", "VOICE_TRACK", ""):
        # Daytime AUTO: soften around VT breaks
        return dict(ramps["profiles"].get("soft") or ramps["profiles"]["default"])

    if et in ("ID", "SWEEPER", "PROMO"):
        return dict(ramps["profiles"].get("imaging") or ramps["profiles"]["default"])
    if et == "VOICE_TRACK":
        return dict(ramps["profiles"].get("soft") or ramps["profiles"]["default"])
    return dict(ramps.get("active") or ramps["profiles"]["default"])

"""Native on-air broadcast processing chain (desk control surface).

Public broadcast practice topology — NOT an Orban Optimod schematic clone,
NOT AU/AAX hosting (that stays a later Mac production-bus option only):

    AGC → EQ → Multiband → Exciter → Peak Limiter

FM and Digital templates ship as announcer-recognisable defaults. The MockEngine
stores/loads these params for the desk; a future Liquidsoap/Mac engine applies them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR

PROCESSING_FILE = "processing.json"

# Stage order is fixed — broadcast chain reading order on the desk
STAGE_ORDER = ("agc", "eq", "multiband", "exciter", "limiter")

STAGE_LABELS = {
    "agc": "AGC / Leveler",
    "eq": "EQ",
    "multiband": "Multiband",
    "exciter": "Exciter / Presence",
    "limiter": "Peak Limiter",
}

# Sensible on-air defaults an announcer would recognise (dense, not streamer-toy)
_BASE_CHAIN = {
    "enabled": True,
    "insert_policy": "native_when_empty",  # Program path: empty AU insert → native chain
    "template": "FM",
    # desk = mild On-Air approx; transmission = more aggressive FM vs Digital flavour
    "transmission_mode": False,
    "notes": (
        "Native MQ processing — AGC→EQ→Multiband→Exciter→Limiter. "
        "FM = classic dense on-air; Digital = cleaner streaming/DAB path. "
        "Not an Optimod clone; AU plugins are production-bus only (later). transmission_mode=true pushes FM denser / Digital cleaner for audible TX preview."
    ),
    "stages": {
        "agc": {
            "enabled": True,
            "target_db": -16.0,
            "drive_db": 6.0,
            "attack_ms": 50.0,
            "release_ms": 1200.0,
            "gate_db": -42.0,
        },
        "eq": {
            "enabled": True,
            "low_shelf_hz": 120.0,
            "low_shelf_db": 1.5,
            "presence_hz": 3200.0,
            "presence_db": 1.0,
            "air_hz": 10000.0,
            "air_db": 0.5,
            "high_cut_hz": 15000.0,
        },
        "multiband": {
            "enabled": True,
            "bands": 4,
            "crossovers_hz": [200.0, 800.0, 3200.0],
            "drive_db": [3.0, 4.0, 3.5, 2.5],
            "release_ms": [400.0, 250.0, 180.0, 120.0],
            "couple": True,
        },
        "exciter": {
            "enabled": True,
            "amount": 0.25,
            "harmonics": 0.35,
            "mix": 0.20,
        },
        "limiter": {
            "enabled": True,
            "ceiling_dbfs": -1.0,
            "release_ms": 40.0,
            "lookahead_ms": 3.0,
            "isr": True,  # inter-sample peak awareness flag for digital path
        },
    },
    # Output path flavour (affects limiter / HF defaults when template applied)
    "output": {
        "path": "FM",  # FM | DIGITAL
        "preemphasis": True,  # FM 50/75µs awareness (flag only in mock)
        "preemphasis_us": 50,  # AU/EU default 50; US often 75 — station settable
        "stereo_enhance": 0.15,
    },
}


def fm_template() -> dict[str, Any]:
    """Dense FM on-air — classic competitive loudness, 15 kHz-aware."""
    t = copy.deepcopy(_BASE_CHAIN)
    t["template"] = "FM"
    t["output"]["path"] = "FM"
    t["output"]["preemphasis"] = True
    t["output"]["preemphasis_us"] = 50
    t["stages"]["agc"]["target_db"] = -15.0
    t["stages"]["agc"]["drive_db"] = 7.0
    t["stages"]["agc"]["release_ms"] = 900.0
    t["stages"]["eq"]["high_cut_hz"] = 15000.0
    t["stages"]["eq"]["air_db"] = 0.75
    t["stages"]["eq"]["presence_db"] = 1.5
    t["stages"]["multiband"]["drive_db"] = [3.5, 4.5, 4.0, 3.0]
    t["stages"]["exciter"]["amount"] = 0.30
    t["stages"]["exciter"]["mix"] = 0.22
    t["stages"]["limiter"]["ceiling_dbfs"] = -1.0
    t["stages"]["limiter"]["release_ms"] = 35.0
    t["stages"]["limiter"]["isr"] = False
    return t


def digital_template() -> dict[str, Any]:
    """Digital / stream / DAB — cleaner ceiling, ISR-aware, less HF hype."""
    t = copy.deepcopy(_BASE_CHAIN)
    t["template"] = "DIGITAL"
    t["output"]["path"] = "DIGITAL"
    t["output"]["preemphasis"] = False
    t["output"]["stereo_enhance"] = 0.08
    t["stages"]["agc"]["target_db"] = -16.0
    t["stages"]["agc"]["drive_db"] = 5.0
    t["stages"]["agc"]["release_ms"] = 1400.0
    t["stages"]["eq"]["high_cut_hz"] = 18000.0
    t["stages"]["eq"]["air_db"] = 0.25
    t["stages"]["eq"]["presence_db"] = 0.75
    t["stages"]["multiband"]["drive_db"] = [2.5, 3.0, 2.8, 2.0]
    t["stages"]["exciter"]["amount"] = 0.15
    t["stages"]["exciter"]["mix"] = 0.12
    t["stages"]["exciter"]["enabled"] = True
    t["stages"]["limiter"]["ceiling_dbfs"] = -1.0
    t["stages"]["limiter"]["release_ms"] = 50.0
    t["stages"]["limiter"]["lookahead_ms"] = 5.0
    t["stages"]["limiter"]["isr"] = True
    return t


TEMPLATES = {
    "FM": fm_template,
    "DIGITAL": digital_template,
}


def default_processing() -> dict[str, Any]:
    return fm_template()


def _path(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    return root / PROCESSING_FILE


def _merge_stage(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def normalize_processing(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce user/API payload onto a full chain with template defaults."""
    base = default_processing()
    if not payload or not isinstance(payload, dict):
        return base

    tmpl_name = str(payload.get("template") or base["template"]).upper()
    if tmpl_name not in TEMPLATES:
        tmpl_name = "FM"
    chain = TEMPLATES[tmpl_name]()

    if "enabled" in payload:
        chain["enabled"] = bool(payload["enabled"])
    if "transmission_mode" in payload:
        chain["transmission_mode"] = bool(payload["transmission_mode"])
    if payload.get("notes"):
        chain["notes"] = str(payload["notes"])

    if isinstance(payload.get("output"), dict):
        chain["output"] = {**chain["output"], **payload["output"]}
        chain["output"]["path"] = str(chain["output"].get("path") or tmpl_name).upper()

    stages_in = payload.get("stages") if isinstance(payload.get("stages"), dict) else {}
    for name in STAGE_ORDER:
        if name in stages_in and isinstance(stages_in[name], dict):
            chain["stages"][name] = _merge_stage(chain["stages"][name], stages_in[name])

    chain["template"] = tmpl_name
    chain["topology"] = " → ".join(STAGE_LABELS[s] for s in STAGE_ORDER)
    chain["stage_order"] = list(STAGE_ORDER)
    return chain


def load_processing(data_dir: Optional[Path] = None) -> dict[str, Any]:
    path = _path(data_dir)
    if not path.exists():
        chain = default_processing()
        chain["topology"] = " → ".join(STAGE_LABELS[s] for s in STAGE_ORDER)
        chain["stage_order"] = list(STAGE_ORDER)
        chain["source"] = "defaults"
        return chain
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        chain = normalize_processing(data if isinstance(data, dict) else {})
        chain["source"] = str(path)
        return chain
    except (OSError, json.JSONDecodeError):
        chain = default_processing()
        chain["topology"] = " → ".join(STAGE_LABELS[s] for s in STAGE_ORDER)
        chain["stage_order"] = list(STAGE_ORDER)
        chain["source"] = "defaults"
        return chain


def save_processing(payload: dict[str, Any], data_dir: Optional[Path] = None) -> dict[str, Any]:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Allow template switch shortcut
    if payload.get("apply_template"):
        name = str(payload.get("apply_template") or payload.get("template") or "FM").upper()
        if name in TEMPLATES:
            payload = {**TEMPLATES[name](), **{k: v for k, v in payload.items() if k not in ("apply_template", "stages")}}
            payload["template"] = name
    chain = normalize_processing(payload)
    to_store = {
        "enabled": chain["enabled"],
        "template": chain["template"],
        "transmission_mode": bool(chain.get("transmission_mode")),
        "notes": chain["notes"],
        "output": chain["output"],
        "stages": chain["stages"],
    }
    path.write_text(json.dumps(to_store, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **chain, "path": str(path)}


def processing_summary(chain: Optional[dict[str, Any]] = None) -> str:
    c = chain or default_processing()
    if not c.get("enabled"):
        return "PROC BYPASS"
    on = [STAGE_LABELS[s][:3].upper() for s in STAGE_ORDER if c["stages"].get(s, {}).get("enabled")]
    tx = "+TX" if c.get("transmission_mode") else ""
    return f"{c.get('template', 'FM')}{tx} [{'·'.join(on) or 'off'}]"

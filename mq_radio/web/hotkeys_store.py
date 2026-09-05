"""Editable On-Air hotkey bank — persisted to data/hotkeys.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR

HOTKEYS_FILE = "hotkeys.json"
SLOTS_PER_PAGE = 16  # 4x4
DEFAULT_PAGES = 2  # 32 slots

DEFAULT_HOTKEYS: list[dict[str, Any]] = [
    {"slot": 0, "key": "F1", "label": "Top of Hour ID", "type": "ID", "target": None, "macro": None},
    {"slot": 1, "key": "F2", "label": "Legal ID", "type": "ID", "target": None, "macro": None},
    {"slot": 2, "key": "F3", "label": "Sweeper — More Music", "type": "SWEEPER", "target": None, "macro": None},
    {"slot": 3, "key": "F4", "label": "Sweeper — Brand", "type": "SWEEPER", "target": None, "macro": None},
    {"slot": 4, "key": "F5", "label": "Weekend Promo", "type": "PROMO", "target": None, "macro": None},
    {"slot": 5, "key": "F6", "label": "Contest Promo", "type": "PROMO", "target": None, "macro": None},
    {"slot": 6, "key": "F7", "label": "VT Bed", "type": "VT", "target": None, "macro": None},
    {"slot": 7, "key": "F8", "label": "Emergency Fill", "type": "MUSIC", "target": None, "macro": None},
]


def _path(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir else DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root / HOTKEYS_FILE


def _empty_slot(slot: int) -> dict[str, Any]:
    page = slot // SLOTS_PER_PAGE
    idx = slot % SLOTS_PER_PAGE
    key = f"F{idx + 1}" if page == 0 and idx < 12 else ""
    return {
        "slot": slot,
        "key": key,
        "label": "",
        "type": "",
        "target": None,
        "macro": None,
        "empty": True,
    }


def _normalize(items: list[dict]) -> list[dict]:
    by_slot: dict[int, dict] = {}
    for it in items:
        try:
            s = int(it.get("slot", -1))
        except (TypeError, ValueError):
            continue
        if s < 0:
            continue
        label = (it.get("label") or "").strip()
        typ = (it.get("type") or "").strip().upper()
        if typ == "VOICE_TRACK":
            typ = "VT"
        empty = not label and not typ and not it.get("target") and not it.get("macro")
        row = {
            "slot": s,
            "key": it.get("key") or "",
            "label": label,
            "type": typ,
            "target": it.get("target"),
            "macro": it.get("macro"),
            "empty": empty,
        }
        by_slot[s] = row
    total = max(SLOTS_PER_PAGE * DEFAULT_PAGES, (max(by_slot.keys()) + 1) if by_slot else 0)
    pages = max(DEFAULT_PAGES, (total + SLOTS_PER_PAGE - 1) // SLOTS_PER_PAGE)
    total = pages * SLOTS_PER_PAGE
    out = []
    for s in range(total):
        if s in by_slot:
            out.append(by_slot[s])
        else:
            out.append(_empty_slot(s))
    return out


def load_hotkeys(data_dir: Optional[Path] = None) -> dict:
    path = _path(data_dir)
    if not path.exists():
        slots = [_empty_slot(s) for s in range(SLOTS_PER_PAGE * DEFAULT_PAGES)]
        for d in DEFAULT_HOTKEYS:
            slots[d["slot"]] = {**d, "empty": False}
        return {
            "version": 1,
            "slots_per_page": SLOTS_PER_PAGE,
            "pages": DEFAULT_PAGES,
            "hotkeys": slots,
            "source": "default",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    items = data.get("hotkeys") if isinstance(data, dict) else None
    if not isinstance(items, list):
        items = []
    slots = _normalize(items)
    pages = max(DEFAULT_PAGES, len(slots) // SLOTS_PER_PAGE)
    return {
        "version": 1,
        "slots_per_page": SLOTS_PER_PAGE,
        "pages": pages,
        "hotkeys": slots,
        "source": "file",
        "path": str(path),
    }


def save_hotkeys(hotkeys: list[dict], data_dir: Optional[Path] = None) -> dict:
    path = _path(data_dir)
    slots = _normalize(list(hotkeys or []))
    payload = {
        "version": 1,
        "slots_per_page": SLOTS_PER_PAGE,
        "pages": len(slots) // SLOTS_PER_PAGE,
        "hotkeys": slots,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {**payload, "ok": True, "path": str(path), "source": "file"}

"""Editable On-Air hotkey bank — persisted to data/hotkeys.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR

HOTKEYS_FILE = "hotkeys.json"
SLOTS_PER_PAGE = 16  # 4x4
DEFAULT_PAGES = 2  # 32 slots
MAX_PAGES = 8
MIN_PAGES = DEFAULT_PAGES

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
        "color": "",
        "target": None,
        "path": None,
        "macro": None,
        "inject_mode": "over_program",  # over_program | queue_next
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
        path_ref = it.get("path") or it.get("file_path") or None
        if path_ref is not None:
            path_ref = str(path_ref).strip() or None
        inject = str(it.get("inject_mode") or it.get("inject") or "over_program").strip().lower().replace("-", "_")
        if inject in ("over", "oneshot", "fire"):
            inject = "over_program"
        if inject in ("queue", "next", "insert"):
            inject = "queue_next"
        if inject not in ("over_program", "queue_next"):
            inject = "over_program"
        color = str(it.get("color") or "").strip()
        empty = not label and not typ and not it.get("target") and not path_ref and not it.get("macro")
        row = {
            "slot": s,
            "key": it.get("key") or "",
            "label": label,
            "type": typ,
            "color": color,
            "target": it.get("target"),
            "path": path_ref,  # absolute path for one-shot — plays in place, no library copy
            "macro": it.get("macro"),
            "inject_mode": inject,
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
        # Run defaults through _normalize so path/inject_mode match persisted shape.
        slots = _normalize(list(DEFAULT_HOTKEYS))
        return {
            "version": 1,
            "slots_per_page": SLOTS_PER_PAGE,
            "pages": max(DEFAULT_PAGES, len(slots) // SLOTS_PER_PAGE),
            "hotkeys": slots,
            "ui_page": 0,
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
    ui_page = 0
    if isinstance(data, dict) and data.get("ui_page") is not None:
        try:
            ui_page = max(0, min(pages - 1, int(data.get("ui_page"))))
        except (TypeError, ValueError):
            ui_page = 0
    return {
        "version": 1,
        "slots_per_page": SLOTS_PER_PAGE,
        "pages": pages,
        "hotkeys": slots,
        "ui_page": ui_page,
        "source": "file",
        "path": str(path),
    }


def save_hotkeys(
    hotkeys: list[dict],
    data_dir: Optional[Path] = None,
    *,
    ui_page: Optional[int] = None,
) -> dict:
    path = _path(data_dir)
    slots = _normalize(list(hotkeys or []))
    pages = len(slots) // SLOTS_PER_PAGE
    payload = {
        "version": 1,
        "slots_per_page": SLOTS_PER_PAGE,
        "pages": pages,
        "hotkeys": slots,
    }
    if ui_page is not None:
        try:
            payload["ui_page"] = max(0, min(max(pages - 1, 0), int(ui_page)))
        except (TypeError, ValueError):
            payload["ui_page"] = 0
    elif path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev, dict) and prev.get("ui_page") is not None:
                payload["ui_page"] = max(0, min(max(pages - 1, 0), int(prev["ui_page"])))
        except Exception:
            pass
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {**payload, "ok": True, "path": str(path), "source": "file"}


def _rekey_page0(slots: list[dict]) -> list[dict]:
    """Ensure page-0 slots keep F1–F12 key labels after reorder."""
    for i, row in enumerate(slots):
        row["slot"] = i
        if i < SLOTS_PER_PAGE:
            row["key"] = f"F{i + 1}" if i < 12 else ""
        else:
            row["key"] = row.get("key") or ""
    return slots


def reorder_hotkeys(
    from_slot: int,
    to_slot: int,
    data_dir: Optional[Path] = None,
) -> dict:
    """Swap two hotkey bank slots and persist (drag-reorder / Up/Down)."""
    try:
        a = int(from_slot)
        b = int(to_slot)
    except (TypeError, ValueError):
        return {"ok": False, "error": "from_slot and to_slot must be integers"}
    if a == b:
        loaded = load_hotkeys(data_dir)
        return {
            "ok": True,
            "unchanged": True,
            "hotkeys": loaded["hotkeys"],
            "pages": loaded["pages"],
            "slots_per_page": loaded["slots_per_page"],
        }
    loaded = load_hotkeys(data_dir)
    slots = list(loaded["hotkeys"])
    n = len(slots)
    if a < 0 or b < 0 or a >= n or b >= n:
        return {"ok": False, "error": f"slot out of range (0..{n - 1})"}
    ha = dict(slots[a])
    hb = dict(slots[b])
    ha["slot"] = b
    hb["slot"] = a
    slots[b] = ha
    slots[a] = hb
    slots = _rekey_page0(slots)
    saved = save_hotkeys(slots, data_dir)
    return {
        **saved,
        "ok": True,
        "from_slot": a,
        "to_slot": b,
        "message": f"Hotkey slot {a + 1} ↔ {b + 1} reordered",
    }


def page_slice(hotkeys: list[dict], page: int, slots_per_page: int = SLOTS_PER_PAGE) -> list[dict]:
    """Return one cartwall page of slots (0-indexed page)."""
    spp = max(1, int(slots_per_page or SLOTS_PER_PAGE))
    p = max(0, int(page or 0))
    start = p * spp
    return list(hotkeys[start : start + spp])


def set_pages(pages: int, data_dir: Optional[Path] = None, *, ui_page: Optional[int] = None) -> dict:
    """Expand or shrink cartwall pages (2–8). Shrinking clears trailing empty slots only when empty."""
    try:
        n = int(pages)
    except (TypeError, ValueError):
        return {"ok": False, "error": "pages must be an integer"}
    if n < MIN_PAGES or n > MAX_PAGES:
        return {"ok": False, "error": f"pages must be {MIN_PAGES}..{MAX_PAGES}"}
    loaded = load_hotkeys(data_dir)
    slots = list(loaded["hotkeys"])
    target = n * SLOTS_PER_PAGE
    if len(slots) < target:
        for s in range(len(slots), target):
            slots.append(_empty_slot(s))
    elif len(slots) > target:
        # Refuse to drop non-empty slots beyond the new last page
        for row in slots[target:]:
            if not row.get("empty"):
                return {
                    "ok": False,
                    "error": (
                        f"cannot shrink to {n} pages — slot {int(row['slot']) + 1} "
                        f"still assigned ({row.get('label') or row.get('type') or 'cart'})"
                    ),
                }
        slots = slots[:target]
    slots = _rekey_page0(slots)
    path = _path(data_dir)
    payload = {
        "version": 1,
        "slots_per_page": SLOTS_PER_PAGE,
        "pages": n,
        "hotkeys": slots,
    }
    if ui_page is not None:
        try:
            payload["ui_page"] = max(0, min(n - 1, int(ui_page)))
        except (TypeError, ValueError):
            payload["ui_page"] = 0
    elif isinstance(loaded.get("ui_page"), int):
        payload["ui_page"] = max(0, min(n - 1, int(loaded["ui_page"])))
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        **payload,
        "ok": True,
        "path": str(path),
        "source": "file",
        "message": f"Hotkey bank now {n} pages ({target} slots)",
    }


def clear_slot(slot: int, data_dir: Optional[Path] = None) -> dict:
    """Clear one hotkey bank slot and persist."""
    try:
        s = int(slot)
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot must be an integer"}
    loaded = load_hotkeys(data_dir)
    slots = list(loaded["hotkeys"])
    if s < 0 or s >= len(slots):
        return {"ok": False, "error": f"slot out of range (0..{len(slots) - 1})"}
    slots[s] = _empty_slot(s)
    slots = _rekey_page0(slots)
    ui = loaded.get("ui_page") if isinstance(loaded.get("ui_page"), int) else None
    saved = save_hotkeys(slots, data_dir, ui_page=ui)
    return {
        **saved,
        "ok": True,
        "cleared_slot": s,
        "message": f"Hotkey slot {s + 1} cleared",
    }


def move_hotkey(
    from_slot: int,
    to_slot: int,
    data_dir: Optional[Path] = None,
) -> dict:
    """Insert-move a slot (shift others) — deeper reorder than swap."""
    try:
        a = int(from_slot)
        b = int(to_slot)
    except (TypeError, ValueError):
        return {"ok": False, "error": "from_slot and to_slot must be integers"}
    if a == b:
        loaded = load_hotkeys(data_dir)
        return {
            "ok": True,
            "unchanged": True,
            "hotkeys": loaded["hotkeys"],
            "pages": loaded["pages"],
            "slots_per_page": loaded["slots_per_page"],
        }
    loaded = load_hotkeys(data_dir)
    slots = list(loaded["hotkeys"])
    n = len(slots)
    if a < 0 or b < 0 or a >= n or b >= n:
        return {"ok": False, "error": f"slot out of range (0..{n - 1})"}
    item = dict(slots.pop(a))
    slots.insert(b, item)
    slots = _rekey_page0(slots)
    saved = save_hotkeys(slots, data_dir)
    return {
        **saved,
        "ok": True,
        "from_slot": a,
        "to_slot": b,
        "moved": True,
        "message": f"Hotkey slot {a + 1} moved to {b + 1}",
    }

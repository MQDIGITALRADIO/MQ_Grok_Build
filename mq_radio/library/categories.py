"""Category / library manager — SQLite categories + track browse."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from mq_radio.db.connection import get_connection

# How the scheduler / clocks typically use each seeded code (operator-facing).
_CODE_RULE_HINTS: dict[str, str] = {
    "A": "Music · Power/Current scored; high rotation in GENERAL clocks",
    "B": "Music · Recurrent scored; mid rotation dayparts",
    "C": "Music · Gold/library scored; softer / overnight lean",
    "ID": "Imaging · legal / top-of-hour IDs (HIT timing common)",
    "SW": "Imaging · sweepers between music",
    "PR": "Imaging · promos / liners",
    "BED": "Production · beds / underlays",
    "VT": "Voice · VT stubs for AI / Vocloner path",
    "FL": "Filler · short carts for ETM/HIT under-fills (prefer over stub)",
    "FILLER": "Filler · short carts for ETM/HIT under-fills",
}


def _rules_summary(row: dict, track_count: int) -> str:
    """Operator-facing rules blurb: description + derived scheduler hint."""
    desc = (row.get("description") or "").strip()
    code = (row.get("code") or "").strip().upper()
    hint = _CODE_RULE_HINTS.get(code, "")
    kind = "Music category" if int(row.get("is_music") or 0) else "Non-music / imaging"
    pri = int(row.get("priority") or 100)
    bits = []
    if desc:
        bits.append(desc)
    elif hint:
        bits.append(hint)
    else:
        bits.append(kind)
    if hint and desc and hint not in desc:
        bits.append(hint)
    bits.append(f"priority {pri}")
    bits.append(f"{track_count} cart{'s' if track_count != 1 else ''}")
    return " · ".join(bits)


def list_categories(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """List all categories with track counts and rules summaries."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT c.id, c.code, c.name, c.description, c.priority, c.is_music, c.created_at,
                  COUNT(t.id) AS track_count
           FROM categories c
           LEFT JOIN tracks t ON t.category_id = c.id AND t.active = 1
           GROUP BY c.id
           ORDER BY c.priority ASC, c.code ASC"""
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["is_music"] = bool(d.get("is_music"))
        d["track_count"] = int(d.get("track_count") or 0)
        d["rules_summary"] = _rules_summary(d, d["track_count"])
        out.append(d)
    return out


def get_category(code: str, db_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    code = (code or "").strip().upper()
    if not code:
        return None
    for c in list_categories(db_path):
        if c["code"].upper() == code:
            return c
    return None


def _valid_code(code: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]{1,12}", code or ""))


def add_category(
    code: str,
    name: str,
    *,
    description: Optional[str] = None,
    priority: int = 50,
    is_music: bool = False,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Insert a new category. Returns {ok, category} or {ok:False, error}."""
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not _valid_code(code):
        return {"ok": False, "error": "code must be 1–12 alphanumeric/underscore"}
    if not name:
        return {"ok": False, "error": "name required"}
    conn = get_connection(db_path)
    try:
        exists = conn.execute(
            "SELECT id FROM categories WHERE code = ?", (code,)
        ).fetchone()
        if exists:
            return {"ok": False, "error": f"category {code} already exists"}
        conn.execute(
            """INSERT INTO categories (code, name, description, priority, is_music)
               VALUES (?,?,?,?,?)""",
            (code, name, (description or "").strip() or None, int(priority), 1 if is_music else 0),
        )
        conn.commit()
    finally:
        conn.close()
    cat = get_category(code, db_path=db_path)
    return {"ok": True, "category": cat}


def update_category(
    code: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    is_music: Optional[bool] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Update name / rules summary (description) / priority / is_music."""
    code = (code or "").strip().upper()
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM categories WHERE code = ?", (code,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"category {code} not found"}
        new_name = name.strip() if name is not None else row["name"]
        if name is not None and not new_name:
            return {"ok": False, "error": "name required"}
        new_desc = (
            description.strip() if description is not None else row["description"]
        )
        new_pri = int(priority) if priority is not None else int(row["priority"])
        if is_music is not None:
            new_music = 1 if is_music else 0
        else:
            new_music = int(row["is_music"] or 0)
        conn.execute(
            """UPDATE categories
               SET name=?, description=?, priority=?, is_music=?
               WHERE code=?""",
            (new_name, new_desc or None, new_pri, new_music, code),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "category": get_category(code, db_path=db_path)}


def rename_category(
    old_code: str,
    new_code: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Rename category code; cascade to clock_slots + log_events category_code."""
    old_code = (old_code or "").strip().upper()
    new_code = (new_code or "").strip().upper()
    if not _valid_code(new_code):
        return {"ok": False, "error": "new code must be 1–12 alphanumeric/underscore"}
    if old_code == new_code:
        return {"ok": True, "category": get_category(old_code, db_path=db_path)}
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM categories WHERE code = ?", (old_code,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"category {old_code} not found"}
        clash = conn.execute(
            "SELECT id FROM categories WHERE code = ?", (new_code,)
        ).fetchone()
        if clash:
            return {"ok": False, "error": f"category {new_code} already exists"}
        conn.execute(
            "UPDATE categories SET code = ? WHERE code = ?", (new_code, old_code)
        )
        conn.execute(
            "UPDATE clock_slots SET category_code = ? WHERE category_code = ?",
            (new_code, old_code),
        )
        conn.execute(
            "UPDATE log_events SET category_code = ? WHERE category_code = ?",
            (new_code, old_code),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "category": get_category(new_code, db_path=db_path), "renamed_from": old_code}


def list_tracks_for_category(
    code: Optional[str] = None,
    *,
    q: Optional[str] = None,
    db_path: Optional[Path] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Browse library tracks, optionally filtered by category code."""
    conn = get_connection(db_path)
    params: list[Any] = []
    sql = """
        SELECT t.id, t.artist, t.title, t.duration_ms, t.event_type,
               t.rotation_category, t.active,
               COALESCE(t.intro_ms, 0) AS intro_ms,
               COALESCE(t.outro_ms, 0) AS outro_ms,
               COALESCE(c.code, '') AS category,
               COALESCE(c.name, '') AS category_name
        FROM tracks t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.active = 1
    """
    if code and code.strip():
        sql += " AND UPPER(c.code) = ?"
        params.append(code.strip().upper())
    if q and q.strip():
        like = f"%{q.strip()}%"
        sql += """ AND (t.title LIKE ? OR t.artist LIKE ?
                        OR t.event_type LIKE ? OR COALESCE(c.code,'') LIKE ?)"""
        params.extend([like, like, like, like])
    sql += " ORDER BY t.artist, t.title LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        {
            "id": int(r["id"]),
            "artist": r["artist"] or "",
            "title": r["title"] or "",
            "category": r["category"] or "",
            "category_name": r["category_name"] or "",
            "duration_ms": int(r["duration_ms"] or 0),
            "event_type": r["event_type"] or "MUSIC",
            "rotation_category": r["rotation_category"] or "",
            "intro_ms": int(r["intro_ms"] or 0),
            "outro_ms": int(r["outro_ms"] or 0),
        }
        for r in rows
    ]


def categories_bundle(db_path: Optional[Path] = None) -> dict[str, Any]:
    """API payload for Category / Library Manager UI."""
    cats = list_categories(db_path)
    return {
        "categories": cats,
        "total_tracks": sum(c["track_count"] for c in cats),
    }

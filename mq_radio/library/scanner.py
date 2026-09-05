"""Library scanner — indexes audio files into tracks table."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Optional

import mq_radio.config as _cfg
from mq_radio.db.connection import get_connection


def _duration_ms_from_wav(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 44100
            return int(frames / rate * 1000)
    except Exception:
        return 0


def _load_sidecar_meta(path: Path) -> dict:
    meta_path = path.with_suffix(path.suffix + ".json")
    if not meta_path.exists():
        meta_path = path.with_suffix(".json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    # fallback from filename Artist - Title.wav
    stem = path.stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return {"artist": artist.strip(), "title": title.strip()}
    return {"artist": "Unknown", "title": stem}


def scan_directory(
    directory: Optional[Path] = None,
    db_path: Optional[Path] = None,
    category_code: str = "A",
) -> int:
    """Scan audio files and upsert tracks. Returns count inserted/updated."""
    root = Path(directory) if directory else _cfg.FIXTURES_DIR
    if not root.exists():
        return 0

    conn = get_connection(db_path)
    cat = conn.execute(
        "SELECT id FROM categories WHERE code = ?", (category_code,)
    ).fetchone()
    category_id = cat["id"] if cat else None

    count = 0
    patterns = ("*.wav", "*.mp3", "*.flac", "*.ogg")
    files: list[Path] = []
    for pat in patterns:
        files.extend(root.rglob(pat))

    for path in sorted(files):
        meta = _load_sidecar_meta(path)
        duration_ms = meta.get("duration_ms")
        if duration_ms is None and path.suffix.lower() == ".wav":
            duration_ms = _duration_ms_from_wav(path)
        duration_ms = int(duration_ms or 0)

        existing = conn.execute(
            "SELECT id FROM tracks WHERE file_path = ?", (str(path.resolve()),)
        ).fetchone()

        fields = {
            "title": meta.get("title", path.stem),
            "artist": meta.get("artist", "Unknown"),
            "album": meta.get("album"),
            "year": meta.get("year"),
            "genre": meta.get("genre"),
            "bpm": meta.get("bpm"),
            "duration_ms": duration_ms,
            "intro_ms": int(meta.get("intro_ms", 0)),
            "outro_ms": int(meta.get("outro_ms", 0)),
            "energy": meta.get("energy"),
            "mood": meta.get("mood"),
            "gender": meta.get("gender"),
            "australian": 1 if meta.get("australian") else 0,
            "era": meta.get("era"),
            "category_id": category_id,
            "rotation_category": meta.get("rotation_category", meta.get("rotation", "Current")),
            "start_date": meta.get("start_date"),
            "end_date": meta.get("end_date"),
            "explicit": 1 if meta.get("explicit") else 0,
            "file_path": str(path.resolve()),
            "replaygain": meta.get("replaygain"),
            "isrc": meta.get("isrc"),
            "apra_work_id": meta.get("apra_work_id"),
            "ppca_id": meta.get("ppca_id"),
            "event_type": meta.get("event_type", "MUSIC"),
        }

        if existing:
            conn.execute(
                """UPDATE tracks SET
                    title=?, artist=?, album=?, year=?, genre=?, bpm=?,
                    duration_ms=?, intro_ms=?, outro_ms=?, energy=?, mood=?,
                    gender=?, australian=?, era=?, category_id=?, rotation_category=?,
                    start_date=?, end_date=?, explicit=?, replaygain=?, isrc=?,
                    apra_work_id=?, ppca_id=?, event_type=?,
                    updated_at=datetime('now')
                WHERE id=?""",
                (
                    fields["title"], fields["artist"], fields["album"], fields["year"],
                    fields["genre"], fields["bpm"], fields["duration_ms"], fields["intro_ms"],
                    fields["outro_ms"], fields["energy"], fields["mood"], fields["gender"],
                    fields["australian"], fields["era"], fields["category_id"],
                    fields["rotation_category"], fields["start_date"], fields["end_date"],
                    fields["explicit"], fields["replaygain"], fields["isrc"],
                    fields["apra_work_id"], fields["ppca_id"], fields["event_type"],
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO tracks (
                    title, artist, album, year, genre, bpm, duration_ms, intro_ms, outro_ms,
                    energy, mood, gender, australian, era, category_id, rotation_category,
                    start_date, end_date, explicit, file_path, replaygain, isrc,
                    apra_work_id, ppca_id, event_type
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    fields["title"], fields["artist"], fields["album"], fields["year"],
                    fields["genre"], fields["bpm"], fields["duration_ms"], fields["intro_ms"],
                    fields["outro_ms"], fields["energy"], fields["mood"], fields["gender"],
                    fields["australian"], fields["era"], fields["category_id"],
                    fields["rotation_category"], fields["start_date"], fields["end_date"],
                    fields["explicit"], fields["file_path"], fields["replaygain"], fields["isrc"],
                    fields["apra_work_id"], fields["ppca_id"], fields["event_type"],
                ),
            )
        count += 1

    conn.commit()
    conn.close()
    return count

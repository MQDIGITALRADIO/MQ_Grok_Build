"""Serve library / fixture / hotkey audio for the On-Air Web Audio path."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from mq_radio.config import DATA_DIR, FIXTURES_DIR, ROOT
from mq_radio.library.ingest import library_audio_dir, segments_dir, vt_inbox_dir


AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".webm"}


def _allowed_roots(data_dir: Optional[Path] = None) -> list[Path]:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    candidates = [
        library_audio_dir(root),
        segments_dir(root),
        root / "vt",
        root / "library",
        root / "segments",
        root / "demo_audio",
        vt_inbox_dir(root),
        Path(FIXTURES_DIR),
        ROOT / "fixtures" / "demo_audio",
        root,
    ]
    out: list[Path] = []
    seen = set()
    for c in candidates:
        try:
            r = c.resolve()
        except OSError:
            continue
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def resolve_media_path(
    raw: str | Path,
    data_dir: Optional[Path] = None,
    *,
    allow_absolute: bool = True,
) -> Optional[Path]:
    """Resolve a playable audio path.

    Prefers files under library/fixtures/data roots. For local desk one-shots,
    absolute paths to existing audio files are also allowed (not a public CDN).
    """
    if not raw:
        return None
    try:
        p = Path(str(raw)).expanduser().resolve()
    except OSError:
        return None
    if not p.is_file():
        return None
    if p.suffix.lower() not in AUDIO_EXTS:
        return None
    for root in _allowed_roots(data_dir):
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    if allow_absolute:
        return p
    return None


def playable_url(path: str | Path | None, track_id: int | None = None) -> Optional[str]:
    if track_id is not None:
        return f"/api/media/track/{int(track_id)}"
    if path:
        return f"/api/media?path={quote(str(path), safe='')}"
    return None


def content_type_for(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    if ctype:
        return ctype
    ext = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")

"""Ingest audio/video into the library as carts; segment long files; VT inbox import."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import mq_radio.config as _cfg
from mq_radio.db.connection import get_connection

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
INGEST_EXTS = AUDIO_EXTS | VIDEO_EXTS


def library_root_config_path(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    return root / "library-root.json"


def save_library_root_path(path: str | Path, data_dir: Optional[Path] = None) -> dict:
    """Persist MQ Digital library root (ingest destination)."""
    import json

    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    cfg = library_root_config_path(data_dir)
    payload = {"path": str(p)}
    cfg.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(p), "config": str(cfg)}


def library_audio_dir(data_dir: Optional[Path] = None) -> Path:
    """MQ Digital library audio root.

    Priority:
      1. MQ_RADIO_LIBRARY_ROOT env
      2. data/library-root.json path key
      3. data/library (default)
    """
    env = os.environ.get("MQ_RADIO_LIBRARY_ROOT")
    if env:
        p = Path(env).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    cfg_path = library_root_config_path(data_dir)
    if cfg_path.exists():
        try:
            import json

            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw = (data or {}).get("path") or ""
            if raw:
                p = Path(str(raw)).expanduser()
                p.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:
            pass

    d = root / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def segments_dir(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    d = root / "segments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def vt_inbox_dir(data_dir: Optional[Path] = None) -> Path:
    """Configurable VT / Downloads inbox.

    Priority:
      1. MQ_RADIO_VT_INBOX env
      2. data/vt-inbox.json path key (if present)
      3. ~/Downloads on macOS / Darwin
      4. data/vt-inbox (Linux/web demo default)
    """
    env = os.environ.get("MQ_RADIO_VT_INBOX")
    if env:
        p = Path(env).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    cfg_path = root / "vt-inbox.json"
    if cfg_path.exists():
        try:
            import json

            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw = (data or {}).get("path") or ""
            if raw:
                p = Path(str(raw)).expanduser()
                p.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:
            pass

    if os.environ.get("MQ_RADIO_USE_DOWNLOADS", "").lower() in ("1", "true", "yes"):
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            return downloads

    # Auto-detect macOS Downloads when home looks like a Mac user
    downloads = Path.home() / "Downloads"
    if downloads.is_dir() and (
        (Path.home() / "Library").is_dir() or os.uname().sysname == "Darwin"
    ):
        return downloads

    d = root / "vt-inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_vt_inbox_path(path: str | Path, data_dir: Optional[Path] = None) -> dict:
    import json

    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    cfg = root / "vt-inbox.json"
    payload = {"path": str(p)}
    cfg.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(p), "config": str(cfg)}


def _bundled_runtime_bins() -> list[Path]:
    """Locate ffmpeg/ffprobe shipped next to MQRadioEngine (Electron extraResources)."""
    import sys
    from mq_radio.config import ROOT

    candidates: list[Path] = []
    # Electron: resources/runtime/... beside MQRadioEngine
    env = os.environ.get("MQ_RADIO_RUNTIME_DIR")
    if env:
        candidates.append(Path(env))
    if getattr(sys, "frozen", False):
        # PyInstaller exe lives in MQRadioEngine/; runtime is sibling under Resources
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir.parent / "runtime")
        candidates.append(exe_dir / "runtime")
    candidates.append(ROOT / "desktop" / "resources" / "runtime")
    candidates.append(ROOT / "runtime")
    return candidates


def _is_macho(path: Path) -> bool:
    """True if file looks like a macOS Mach-O binary (skip on Linux hosts)."""
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
        return magic in (
            b"\xfe\xed\xfa\xce",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xce\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
        )
    except OSError:
        return False


def _usable_binary(path: Path) -> bool:
    if not path.is_file() or not os.access(path, os.X_OK):
        return False
    import sys as _sys

    # Darwin static builds are Mach-O — do not prefer them on Linux/CI hosts
    if _sys.platform != "darwin" and _is_macho(path):
        return False
    return True


def _find_bundled(names: tuple[str, ...]) -> str | None:
    for root in _bundled_runtime_bins():
        for rel in names:
            p = root / rel
            if _usable_binary(p):
                return str(p)
    return None


def resolve_ffmpeg() -> str | None:
    """Prefer runnable bundled static ffmpeg (Mac app), else PATH."""
    import sys as _sys

    bundled = _find_bundled(("ffmpeg/ffmpeg", "ffmpeg.bin", "ffmpeg"))
    path_ff = shutil.which("ffmpeg")
    # Frozen / Electron Mac: bundled first. Dev Linux: PATH first (skip Mach-O).
    if getattr(_sys, "frozen", False) or (
        os.environ.get("MQ_RADIO_RUNTIME_DIR") and _sys.platform == "darwin"
    ):
        return bundled or path_ff
    return path_ff or bundled


def resolve_ffprobe() -> str | None:
    import sys as _sys

    bundled = _find_bundled(("ffprobe/ffprobe", "ffprobe.bin", "ffprobe"))
    path_ff = shutil.which("ffprobe")
    if getattr(_sys, "frozen", False) or (
        os.environ.get("MQ_RADIO_RUNTIME_DIR") and _sys.platform == "darwin"
    ):
        return bundled or path_ff or resolve_ffmpeg()
    return path_ff or bundled or resolve_ffmpeg()


def ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE).strip() or "cart"
    return stem[:120]


def _duration_ms_wav(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 44100
            return int(frames / rate * 1000)
    except Exception:
        return 0


def probe_duration_ms(path: Path) -> int:
    """Duration via ffprobe or WAV header; 0 if unknown."""
    if path.suffix.lower() == ".wav":
        ms = _duration_ms_wav(path)
        if ms:
            return ms
    probe = resolve_ffprobe()
    if not probe:
        return 0
    cmd = [
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
        return int(float(out) * 1000)
    except Exception:
        return 0


def extract_audio_from_video(src: Path, dest: Path) -> dict:
    """Extract audio track from video to WAV via ffmpeg. Falls back with clear error."""
    ff = resolve_ffmpeg()
    if not ff:
        return {
            "ok": False,
            "error": (
                "ffmpeg not found — install ffmpeg to extract audio from mp4/mov. "
                "WAV/MP3 can still be ingested without ffmpeg. "
                "Mac package ships ffmpeg under Resources/runtime/."
            ),
        }
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ff,
        "-y",
        "-i",
        str(src),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc))[-500:]
        return {"ok": False, "error": f"ffmpeg extract failed: {err}"}
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg not found on PATH"}
    if not dest.exists() or dest.stat().st_size < 44:
        return {"ok": False, "error": "ffmpeg produced empty audio"}
    return {"ok": True, "path": dest}


def cut_segment(
    src: Path,
    dest: Path,
    *,
    in_ms: int,
    out_ms: int,
) -> dict:
    """Cut [in_ms, out_ms) from src to dest (WAV) using ffmpeg."""
    if out_ms <= in_ms:
        return {"ok": False, "error": "out_ms must be greater than in_ms"}
    ff = resolve_ffmpeg()
    if not ff:
        # Fallback: only allow full-file copy for wav without cut
        return {
            "ok": False,
            "error": "ffmpeg required to cut segments — install ffmpeg or use Mac package runtime",
        }
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = max(0, in_ms) / 1000.0
    dur = (out_ms - in_ms) / 1000.0
    cmd = [
        ff,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        str(src),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc))[-500:]
        return {"ok": False, "error": f"ffmpeg cut failed: {err}"}
    if not dest.exists() or dest.stat().st_size < 44:
        return {"ok": False, "error": "ffmpeg produced empty segment"}
    return {"ok": True, "path": dest, "duration_ms": out_ms - in_ms}


def _category_id(conn, code: str = "A") -> Optional[int]:
    row = conn.execute("SELECT id FROM categories WHERE code = ?", (code,)).fetchone()
    return int(row["id"]) if row else None


def upsert_track(
    file_path: Path,
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    event_type: str = "MUSIC",
    duration_ms: Optional[int] = None,
    category_code: str = "A",
    rotation_category: str = "Library",
    notes_album: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Insert or update a tracks row for file_path."""
    path = Path(file_path).resolve()
    if not path.exists():
        return {"ok": False, "error": f"file not found: {path}"}

    dur = duration_ms if duration_ms is not None else probe_duration_ms(path)
    stem = path.stem
    if title is None or artist is None:
        if " - " in stem:
            a, t = stem.split(" - ", 1)
            artist = artist if artist is not None else a.strip()
            title = title if title is not None else t.strip()
        else:
            artist = artist if artist is not None else "Imported"
            title = title if title is not None else stem

    # Announcer-friendly marker defaults (Maestro-style cold/soft/fade cues)
    dur_i = int(dur or 0)
    intro_ms, outro_ms = default_markers_for(event_type, dur_i)

    conn = get_connection(db_path)
    cat_id = _category_id(conn, category_code)
    existing = conn.execute(
        "SELECT id FROM tracks WHERE file_path = ?", (str(path),)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE tracks SET title=?, artist=?, album=?, duration_ms=?,
               intro_ms=?, outro_ms=?,
               category_id=?, rotation_category=?, event_type=?, active=1,
               updated_at=datetime('now') WHERE id=?""",
            (
                title,
                artist,
                notes_album,
                dur_i,
                intro_ms,
                outro_ms,
                cat_id,
                rotation_category,
                event_type,
                existing["id"],
            ),
        )
        tid = int(existing["id"])
        conn.commit()
        conn.close()
        return {
            "ok": True,
            "track_id": tid,
            "title": title,
            "artist": artist,
            "duration_ms": dur_i,
            "intro_ms": intro_ms,
            "outro_ms": outro_ms,
            "file_path": str(path),
            "updated": True,
            "event_type": event_type,
        }

    cur = conn.execute(
        """INSERT INTO tracks (
            title, artist, album, duration_ms, intro_ms, outro_ms,
            category_id, rotation_category, event_type, file_path, active
        ) VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (
            title,
            artist,
            notes_album,
            dur_i,
            intro_ms,
            outro_ms,
            cat_id,
            rotation_category,
            event_type,
            str(path),
        ),
    )
    tid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "track_id": tid,
        "title": title,
        "artist": artist,
        "duration_ms": dur_i,
        "intro_ms": intro_ms,
        "outro_ms": outro_ms,
        "file_path": str(path),
        "updated": False,
        "event_type": event_type,
    }


def ingest_bytes(
    filename: str,
    data: bytes,
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    event_type: str = "MUSIC",
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> dict:
    """Save uploaded bytes under data/library and register as a cart."""
    if not data:
        return {"ok": False, "error": "empty file"}
    name = Path(filename or "upload.bin").name
    ext = Path(name).suffix.lower()
    if ext not in INGEST_EXTS:
        return {
            "ok": False,
            "error": f"unsupported type {ext or '(none)'} — use wav/mp3/mp4 (flac/ogg/m4a also OK)",
        }

    lib = library_audio_dir(data_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = _safe_stem(Path(name).stem)
    raw_path = lib / f"{safe}_{stamp}{ext}"
    raw_path.write_bytes(data)

    final_path = raw_path
    if ext in VIDEO_EXTS or (ext == ".flac" and ffmpeg_available()):
        wav_path = lib / f"{safe}_{stamp}.wav"
        if ext in VIDEO_EXTS:
            result = extract_audio_from_video(raw_path, wav_path)
        else:
            # Decode FLAC → WAV so carts behave like studio WAV assets
            result = extract_audio_from_video(raw_path, wav_path)  # ffmpeg -vn works for audio-only too
            if not result.get("ok"):
                # keep original flac if decode fails
                final_path = raw_path
                result = {"ok": True, "path": raw_path, "note": "kept original flac"}
        if not result.get("ok"):
            return {**result, "source_path": str(raw_path)}
        if result.get("path") == wav_path or (wav_path.exists() and wav_path.stat().st_size > 44):
            final_path = wav_path
            try:
                if raw_path != wav_path:
                    raw_path.unlink(missing_ok=True)
            except Exception:
                pass

    return upsert_track(
        final_path,
        title=title or Path(name).stem,
        artist=artist or "Imported",
        event_type=event_type,
        db_path=db_path,
    )


def ingest_file(
    src: Path,
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    event_type: str = "MUSIC",
    copy: bool = True,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    dest_subdir: str = "library",
) -> dict:
    """Ingest an existing filesystem path (copy into data/). Supports long concerts."""
    src = Path(src).expanduser().resolve()
    if not src.is_file():
        return {"ok": False, "error": f"not a file: {src}"}
    ext = src.suffix.lower()
    if ext not in INGEST_EXTS:
        return {"ok": False, "error": f"unsupported type {ext}"}

    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    dest_root = root / dest_subdir
    dest_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = _safe_stem(src.stem)
    dest = dest_root / f"{safe}_{stamp}{ext}"

    if copy:
        shutil.copy2(src, dest)
    else:
        dest = src

    final_path = dest
    if ext in VIDEO_EXTS or (ext == ".flac" and ffmpeg_available()):
        wav_path = dest_root / f"{safe}_{stamp}.wav"
        result = extract_audio_from_video(dest, wav_path)
        if not result.get("ok"):
            if ext == ".flac":
                final_path = dest  # keep flac
            else:
                return {**result, "source_path": str(dest)}
        else:
            final_path = wav_path
            if copy and dest != wav_path:
                try:
                    dest.unlink(missing_ok=True)
                except Exception:
                    pass

    return upsert_track(
        final_path,
        title=title or src.stem,
        artist=artist or "Imported",
        event_type=event_type,
        db_path=db_path,
    )


def save_segment_as_cart(
    track_id: int,
    *,
    in_ms: int,
    out_ms: int,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    event_type: str = "MUSIC",
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    allow_markers_only: bool = True,
) -> dict:
    """Cut IN/OUT via ffmpeg into a new cart; fall back to markers-only if no ffmpeg.

    When ffmpeg is available: re-encode a WAV under data/segments/ (real trim).
    When missing (or cut fails) and allow_markers_only: create a cart that
    references the source file with duration=(out-in) and album markers notes —
    no re-encode. Desk still gets a usable Living Log duration.
    """
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": f"track {track_id} not found"}
    src = Path(row["file_path"] or "")
    if not src.is_file():
        return {"ok": False, "error": f"source file missing: {src}"}

    in_ms = max(0, int(in_ms))
    out_ms = int(out_ms)
    src_dur = int(row["duration_ms"] or 0) or probe_duration_ms(src)
    if out_ms <= 0:
        out_ms = src_dur
    if src_dur and out_ms > src_dur:
        out_ms = src_dur
    if out_ms <= in_ms:
        return {"ok": False, "error": "out must be after in"}

    base_title = title or f"{row['title']} [{in_ms}-{out_ms}]"
    artist_out = artist if artist is not None else (row["artist"] or "Segment")
    etype = event_type or (row["event_type"] or "MUSIC")
    dur = out_ms - in_ms

    if ffmpeg_available():
        seg_root = segments_dir(data_dir)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe = _safe_stem(base_title)
        dest = seg_root / f"{safe}_{stamp}.wav"
        cut = cut_segment(src, dest, in_ms=in_ms, out_ms=out_ms)
        if cut.get("ok"):
            res = upsert_track(
                dest,
                title=base_title,
                artist=artist_out,
                event_type=etype,
                duration_ms=dur,
                rotation_category="Segment",
                notes_album=f"segment of track {track_id} cut [{in_ms}-{out_ms}]",
                db_path=db_path,
            )
            if res.get("ok"):
                res["trim_mode"] = "cut"
                res["trim_in_ms"] = in_ms
                res["trim_out_ms"] = out_ms
                res["source_track_id"] = int(track_id)
                res["ffmpeg"] = True
                res["cut"] = True
            return res
        # Cut failed — fall through to markers-only when allowed
        cut_err = cut.get("error") or "ffmpeg cut failed"
        if not allow_markers_only:
            return cut
    else:
        cut_err = "ffmpeg not on PATH"

    if not allow_markers_only:
        return {
            "ok": False,
            "error": f"ffmpeg required to cut segments — {cut_err}",
            "trim_mode": None,
            "ffmpeg": False,
        }

    return markers_only_segment_cart(
        track_id,
        in_ms=in_ms,
        out_ms=out_ms,
        title=base_title,
        artist=artist_out,
        event_type=etype,
        db_path=db_path,
        cut_error=cut_err,
    )


def import_vt_inbox(
    *,
    db_path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    inbox: Optional[Path] = None,
    attach_event_id: Optional[int] = None,
    move: bool = False,
) -> dict:
    """Import .mp3/.wav (and mp4 audio) from VT inbox / Downloads into data/vt + library.

    Optionally attach the newest imported file to a selected VT log event.
    """
    from mq_radio.voice_tracker.recording import vt_audio_dir

    box = Path(inbox) if inbox else vt_inbox_dir(data_dir)
    if not box.is_dir():
        return {"ok": False, "error": f"inbox not found: {box}", "imported": []}

    patterns = ("*.wav", "*.mp3", "*.mp4", "*.m4a", "*.flac", "*.ogg")
    files: list[Path] = []
    for pat in patterns:
        files.extend(box.glob(pat))
    # Prefer newest first
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    imported: list[dict] = []
    errors: list[dict] = []
    for src in files:
        # Skip already-processed marker sidecars
        if src.name.startswith("."):
            continue
        # Heuristic: prefer Vocloner / VT-ish names but accept all audio
        res = ingest_file(
            src,
            title=src.stem,
            artist="Voice Track",
            event_type="VOICE_TRACK",
            copy=True,
            db_path=db_path,
            data_dir=data_dir,
            dest_subdir="vt",
        )
        if not res.get("ok"):
            errors.append({"file": str(src), "error": res.get("error")})
            continue
        # Also ensure a copy path under vt/ is absolute in result
        imported.append({**res, "source": str(src)})
        if move:
            try:
                src.unlink()
            except Exception:
                pass

    attached = None
    if attach_event_id is not None and imported:
        # Attach first (newest) import to VT event via vt_scripts.audio_path
        best = imported[0]
        audio_path = best.get("file_path")
        conn = get_connection(db_path)
        ev = conn.execute(
            "SELECT * FROM log_events WHERE id = ?", (int(attach_event_id),)
        ).fetchone()
        if not ev:
            conn.close()
            attached = {"ok": False, "error": f"event {attach_event_id} not found"}
        else:
            existing = conn.execute(
                "SELECT id FROM vt_scripts WHERE log_event_id = ?",
                (int(attach_event_id),),
            ).fetchone()
            rel = str(audio_path)
            try:
                root = Path(data_dir) if data_dir else _cfg.DATA_DIR
                rel = str(Path(audio_path).resolve().relative_to(root.resolve()))
            except Exception:
                pass
            if existing:
                conn.execute(
                    """UPDATE vt_scripts SET audio_path=?, recorded_at=datetime('now'),
                       status='APPROVED', source='VT_INBOX', updated_at=datetime('now')
                       WHERE id=?""",
                    (rel, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO vt_scripts (
                        log_event_id, variation, script_text, status, source, audio_path, recorded_at
                    ) VALUES (?, 'inbox', ?, 'APPROVED', 'VT_INBOX', ?, datetime('now'))""",
                    (int(attach_event_id), ev["title"] or "Imported VT", rel),
                )
            notes = ev["notes"] or ""
            marker = f"[VT AUDIO {rel}]"
            if marker not in notes:
                notes = (notes + " " + marker).strip() if notes else marker
            conn.execute(
                "UPDATE log_events SET notes=?, event_type='VOICE_TRACK', manual_flag='MANUAL' WHERE id=?",
                (notes, int(attach_event_id)),
            )
            conn.commit()
            conn.close()
            attached = {"ok": True, "log_event_id": int(attach_event_id), "audio_path": rel}

    return {
        "ok": True,
        "inbox": str(box),
        "imported": imported,
        "count": len(imported),
        "errors": errors,
        "attached": attached,
        "ffmpeg": ffmpeg_available(),
    }



def default_markers_for(event_type: str, duration_ms: int) -> tuple[int, int]:
    """Sensible intro / end-pulse (outro) defaults for newly ingested carts."""
    dur_i = max(0, int(duration_ms or 0))
    et = (event_type or "MUSIC").upper()
    if et == "VOICE_TRACK":
        return 0, min(800, dur_i // 10 if dur_i else 0)
    if et in ("ID", "SWEEPER", "PROMO"):
        return 0, min(1500, max(400, dur_i // 8 if dur_i else 400))
    if et == "BED":
        return min(2000, dur_i // 8 if dur_i else 0), min(3000, max(800, dur_i // 5 if dur_i else 800))
    if dur_i >= 180_000:
        return 4000, 6000
    if dur_i >= 90_000:
        return 8000, 5000
    # Short music: keep pulse window meaningful for AUTO/segue (~2–5s)
    intro = min(5000, dur_i // 5 if dur_i else 0)
    outro = min(5000, max(2000, dur_i // 5 if dur_i else 2000))
    if dur_i and outro >= dur_i:
        outro = max(500, dur_i // 4)
    return intro, outro


def update_track_markers(
    track_id: int,
    *,
    intro_ms: Optional[int] = None,
    outro_ms: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Update cart intro / end-pulse (outro_ms) marks used by AUTO and Segue."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM tracks WHERE id = ?", (int(track_id),)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"track {track_id} not found"}
    dur = int(row["duration_ms"] or 0)
    new_intro = int(row["intro_ms"] or 0) if intro_ms is None else max(0, int(intro_ms))
    new_outro = int(row["outro_ms"] or 0) if outro_ms is None else max(0, int(outro_ms))
    if dur > 0:
        # Keep usable body before pulse (≥55% of cart, matching engine clamp)
        max_pulse = max(250, int(dur * 0.45))
        new_outro = min(new_outro, max_pulse)
        if new_intro + new_outro > dur:
            new_intro = max(0, dur - new_outro)
    conn.execute(
        """UPDATE tracks SET intro_ms=?, outro_ms=?, updated_at=datetime('now')
           WHERE id=?""",
        (new_intro, new_outro, int(track_id)),
    )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "track_id": int(track_id),
        "intro_ms": new_intro,
        "outro_ms": new_outro,
        "duration_ms": dur,
        "end_pulse_ms": new_outro,
    }


def get_track(track_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def markers_only_segment_cart(
    track_id: int,
    *,
    in_ms: int,
    out_ms: int,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    event_type: str = "MUSIC",
    db_path: Optional[Path] = None,
    cut_error: Optional[str] = None,
) -> dict:
    """Create a segment cart referencing the source file with IN/OUT markers.

    No re-encode — used when ffmpeg is missing. Living Log duration uses (out-in);
    album notes carry [SEGMENT MARKERS …] for a later cut pass.
    """
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"track {track_id} not found"}
    src = Path(row["file_path"] or "")
    if not src.is_file():
        conn.close()
        return {"ok": False, "error": f"source file missing: {src}"}

    in_ms = max(0, int(in_ms))
    out_ms = int(out_ms)
    src_dur = int(row["duration_ms"] or 0) or probe_duration_ms(src)
    if out_ms <= 0:
        out_ms = src_dur
    if src_dur and out_ms > src_dur:
        out_ms = src_dur
    if out_ms <= in_ms:
        conn.close()
        return {"ok": False, "error": "out must be after in"}

    dur = out_ms - in_ms
    base_title = title or f"{row['title']} [{in_ms}-{out_ms}]"
    artist_out = artist if artist is not None else (row["artist"] or "Segment")
    etype = event_type or (row["event_type"] or "MUSIC")
    reason = cut_error or "ffmpeg not available"
    notes = (
        f"[SEGMENT MARKERS in={in_ms} out={out_ms} of track {track_id}] "
        f"markers-only ({reason}) — install ffmpeg to cut a real WAV segment"
    )
    cat = _category_id(conn, "A")
    intro_ms, outro_ms = default_markers_for(etype, dur)
    cur = conn.execute(
        """INSERT INTO tracks (
            title, artist, album, duration_ms, intro_ms, outro_ms,
            category_id, rotation_category, event_type, file_path, active
        ) VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (
            base_title,
            artist_out,
            notes,
            dur,
            intro_ms,
            outro_ms,
            cat,
            "Segment",
            etype,
            str(src.resolve()),
        ),
    )
    new_id = int(cur.lastrowid)
    # Also stamp source cart with the same window notes (non-destructive)
    src_album = (row["album"] or "") if "album" in row.keys() else ""
    marker = f"[SEGMENT MARKERS in={in_ms} out={out_ms}]"
    if marker not in src_album:
        src_album = (src_album + " " + marker).strip() if src_album else marker
        conn.execute(
            "UPDATE tracks SET album=?, updated_at=datetime('now') WHERE id=?",
            (src_album, int(track_id)),
        )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "track_id": new_id,
        "title": base_title,
        "artist": artist_out,
        "event_type": etype,
        "file_path": str(src.resolve()),
        "duration_ms": dur,
        "intro_ms": intro_ms,
        "outro_ms": outro_ms,
        "trim_mode": "markers_only",
        "trim_in_ms": in_ms,
        "trim_out_ms": out_ms,
        "source_track_id": int(track_id),
        "ffmpeg": False,
        "cut": False,
        "message": f"markers-only segment (no ffmpeg cut): {reason}",
    }

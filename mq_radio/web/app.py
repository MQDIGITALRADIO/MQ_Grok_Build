"""On-Air / Living Log web prototype (stdlib HTTP + SQLite)."""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from mq_radio.config import DATA_DIR, DB_PATH
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import (
    ffmpeg_available,
    get_track,
    import_vt_inbox,
    ingest_bytes,
    library_audio_dir,
    save_library_root_path,
    save_segment_as_cart,
    save_vt_inbox_path,
    vt_inbox_dir,
)
from mq_radio.production.ramps import load_ramps, profile_for_context, save_ramps
from mq_radio.web.media import content_type_for, playable_url, resolve_media_path
from mq_radio.living_log.service import (
    delete_event,
    insert_event,
    list_events,
    list_library,
    load_sample_hour,
    now_and_upcoming,
    replace_event,
)
from mq_radio.segue.service import get_segue, save_segue, segue_context_for_event
from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.recording import attach_vt_cart, save_vt_recording
from mq_radio.voice_tracker.script_generator import daypart_for_hour
from mq_radio.voice_tracker.service import (
    approve_ai_breaks,
    list_vt,
    script_for_transition,
)
from mq_radio.web.hotkeys_store import load_hotkeys, save_hotkeys
from mq_radio.web.multipart import parse_multipart
from mq_radio.production.processing import (
    load_processing,
    processing_summary,
    save_processing,
)
from mq_radio.web.settings_store import (
    load_audio_outputs,
    load_vocloner,
    save_audio_outputs,
    save_vocloner,
)


def _static_dir() -> Path:
    here = Path(__file__).resolve().parent / "static"
    if here.is_dir():
        return here
    import sys
    me = getattr(sys, "_MEI" + "PASS", None)
    if getattr(sys, "frozen", False) and me:
        bundled = Path(me) / "mq_radio" / "web" / "static"
        if bundled.is_dir():
            return bundled
    return here


STATIC_DIR = _static_dir()


def _json_response(handler: BaseHTTPRequestHandler, data, status: int = 200) -> None:
    body = json.dumps(data, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler, body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _synthetic_vu() -> dict:
    """Classic stereo VU levels driven by MockEngine play session (synthetic analyser)."""
    import math
    import time as _time

    with SESSION.lock:
        running = SESSION.running
        started = SESSION.started_at
        dur = SESSION.duration_ms or 0
        etype = SESSION.event_type or ""
    if not running or started is None:
        return {"playing": False, "left": 0.02, "right": 0.02, "peak_left": 0.02, "peak_right": 0.02}
    elapsed = max(0.0, _time.time() - started)
    # Pseudo programme energy: mid-cart louder, soft intro/outro
    progress = (elapsed * 1000 / dur) if dur > 0 else 0.5
    envelope = 0.55 + 0.35 * math.sin(progress * math.pi)
    if etype in ("ID", "SWEEPER", "PROMO"):
        envelope *= 0.85
    t = _time.time()
    left = max(0.0, min(1.0, envelope * (0.72 + 0.28 * math.sin(t * 9.3))))
    right = max(0.0, min(1.0, envelope * (0.70 + 0.30 * math.sin(t * 11.1 + 0.7))))
    # Occasional transient peaks
    if math.sin(t * 3.7) > 0.92:
        left = min(1.0, left * 1.15)
        right = min(1.0, right * 1.12)
    return {
        "playing": True,
        "left": round(left, 3),
        "right": round(right, 3),
        "peak_left": round(min(1.0, left * 1.05), 3),
        "peak_right": round(min(1.0, right * 1.05), 3),
    }




def _media_response(handler: BaseHTTPRequestHandler, path: Path) -> None:
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type_for(path))
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, max-age=30")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def _enrich_playable(ev: dict | None) -> dict | None:
    if not ev:
        return ev
    out = dict(ev)
    tid = out.get("track_id")
    fpath = out.get("file_path") or ""
    url = playable_url(fpath, int(tid) if tid is not None else None)
    if url:
        out["playable_url"] = url
    return out


def make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f"[on-air] {self.address_string()} {fmt % args}")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            log_date = (qs.get("date") or [date.today().isoformat()])[0]

            if path in ("/", "/index.html"):
                html = (STATIC_DIR / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                fp = STATIC_DIR / rel
                if not fp.exists() or not fp.is_file():
                    self.send_error(404)
                    return
                data = fp.read_bytes()
                ctype = "text/css" if fp.suffix == ".css" else "application/javascript"
                if fp.suffix == ".js":
                    ctype = "application/javascript"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/api/status":
                engine = MockEngine(log_date, db_path=db_path)
                engine.finish_if_due()
                data = now_and_upcoming(log_date, db_path=db_path)
                timing = SESSION.timing()
                proc = load_processing(DATA_DIR)
                ramps = load_ramps(DATA_DIR)
                now_ev = _enrich_playable(data.get("now"))
                upcoming = [_enrich_playable(e) for e in (data.get("upcoming") or [])]
                with SESSION.lock:
                    mode = SESSION.playout_mode
                    auto = SESSION.auto_advance
                    sess_path = SESSION.file_path
                    sess_tid = SESSION.track_id
                    ramp_id = SESSION.ramp_profile
                    decks = SESSION.decks_snapshot()
                    segue = dict(SESSION.segue or {})
                    active_deck = SESSION.active_deck
                    overlap = SESSION.overlap_active
                    assist_go = SESSION.assist_go_ready
                # Enrich deck playable URLs
                def _enrich_deck(slot):
                    if not slot:
                        return None
                    out = dict(slot)
                    url = playable_url(out.get("file_path") or "", out.get("track_id"))
                    if url:
                        out["playable_url"] = url
                    return out
                decks["a"] = _enrich_deck(decks.get("a"))
                decks["b"] = _enrich_deck(decks.get("b"))
                decks["program"] = _enrich_deck(decks.get("program"))
                decks["fading"] = _enrich_deck(decks.get("fading"))
                play_url = playable_url(sess_path, sess_tid) if (sess_path or sess_tid) else (
                    (now_ev or {}).get("playable_url")
                )
                fading_url = (decks.get("fading") or {}).get("playable_url")
                _json_response(self, {
                    "date": log_date,
                    "now": now_ev,
                    "upcoming": upcoming,
                    "total": data.get("total"),
                    "timing": timing,
                    "running": SESSION.running,
                    "vu": _synthetic_vu(),
                    "playout_mode": mode,
                    "auto_advance": auto,
                    "playable_url": play_url,
                    "fading_playable_url": fading_url,
                    "ramp_profile": ramp_id or ramps.get("active_profile"),
                    "active_deck": active_deck,
                    "overlap_active": overlap,
                    "assist_go_ready": assist_go,
                    "decks": decks,
                    "segue": segue,
                    "ramps": {
                        "active_profile": ramps.get("active_profile"),
                        "ai_dj_profile": ramps.get("ai_dj_profile"),
                        "active": ramps.get("active"),
                        "ai_dj": ramps.get("ai_dj"),
                    },
                    "processing": {
                        "enabled": proc.get("enabled"),
                        "template": proc.get("template"),
                        "summary": processing_summary(proc),
                        "topology": proc.get("topology"),
                        "stages": proc.get("stages"),
                        "output": proc.get("output"),
                    },
                })
                return

            if path == "/api/vu":
                _json_response(self, _synthetic_vu())
                return

            if path == "/api/log":
                events = list_events(log_date, db_path=db_path)
                _json_response(self, {"date": log_date, "events": events})
                return

            if path == "/api/library":
                q = (qs.get("q") or [""])[0]
                tracks = list_library(q=q, db_path=db_path)
                _json_response(self, {"tracks": tracks, "q": q})
                return

            if path == "/api/hotkeys":
                _json_response(self, load_hotkeys(DATA_DIR))
                return

            if path == "/api/settings/audio":
                _json_response(self, load_audio_outputs(DATA_DIR))
                return

            if path == "/api/settings/vocloner":
                _json_response(self, load_vocloner(DATA_DIR))
                return

            if path == "/api/vt":
                status = (qs.get("status") or [None])[0]
                rows = list_vt(log_date, db_path=db_path, status=status)
                _json_response(self, {"date": log_date, "voice_tracks": rows})
                return

            if path == "/api/segue":
                try:
                    eid = int((qs.get("event_id") or ["0"])[0])
                except ValueError:
                    _json_response(self, {"ok": False, "error": "event_id required"}, status=400)
                    return
                _json_response(self, segue_context_for_event(eid, db_path=db_path))
                return

            if path == "/api/segue/get":
                try:
                    from_id = int((qs.get("from_event_id") or ["0"])[0])
                except ValueError:
                    _json_response(self, {"ok": False, "error": "from_event_id required"}, status=400)
                    return
                to_raw = (qs.get("to_event_id") or [None])[0]
                to_id = int(to_raw) if to_raw else None
                row = get_segue(from_id, to_id, db_path=db_path)
                _json_response(self, {"ok": True, "segue": row})
                return

            if path == "/api/library/track":
                try:
                    tid = int((qs.get("id") or ["0"])[0])
                except ValueError:
                    _json_response(self, {"ok": False, "error": "id required"}, status=400)
                    return
                row = get_track(tid, db_path=db_path)
                if not row:
                    _json_response(self, {"ok": False, "error": "not found"}, status=404)
                    return
                _json_response(self, {
                    "ok": True,
                    "track": {
                        "id": int(row["id"]),
                        "title": row["title"],
                        "artist": row["artist"],
                        "duration_ms": int(row["duration_ms"] or 0),
                        "event_type": row["event_type"] or "MUSIC",
                        "file_path": row["file_path"] or "",
                    },
                })
                return

            if path == "/api/settings/vt-inbox":
                inbox = vt_inbox_dir(DATA_DIR)
                _json_response(self, {
                    "ok": True,
                    "path": str(inbox),
                    "ffmpeg": ffmpeg_available(),
                })
                return

            if path == "/api/settings/processing":
                _json_response(self, load_processing(DATA_DIR))
                return

            if path == "/api/settings/library-root":
                lib = library_audio_dir(DATA_DIR)
                _json_response(self, {"ok": True, "path": str(lib)})
                return

            if path == "/api/settings/ramps":
                _json_response(self, load_ramps(DATA_DIR))
                return

            if path.startswith("/api/media/track/"):
                raw_id = path.rsplit("/", 1)[-1]
                try:
                    tid = int(raw_id)
                except ValueError:
                    self.send_error(400)
                    return
                row = get_track(tid, db_path=db_path)
                if not row or not row.get("file_path"):
                    self.send_error(404)
                    return
                mp = resolve_media_path(row["file_path"], DATA_DIR)
                if not mp:
                    self.send_error(404)
                    return
                _media_response(self, mp)
                return

            if path == "/api/media":
                raw = (qs.get("path") or [""])[0]
                mp = resolve_media_path(raw, DATA_DIR)
                if not mp:
                    self.send_error(404)
                    return
                _media_response(self, mp)
                return

            self.send_error(404)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            log_date = (qs.get("date") or [date.today().isoformat()])[0]
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "multipart/form-data" in ctype:
                payload = {}
            else:
                payload = _read_json(self, body)

            if path == "/api/settings/audio":
                # Full routing matrix: outputs + inputs + AU insert stub
                body = payload if isinstance(payload, dict) else {}
                _json_response(self, save_audio_outputs(body, DATA_DIR))
                return

            if path == "/api/settings/vocloner":
                _json_response(self, save_vocloner(payload, DATA_DIR))
                return

            if path == "/api/hotkeys":
                items = payload.get("hotkeys") if isinstance(payload.get("hotkeys"), list) else payload
                if not isinstance(items, list):
                    _json_response(self, {"ok": False, "error": "hotkeys list required"}, status=400)
                    return
                _json_response(self, save_hotkeys(items, DATA_DIR))
                return

            if path == "/api/hotkey/fire":
                # One-shot / hotkey: play from absolute path or track id — NEVER force library copy
                from pathlib import Path as _P
                target = payload.get("target")
                file_path = payload.get("path") or payload.get("file_path")
                label = payload.get("label") or "Hotkey"
                resolved = None
                kind = None
                if file_path:
                    p = _P(str(file_path)).expanduser()
                    resolved = str(p)
                    kind = "path"
                    exists = p.is_file()
                elif target is not None and str(target).isdigit():
                    row = get_track(int(target), db_path=db_path)
                    if row:
                        resolved = row.get("file_path") or ""
                        kind = "track"
                        exists = bool(resolved and _P(resolved).is_file())
                    else:
                        exists = False
                elif target and ("/" in str(target) or str(target).startswith("~")):
                    p = _P(str(target)).expanduser()
                    resolved = str(p)
                    kind = "path"
                    exists = p.is_file()
                else:
                    exists = False
                    resolved = str(target) if target else None
                    kind = "label"
                track_id = None
                if kind == "track" and target is not None and str(target).isdigit():
                    track_id = int(target)
                url = None
                if exists and resolved:
                    url = playable_url(resolved, track_id)
                elif track_id is not None:
                    url = playable_url(None, track_id)
                _json_response(self, {
                    "ok": True,
                    "fired": True,
                    "label": label,
                    "kind": kind,
                    "path": resolved,
                    "exists": exists,
                    "playable_url": url,
                    "track_id": track_id,
                    "copied_to_library": False,
                    "message": (
                        f"ONE-SHOT {label}: {resolved or '(no path)'}"
                        + (" [missing file]" if resolved and not exists else "")
                        + (" · playing" if url and exists else " — path reference only, not ingested")
                    ),
                })
                return

            if path == "/api/log/delete":
                eid = payload.get("event_id")
                if eid is None:
                    _json_response(self, {"ok": False, "error": "event_id required"}, status=400)
                    return
                result = delete_event(int(eid), db_path=db_path)
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/log/insert":
                d = payload.get("date") or log_date
                after = payload.get("after_position")
                if after is None:
                    after = -1
                event_dict = {
                    "track_id": payload.get("track_id"),
                    "event_type": payload.get("event_type"),
                    "title": payload.get("title"),
                    "artist": payload.get("artist"),
                    "duration_ms": payload.get("duration_ms"),
                }
                result = insert_event(d, int(after), event_dict, db_path=db_path)
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/log/replace":
                eid = payload.get("event_id")
                tid = payload.get("track_id")
                if eid is None or tid is None:
                    _json_response(self, {"ok": False, "error": "event_id and track_id required"}, status=400)
                    return
                result = replace_event(int(eid), int(tid), db_path=db_path)
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/log/sample-hour":
                d = payload.get("date") or log_date
                if d in ("today", "Today"):
                    d = date.today().isoformat()
                hour = int(payload.get("hour") if payload.get("hour") is not None else 12)
                clear = payload.get("clear_day", True)
                result = load_sample_hour(d, db_path=db_path, hour=hour, clear_day=bool(clear))
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/vt/attach-cart":
                eid = payload.get("event_id") or payload.get("log_event_id")
                tid = payload.get("track_id")
                if eid is None or tid is None:
                    _json_response(self, {"ok": False, "error": "event_id and track_id required"}, status=400)
                    return
                result = attach_vt_cart(
                    int(eid),
                    int(tid),
                    db_path=db_path,
                    data_dir=DATA_DIR,
                )
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/vt/record":
                eid = payload.get("event_id") or payload.get("log_event_id")
                if eid is None:
                    _json_response(self, {"ok": False, "error": "event_id required"}, status=400)
                    return
                result = save_vt_recording(
                    int(eid),
                    audio_b64=payload.get("audio_b64") or payload.get("audio") or "",
                    mime=payload.get("mime") or "audio/webm",
                    trim_in_ms=int(payload.get("trim_in_ms") or 0),
                    trim_out_ms=payload.get("trim_out_ms"),
                    script_text=payload.get("script_text") or payload.get("script"),
                    db_path=db_path,
                    data_dir=DATA_DIR,
                )
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/segue/save":
                result = save_segue(payload, db_path=db_path)
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/ai-breaks/generate":
                result = generate_ai_breaks(
                    log_date,
                    db_path=db_path,
                    station_name=payload.get("station_name") or "MQ Digital",
                    style=payload.get("style") or "warm",
                    insert_gaps=not payload.get("no_insert"),
                )
                status = 200 if result.get("ok") else 400
                _json_response(self, result, status=status)
                return

            if path == "/api/ai-breaks/approve":
                result = approve_ai_breaks(log_date, db_path=db_path)
                status = 200 if result.get("ok") else 400
                _json_response(self, result, status=status)
                return

            if path == "/api/vt/generate-script":
                hour = payload.get("hour")
                if hour is None and payload.get("scheduled_at"):
                    try:
                        hour = int(str(payload["scheduled_at"]).split("T")[1].split(":")[0])
                    except Exception:
                        hour = 12
                if hour is None:
                    hour = 12
                daypart = payload.get("daypart") or daypart_for_hour(int(hour))
                result = script_for_transition(
                    prev_track=payload.get("prev_track"),
                    next_track=payload.get("next_track"),
                    daypart=daypart,
                    station_name=payload.get("station_name") or "MQ Digital",
                    style=payload.get("style") or "warm",
                    variation=payload.get("variation"),
                )
                _json_response(self, result)
                return

            if path == "/api/settings/processing":
                _json_response(self, save_processing(payload, DATA_DIR))
                return

            if path == "/api/settings/vt-inbox":
                raw_path = payload.get("path") or ""
                if not raw_path:
                    _json_response(self, {"ok": False, "error": "path required"}, status=400)
                    return
                _json_response(self, save_vt_inbox_path(raw_path, DATA_DIR))
                return

            if path == "/api/library/ingest":
                ctype = (self.headers.get("Content-Type") or "").lower()
                title = payload.get("title")
                artist = payload.get("artist")
                event_type = payload.get("event_type") or "MUSIC"
                if "multipart/form-data" in ctype:
                    parts = parse_multipart(self.headers.get("Content-Type") or "", body)
                    file_part = parts.get("file") or parts.get("audio") or parts.get("upload")
                    if not isinstance(file_part, dict) or not file_part.get("data"):
                        _json_response(self, {"ok": False, "error": "file field required"}, status=400)
                        return
                    title = parts.get("title") or title
                    artist = parts.get("artist") or artist
                    event_type = parts.get("event_type") or event_type
                    result = ingest_bytes(
                        file_part.get("filename") or "upload.bin",
                        file_part["data"],
                        title=title if isinstance(title, str) else None,
                        artist=artist if isinstance(artist, str) else None,
                        event_type=str(event_type or "MUSIC"),
                        db_path=db_path,
                        data_dir=DATA_DIR,
                    )
                else:
                    import base64
                    b64 = payload.get("audio_b64") or payload.get("data_b64") or ""
                    filename = payload.get("filename") or payload.get("name") or "upload.bin"
                    if not b64:
                        _json_response(self, {"ok": False, "error": "file or audio_b64 required"}, status=400)
                        return
                    raw = b64
                    if "," in raw and str(raw).strip().startswith("data:"):
                        raw = str(raw).split(",", 1)[1]
                    try:
                        blob = base64.b64decode(raw)
                    except Exception as exc:
                        _json_response(self, {"ok": False, "error": f"invalid base64: {exc}"}, status=400)
                        return
                    result = ingest_bytes(
                        filename,
                        blob,
                        title=title,
                        artist=artist,
                        event_type=str(event_type or "MUSIC"),
                        db_path=db_path,
                        data_dir=DATA_DIR,
                    )
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/library/segment":
                tid = payload.get("track_id")
                if tid is None:
                    _json_response(self, {"ok": False, "error": "track_id required"}, status=400)
                    return
                result = save_segment_as_cart(
                    int(tid),
                    in_ms=int(payload.get("in_ms") or 0),
                    out_ms=int(payload.get("out_ms") or 0),
                    title=payload.get("title"),
                    artist=payload.get("artist"),
                    event_type=payload.get("event_type") or "MUSIC",
                    db_path=db_path,
                    data_dir=DATA_DIR,
                )
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/vt/import-inbox":
                attach = payload.get("event_id") or payload.get("log_event_id")
                inbox = payload.get("path") or None
                result = import_vt_inbox(
                    db_path=db_path,
                    data_dir=DATA_DIR,
                    inbox=Path(inbox) if inbox else None,
                    attach_event_id=int(attach) if attach is not None else None,
                    move=bool(payload.get("move")),
                )
                _json_response(self, result, status=200 if result.get("ok") else 400)
                return

            if path == "/api/settings/library-root":
                raw_path = payload.get("path") or ""
                if not raw_path:
                    _json_response(self, {"ok": False, "error": "path required"}, status=400)
                    return
                _json_response(self, save_library_root_path(raw_path, DATA_DIR))
                return

            if path == "/api/settings/ramps":
                _json_response(self, save_ramps(payload, DATA_DIR))
                return

            if path == "/api/mode":
                mode = str(payload.get("mode") or "AUTO").upper()
                if mode not in ("AUTO", "ASSIST", "LIVE"):
                    mode = "AUTO"
                with SESSION.lock:
                    SESSION.playout_mode = mode
                    SESSION.auto_advance = mode == "AUTO"
                _json_response(self, {
                    "ok": True,
                    "mode": mode,
                    "auto_advance": mode == "AUTO",
                })
                return

            if path == "/api/pulse":
                # Client end-pulse / ASSIST GO → overlapping dual-deck advance
                force = bool(payload.get("force") or payload.get("go"))
                engine = MockEngine(log_date, db_path=db_path)
                with SESSION.lock:
                    assist_armed = SESSION.assist_go_ready
                    mode = SESSION.playout_mode
                if force or (assist_armed and mode in ("ASSIST", "LIVE")):
                    st = engine.advance_with_overlap(force=True)
                    advanced = True
                else:
                    advanced = engine.finish_if_due()
                    st = engine.status()
                with SESSION.lock:
                    decks = SESSION.decks_snapshot()
                    segue = dict(SESSION.segue or {})
                _json_response(self, {
                    "ok": True,
                    "advanced": advanced,
                    "message": st.message,
                    "running": st.running,
                    "title": st.current_title,
                    "overlap_active": decks.get("overlap_active"),
                    "active_deck": decks.get("active"),
                    "assist_go_ready": decks.get("assist_go_ready"),
                    "segue": segue,
                    "decks": decks,
                })
                return

            engine = MockEngine(log_date, db_path=db_path)
            if path == "/api/play":
                st = engine.play()
            elif path == "/api/stop":
                st = engine.stop()
            elif path == "/api/skip":
                engine._running = True
                st = engine.skip()
            elif path == "/api/step":
                st = engine.step()
            else:
                self.send_error(404)
                return
            _json_response(self, {
                "message": st.message,
                "running": st.running,
                "position": st.position,
                "title": st.current_title,
                "artist": st.current_artist,
            })

    return Handler


def run_server(host: str = "127.0.0.1", port: int = 8080, db_path: Optional[Path] = None) -> None:
    db = db_path or DB_PATH
    handler = make_handler(db)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"On-Air prototype at http://{host}:{port}/  (db={db})")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()

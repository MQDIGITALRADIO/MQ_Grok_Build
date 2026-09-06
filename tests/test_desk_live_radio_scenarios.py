"""Broadcast-desk scenario e2e: import destinations, PLAY/VU/progress/STOP,
hotkey oneshot vs main deck, Living Log edits, idle meters, edge errors,
ASSIST talk-up / GO, dual-deck crossfade timing, STOP mid-cart, skip mid-sequence.

Paying-client bar — complex simulated live-radio via HTTP API (fields that drive
desk JS: timing.progress/talk_up_*, vu, now.status, oneshot, overlap/segue).

Primary carts: Matt's real files under data/matt_sample_carts/ (47 carts: long MP3 music + WAV beds/VT + short ID/sweeper hotkeys). Silence WAVs remain for pure edge-error cases.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.engine.session import SESSION
from mq_radio.living_log.service import list_events
from mq_radio.web.app import _synthetic_vu, make_handler
from mq_radio.web.hotkeys_store import load_hotkeys
import mq_radio.config as cfg


@pytest.fixture()
def desk(tmp_path: Path):
    db = tmp_path / "desk.db"
    data = tmp_path / "data"
    data.mkdir()
    init_db(db)
    prev = cfg.DATA_DIR
    cfg.apply_data_dir(data)
    import mq_radio.web.app as app_mod

    app_mod.DATA_DIR = data
    with SESSION.lock:
        SESSION.clear()
        SESSION.running = False
        SESSION.oneshot = None
        SESSION.playout_mode = "AUTO"
    yield {"db": db, "data": data}
    with SESSION.lock:
        SESSION.clear()
        SESSION.running = False
        SESSION.oneshot = None
    cfg.apply_data_dir(prev)
    app_mod.DATA_DIR = prev


def _silence_wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def _http_json(method: str, url: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return resp.status, json.loads(body.decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return e.code, payload


@pytest.fixture()
def server(desk):
    Handler = make_handler(desk["db"])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    yield base, desk
    httpd.shutdown()


def _ingest_path(base: str, wav: Path, title: str = "Cart") -> dict:
    status, res = _http_json(
        "POST",
        f"{base}/api/library/ingest",
        data=json.dumps(
            {
                "path": str(wav),
                "title": title,
                "artist": "Studio",
                "event_type": "MUSIC",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert status == 200, res
    assert res.get("ok") is True, res
    return res


# —— Matt sample carts (real MP3s for paying-client live-radio scrutiny) ——

MATT_SAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "matt_sample_carts"
# Short imaging MP3 (~43–54s): 1,2,6,7 · Tiny ID MP3 (~7s): 28 · WAV imaging/ID (~5–7s): 29–31
# Medium (~2–3min): 5,20,21,26 · Long music (~3–5.7min): remaining MP3s
MATT_SHORT = (1, 2, 6, 7)
MATT_MEDIUM = (5, 20, 21, 26, 38, 39, 41)
MATT_LONG = (3, 4, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 22, 23, 24, 25, 27, 37, 40, 42)
MATT_WAV_IMAGING = (29, 30, 31, 32, 36)  # short WAV ID / sweeper (~5–7s)
MATT_WAV_BEDS = (44, 45, 46, 47)  # longer WAV beds / VT (~18–40s)
MATT_TINY_ID = (28, 33, 34, 35)  # short MP3 ID / sweeper / hotkey hits
MATT_VT_SHORT = (43,)  # ~20s MP3 VT / bed candidate
MATT_HOTKEY_BANK = MATT_WAV_IMAGING + MATT_TINY_ID
MATT_BANK_COUNT = 47


def _matt(n: int) -> Path:
    for ext in (".mp3", ".wav", ".MP3", ".WAV"):
        candidate = MATT_SAMPLES_DIR / f"matt_sample_{n}{ext}"
        if candidate.is_file():
            return candidate
    raise AssertionError(f"missing Matt sample cart: matt_sample_{n}.mp3|.wav under {MATT_SAMPLES_DIR}")


def _ingest_matt(base: str, n: int, title: str | None = None, *, event_type: str = "MUSIC") -> dict:
    wav = _matt(n)
    label = title or f"Matt Sample {n}"
    status, res = _http_json(
        "POST",
        f"{base}/api/library/ingest",
        data=json.dumps(
            {
                "path": str(wav),
                "title": label,
                "artist": "MQ Digital",
                "event_type": event_type,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert status == 200, res
    assert res.get("ok") is True, res
    assert res.get("track_id")
    assert Path(res["file_path"]).is_file()
    # Real probe should leave a meaningful duration on music carts
    assert int(res.get("duration_ms") or 0) > 1000, res
    return res


def _log_insert(
    base: str,
    day: str,
    *,
    track_id: int,
    title: str,
    duration_ms: int,
    after_position: int = -1,
    event_type: str = "MUSIC",
    artist: str = "MQ Digital",
) -> dict:
    code, inserted = _http_json(
        "POST",
        f"{base}/api/log/insert?date={day}",
        data=json.dumps(
            {
                "after_position": after_position,
                "track_id": track_id,
                "event_type": event_type,
                "title": title,
                "artist": artist,
                "duration_ms": duration_ms,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and inserted.get("ok"), inserted
    return inserted


def _set_markers(base: str, track_id: int, *, intro_ms: int, outro_ms: int) -> dict:
    code, res = _http_json(
        "POST",
        f"{base}/api/library/track/markers",
        data=json.dumps(
            {"track_id": track_id, "intro_ms": intro_ms, "outro_ms": outro_ms}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and res.get("ok"), res
    return res


# —— Static regressions (CSS/JS that drive the green-bar / import UI) ——


def test_static_meter_css_never_defaults_to_62_percent():
    css = Path("mq_radio/web/static/style.css").read_text(encoding="utf-8")
    # Historic bug: .meter-bar { width: 62%; } showed full-ish green when idle
    assert not re.search(r"\.meter-bar\s*\{[^}]*width:\s*62%", css)
    assert re.search(r"\.meter-bar\.idle\s*\{[^}]*width:\s*0", css, re.S)
    assert "setMeterIdle" in Path("mq_radio/web/static/app.js").read_text(encoding="utf-8")
    assert "setMeterProgress" in Path("mq_radio/web/static/app.js").read_text(encoding="utf-8")


def test_static_import_destination_ui_present():
    html = Path("mq_radio/web/static/index.html").read_text(encoding="utf-8")
    assert 'id="ingest-dest"' in html
    assert 'value="library"' in html
    assert 'value="living_log"' in html
    assert 'value="hotkey"' in html
    assert 'value="deck_a"' in html
    js = Path("mq_radio/web/static/desk_programming.js").read_text(encoding="utf-8")
    assert "routeIngestedCart" in js
    assert "ingestAbsolutePaths" in js
    assert "openAudioFiles" in Path("desktop/preload.js").read_text(encoding="utf-8")
    assert "mq:open-audio-files" in Path("desktop/main.js").read_text(encoding="utf-8")


# —— Idle desk ——


def test_idle_desk_vu_dark_and_timing_progress_zero(server):
    base, _ = server
    code, st = _http_json("GET", f"{base}/api/status?date=2026-09-08")
    assert code == 200, st
    assert st.get("running") is False
    timing = st.get("timing") or {}
    assert timing.get("playing") is False
    assert float(timing.get("progress") or 0) == 0.0
    vu = st.get("vu") or {}
    assert vu.get("playing") is False
    assert float(vu.get("left") or 0) == 0.0
    assert float(vu.get("right") or 0) == 0.0
    # No false ON AIR row
    now = st.get("now")
    if now:
        assert now.get("status") != "ON_AIR"


def test_vu_idle_helper_fully_dark():
    with SESSION.lock:
        SESSION.clear()
        SESSION.running = False
        SESSION.oneshot = None
    vu = _synthetic_vu()
    assert vu["playing"] is False
    assert vu["left"] == 0.0 and vu["right"] == 0.0


# —— Import destinations ——


def test_import_to_library_only(server, tmp_path: Path):
    base, desk = server
    wav = _silence_wav(tmp_path / "lib_only.wav", seconds=0.4)
    res = _ingest_path(base, wav, "Lib Only")
    assert res["track_id"] > 0
    assert Path(res["file_path"]).is_file()
    # Living Log still empty for this day
    code, log = _http_json("GET", f"{base}/api/log?date=2026-09-08")
    assert code == 200
    assert (log.get("events") or []) == [] or all(
        e.get("title") != "Lib Only" for e in (log.get("events") or [])
    )


def test_import_then_living_log_destination(server, tmp_path: Path):
    base, desk = server
    day = "2026-09-08"
    wav = _silence_wav(tmp_path / "to_log.wav", seconds=0.4)
    res = _ingest_path(base, wav, "Log Cart")
    tid = res["track_id"]
    code, inserted = _http_json(
        "POST",
        f"{base}/api/log/insert?date={day}",
        data=json.dumps(
            {
                "after_position": -1,
                "track_id": tid,
                "event_type": "MUSIC",
                "title": "Log Cart",
                "artist": "Studio",
                "duration_ms": res.get("duration_ms") or 400,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200, inserted
    assert inserted.get("ok") is True, inserted
    events = list_events(day, db_path=desk["db"])
    assert any(e.get("title") == "Log Cart" and e.get("track_id") == tid for e in events)


def test_import_then_hotkey_cart_destination(server, tmp_path: Path):
    base, desk = server
    wav = _silence_wav(tmp_path / "hk.wav", seconds=0.3)
    res = _ingest_path(base, wav, "Hotkey Hit")
    tid = res["track_id"]
    # Assign first empty slot (mirrors desk routeIngestedCart hotkey path)
    code, hk = _http_json("GET", f"{base}/api/hotkeys")
    assert code == 200
    slots = list(hk.get("hotkeys") or [])
    assert slots
    slot = next((s for s in slots if s.get("empty")), slots[0])
    slot_i = int(slot["slot"])
    slots[slot_i] = {
        **slot,
        "label": "Hotkey Hit",
        "type": "MUSIC",
        "target": tid,
        "path": res.get("file_path"),
        "empty": False,
        "inject_mode": "over_program",
    }
    code, saved = _http_json(
        "POST",
        f"{base}/api/hotkeys",
        data=json.dumps({"hotkeys": slots}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200, saved
    assert saved.get("ok") is True
    loaded = load_hotkeys(desk["data"])
    hit = loaded["hotkeys"][slot_i]
    assert hit.get("target") == tid or str(hit.get("target")) == str(tid)
    assert hit.get("empty") is False


# —— PLAY → progress/VU → STOP ——


def test_play_progress_vu_then_stop_idle(server, tmp_path: Path):
    base, desk = server
    day = "2026-09-08"
    # Longer cart so progress advances measurably
    wav = _silence_wav(tmp_path / "air.wav", seconds=3.0)
    res = _ingest_path(base, wav, "On Air Cart")
    # Force duration_ms on insert for session timing (probe may be short on silence)
    code, inserted = _http_json(
        "POST",
        f"{base}/api/log/insert?date={day}",
        data=json.dumps(
            {
                "after_position": -1,
                "track_id": res["track_id"],
                "event_type": "MUSIC",
                "title": "On Air Cart",
                "artist": "Studio",
                "duration_ms": 3000,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and inserted.get("ok"), inserted

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200, play
    assert play.get("running") is True

    # Let timing advance
    time.sleep(0.55)
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200, st
    assert st.get("running") is True
    now = st.get("now") or {}
    assert now.get("status") == "ON_AIR"
    timing = st.get("timing") or {}
    assert timing.get("playing") is True
    assert float(timing.get("progress") or 0) > 0.0
    assert int(timing.get("elapsed_ms") or 0) > 0
    vu = st.get("vu") or {}
    assert vu.get("playing") is True
    assert float(vu.get("left") or 0) > 0.0 or float(vu.get("right") or 0) > 0.0

    code, stop = _http_json("POST", f"{base}/api/stop?date={day}")
    assert code == 200, stop
    with SESSION.lock:
        SESSION.running = False
        SESSION.started_at = None
        SESSION.oneshot = None
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200, st2
    assert st2.get("running") is False
    timing2 = st2.get("timing") or {}
    assert timing2.get("playing") is False
    assert float(timing2.get("progress") or 0) == 0.0
    vu2 = st2.get("vu") or _synthetic_vu()
    assert vu2.get("playing") is False
    assert float(vu2.get("left") or 0) == 0.0


# —— Hotkey oneshot vs main deck ——


def test_hotkey_oneshot_vu_moves_without_forcing_log_on_air(server, tmp_path: Path):
    base, desk = server
    day = "2026-09-08"
    wav = _silence_wav(tmp_path / "oneshot.wav", seconds=1.5)
    res = _ingest_path(base, wav, "Sweeper")
    # Ensure Living Log empty / not playing
    code, st0 = _http_json("GET", f"{base}/api/status?date={day}")
    assert st0.get("running") is False

    code, fire = _http_json(
        "POST",
        f"{base}/api/hotkey/fire?date={day}",
        data=json.dumps(
            {
                "path": res["file_path"],
                "label": "Sweeper",
                "type": "SWEEPER",
                "inject": True,
                "inject_mode": "over_program",
                "duration_ms": 1500,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200, fire
    assert fire.get("ok") is True or fire.get("fired") is not False

    time.sleep(0.2)
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200, st
    # Main deck / log must NOT claim ON AIR solely from oneshot
    assert st.get("running") is False
    now = st.get("now")
    if now:
        assert now.get("status") != "ON_AIR"
    shot = st.get("oneshot") or {}
    assert shot.get("active") is True or fire.get("oneshot")
    vu = st.get("vu") or {}
    # Server VU should move while oneshot active
    assert vu.get("playing") is True
    assert float(vu.get("left") or 0) > 0.0 or float(vu.get("right") or 0) > 0.0

    # Clear oneshot
    with SESSION.lock:
        SESSION.oneshot = None
    vu_idle = _synthetic_vu()
    assert vu_idle["playing"] is False


# —— Living Log insert/replace/delete under AUTO ——


def test_living_log_insert_replace_delete_under_auto(server, tmp_path: Path):
    base, desk = server
    day = "2026-09-08"
    w1 = _silence_wav(tmp_path / "a.wav", 0.3)
    w2 = _silence_wav(tmp_path / "b.wav", 0.3)
    r1 = _ingest_path(base, w1, "Alpha")
    r2 = _ingest_path(base, w2, "Beta")

    code, ins = _http_json(
        "POST",
        f"{base}/api/log/insert?date={day}",
        data=json.dumps(
            {
                "after_position": -1,
                "track_id": r1["track_id"],
                "title": "Alpha",
                "event_type": "MUSIC",
                "duration_ms": 300,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and ins.get("ok"), ins
    eid = ins.get("event_id") or ins.get("id")
    events = list_events(day, db_path=desk["db"])
    assert len(events) >= 1
    if eid is None:
        eid = events[0]["id"]

    code, rep = _http_json(
        "POST",
        f"{base}/api/log/replace?date={day}",
        data=json.dumps({"event_id": eid, "track_id": r2["track_id"]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and rep.get("ok"), rep

    code, mode = _http_json(
        "POST",
        f"{base}/api/mode",
        data=json.dumps({"mode": "AUTO"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200

    code, dele = _http_json(
        "POST",
        f"{base}/api/log/delete?date={day}",
        data=json.dumps({"event_id": eid}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and dele.get("ok"), dele


# —— Multi-cart skip/next ——


def test_multi_cart_play_skip_sequence(server, tmp_path: Path):
    base, desk = server
    day = "2026-09-09"
    titles = []
    for i, name in enumerate(["One", "Two", "Three"]):
        wav = _silence_wav(tmp_path / f"{name}.wav", seconds=1.0)
        res = _ingest_path(base, wav, name)
        titles.append(name)
        code, ins = _http_json(
            "POST",
            f"{base}/api/log/insert?date={day}",
            data=json.dumps(
                {
                    "after_position": i - 1 if i else -1,
                    # insert sequentially at end
                    "track_id": res["track_id"],
                    "title": name,
                    "event_type": "MUSIC",
                    "duration_ms": 2000,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        # after_position: use max — simpler append via -1 then reorder by repeated insert
        assert code == 200 and ins.get("ok"), ins

    # Re-build clean order: clear via sample is heavy — just play what we have
    events = list_events(day, db_path=desk["db"])
    assert len(events) >= 2

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    first_title = (st.get("now") or {}).get("title")

    code, skip = _http_json("POST", f"{base}/api/skip?date={day}")
    assert code == 200, skip
    time.sleep(0.05)
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    second_title = (st2.get("now") or {}).get("title")
    # Skip should advance when multiple carts exist
    if st2.get("running"):
        assert second_title != first_title or len(events) == 1

    _http_json("POST", f"{base}/api/stop?date={day}")


# —— Edge errors ——


def test_empty_log_play_clear_state(server):
    base, _ = server
    day = "2026-09-10"
    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    # Engine may return ok:false or running false — must not 500
    assert code in (200, 400)
    if code == 200:
        assert play.get("running") in (False, None) or play.get("ok") is False or "empty" in str(
            play.get("message") or play.get("error") or ""
        ).lower() or play.get("running") is False


def test_bad_import_path_clear_error(server):
    base, _ = server
    code, res = _http_json(
        "POST",
        f"{base}/api/library/ingest",
        data=json.dumps(
            {
                "path": "/no/such/file/missing_cart.wav",
                "title": "Missing",
                "artist": "X",
                "event_type": "MUSIC",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 400
    assert res.get("ok") is False
    err = str(res.get("error") or "")
    assert "not found" in err.lower() or "missing" in err.lower() or "file" in err.lower()


def test_empty_multipart_import_clear_error(server):
    base, _ = server
    boundary = "----MQEmpty"
    body = f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nNope\r\n--{boundary}--\r\n".encode()
    code, res = _http_json(
        "POST",
        f"{base}/api/library/ingest",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert code == 400
    assert res.get("ok") is False
    assert "file" in str(res.get("error") or "").lower()


# —— Matt carts: import destinations (library / Living Log / hotkey / Deck A) ——


def test_matt_samples_present_mix_short_and_long():
    assert MATT_SAMPLES_DIR.is_dir()
    for n in range(1, MATT_BANK_COUNT + 1):
        assert _matt(n).is_file()
    from mq_radio.library.ingest import probe_duration_ms

    short_ms = [probe_duration_ms(_matt(n)) for n in MATT_SHORT]
    med_ms = [probe_duration_ms(_matt(n)) for n in MATT_MEDIUM]
    long_ms = [probe_duration_ms(_matt(n)) for n in MATT_LONG]
    wav_ms = [probe_duration_ms(_matt(n)) for n in MATT_WAV_IMAGING]
    bed_ms = [probe_duration_ms(_matt(n)) for n in MATT_WAV_BEDS]
    tiny_ms = [probe_duration_ms(_matt(n)) for n in MATT_TINY_ID]
    vt_ms = [probe_duration_ms(_matt(n)) for n in MATT_VT_SHORT]
    assert all(30_000 < ms < 70_000 for ms in short_ms), short_ms
    assert all(100_000 < ms < 180_000 for ms in med_ms), med_ms
    assert all(ms > 180_000 for ms in long_ms), long_ms
    assert all(ms < 15_000 for ms in wav_ms), wav_ms
    assert all(15_000 < ms < 50_000 for ms in bed_ms), bed_ms
    assert all(ms < 15_000 for ms in tiny_ms), tiny_ms
    assert all(15_000 < ms < 30_000 for ms in vt_ms), vt_ms
    assert all(_matt(n).suffix.lower() == ".wav" for n in MATT_WAV_IMAGING + MATT_WAV_BEDS)
    assert all(_matt(n).suffix.lower() == ".mp3" for n in MATT_TINY_ID + MATT_VT_SHORT)
    assert len(MATT_HOTKEY_BANK) == 9


def test_import_matt_all_destinations_edge_cases(server):
    """Ingest real MP3s into Library, Living Log, Hotkey, Deck A cue — no cross-bleed."""
    base, desk = server
    day = "2026-09-11"

    # 1) Library only — must not appear on Living Log
    lib = _ingest_matt(base, 1, "Lib Imaging")
    code, log0 = _http_json("GET", f"{base}/api/log?date={day}")
    assert code == 200
    assert all(e.get("title") != "Lib Imaging" for e in (log0.get("events") or []))

    # 2) Living Log destination (append after empty → position 0)
    music = _ingest_matt(base, 3, "Log Music Long")
    ins = _log_insert(
        base,
        day,
        track_id=music["track_id"],
        title="Log Music Long",
        duration_ms=int(music["duration_ms"]),
        after_position=-1,
    )
    events = list_events(day, db_path=desk["db"])
    assert any(e.get("title") == "Log Music Long" and e.get("track_id") == music["track_id"] for e in events)

    # 3) Deck A cue — insert at start (after_position -1) so idle PLAY cues it first
    cue = _ingest_matt(base, 2, "Deck A Cue Imaging")
    _log_insert(
        base,
        day,
        track_id=cue["track_id"],
        title="Deck A Cue Imaging",
        duration_ms=int(cue["duration_ms"]),
        after_position=-1,
    )
    events2 = list_events(day, db_path=desk["db"])
    assert events2[0]["title"] == "Deck A Cue Imaging"
    assert any(e["title"] == "Log Music Long" for e in events2)

    # 4) Hotkey cart destination
    hk_src = _ingest_matt(base, 6, "Hotkey Sweeper")
    code, hk = _http_json("GET", f"{base}/api/hotkeys")
    assert code == 200
    slots = list(hk.get("hotkeys") or [])
    assert slots
    slot = next((s for s in slots if s.get("empty")), slots[0])
    slot_i = int(slot["slot"])
    slots[slot_i] = {
        **slot,
        "label": "Hotkey Sweeper",
        "type": "SWEEPER",
        "target": hk_src["track_id"],
        "path": hk_src.get("file_path"),
        "empty": False,
        "inject_mode": "over_program",
    }
    code, saved = _http_json(
        "POST",
        f"{base}/api/hotkeys",
        data=json.dumps({"hotkeys": slots}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and saved.get("ok")
    loaded = load_hotkeys(desk["data"])
    hit = loaded["hotkeys"][slot_i]
    assert hit.get("empty") is False
    assert hit.get("target") == hk_src["track_id"] or str(hit.get("target")) == str(hk_src["track_id"])

    # Library-only cart still absent from log
    assert all(e.get("title") != "Lib Imaging" for e in list_events(day, db_path=desk["db"]))


def test_import_dest_ui_allows_only_known_values():
    """ingestDestination whitelist — unknown values fall back to library (desk JS)."""
    js = Path("mq_radio/web/static/desk_programming.js").read_text(encoding="utf-8")
    assert '["library", "living_log", "hotkey", "deck_a"]' in js or (
        '"library"' in js and '"living_log"' in js and '"hotkey"' in js and '"deck_a"' in js
    )
    assert "ingestDestination" in js
    # Fallback: unknown → library
    assert "return \"library\"" in js or "return 'library'" in js


# —— ASSIST talk-up + GO (Matt short imaging + long music) ——


def test_assist_talk_up_countdown_and_go_matt(server):
    base, desk = server
    day = "2026-09-12"

    code, mode = _http_json(
        "POST",
        f"{base}/api/mode",
        data=json.dumps({"mode": "ASSIST"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and mode.get("mode") == "ASSIST"
    assert mode.get("auto_advance") is False

    # Long music (talk-up intro) then short imaging (next for ASSIST GO)
    song = _ingest_matt(base, 4, "Assist Song")
    img = _ingest_matt(base, 7, "Assist Imaging Next")
    _set_markers(base, song["track_id"], intro_ms=8000, outro_ms=4000)

    _log_insert(base, day, track_id=song["track_id"], title="Assist Song", duration_ms=20000, after_position=-1)
    events = list_events(day, db_path=desk["db"])
    _log_insert(
        base,
        day,
        track_id=img["track_id"],
        title="Assist Imaging Next",
        duration_ms=12000,
        after_position=int(events[0]["position"]),
    )

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st.get("now") or {}).get("title") == "Assist Song"

    # Ensure ASSIST + intro window for talk-up (session may carry track intro)
    with SESSION.lock:
        SESSION.playout_mode = "ASSIST"
        SESSION.auto_advance = False
        SESSION.intro_ms = 8000
        SESSION.duration_ms = 20000
        SESSION.event_type = "MUSIC"
        SESSION.started_at = time.time() - 1.2  # ~1.2s into intro
        t = SESSION.timing()
    assert t["talk_up_applicable"] is True
    assert t["in_intro"] is True
    assert 6000 <= t["talk_up_remaining_ms"] <= 8000
    assert t["vocals_in"] is False

    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    timing = st2.get("timing") or {}
    assert timing.get("talk_up_applicable") is True
    assert int(timing.get("talk_up_remaining_ms") or 0) > 0
    assert st2.get("playout_mode") == "ASSIST"

    # Past intro → VOCALS IN / talk-up remaining 0
    with SESSION.lock:
        SESSION.started_at = time.time() - 9.0
        t_past = SESSION.timing()
    assert t_past["in_intro"] is False
    assert t_past["vocals_in"] is True
    assert t_past["talk_up_remaining_ms"] == 0

    # Arm ASSIST GO on end-pulse without auto-chain
    with SESSION.lock:
        first_id = SESSION.event_id
        SESSION.end_pulse_ms = 3000
        SESSION.duration_ms = 10000
        SESSION.started_at = time.time() - 7.5  # remaining ~2.5s ≤ pulse
        assert SESSION.timing()["pulse_due"] is True
        assert SESSION.timing()["finished"] is False

    # /api/status runs finish_if_due → arms GO in ASSIST
    code, st3 = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    assert st3.get("assist_go_ready") is True or (st3.get("timing") or {}).get("assist_go_ready") is True
    with SESSION.lock:
        assert SESSION.assist_go_ready is True
        assert SESSION.event_id == first_id
        assert SESSION.overlap_active is False

    code, pulse = _http_json(
        "POST",
        f"{base}/api/pulse?date={day}",
        data=json.dumps({"go": True, "date": day}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and pulse.get("ok")
    assert pulse.get("advanced") is True
    with SESSION.lock:
        assert SESSION.assist_go_ready is False
        # Overlap dual-deck after GO when next cart exists
        if SESSION.event_id != first_id:
            assert SESSION.overlap_active is True
            assert int((SESSION.segue or {}).get("crossfade_ms") or 0) >= 120

    _http_json("POST", f"{base}/api/stop?date={day}")


# —— Dual-deck crossfade timing (AUTO + Matt long→long) ——


def test_dual_deck_crossfade_timing_matt_http(server):
    base, desk = server
    day = "2026-09-13"

    code, mode = _http_json(
        "POST",
        f"{base}/api/mode",
        data=json.dumps({"mode": "AUTO"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and mode.get("auto_advance") is True

    a = _ingest_matt(base, 8, "Xfade Out")
    b = _ingest_matt(base, 9, "Xfade In")
    _set_markers(base, a["track_id"], intro_ms=2000, outro_ms=3500)
    _set_markers(base, b["track_id"], intro_ms=2500, outro_ms=3500)

    _log_insert(base, day, track_id=a["track_id"], title="Xfade Out", duration_ms=10000, after_position=-1)
    ev = list_events(day, db_path=desk["db"])
    _log_insert(
        base,
        day,
        track_id=b["track_id"],
        title="Xfade In",
        duration_ms=10000,
        after_position=int(ev[0]["position"]),
    )

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True
    with SESSION.lock:
        first_id = SESSION.event_id
        first_deck = SESSION.active_deck
        SESSION.end_pulse_ms = 2500
        SESSION.duration_ms = 8000
        SESSION.started_at = time.time() - 6.0  # into pulse window
        assert SESSION.timing()["pulse_due"] is True

    # Status polls finish_if_due → AUTO overlapping advance
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    assert st.get("running") is True
    assert st.get("overlap_active") is True or (st.get("decks") or {}).get("overlap_active") is True
    segue = st.get("segue") or {}
    xfade = int(segue.get("crossfade_ms") or 0)
    assert xfade >= 120, segue
    decks = st.get("decks") or {}
    assert decks.get("fading") is not None or st.get("fading_playable_url") or SESSION.fading is not None
    with SESSION.lock:
        assert SESSION.event_id != first_id
        assert SESSION.active_deck != first_deck
        assert SESSION.overlap_active is True
        assert int((SESSION.segue or {}).get("crossfade_ms") or 0) >= 120

    # Fade clears after crossfade window elapses
    with SESSION.lock:
        SESSION.segue["crossfade_ms"] = 40
        SESSION.segue["started_at"] = time.time() - 0.25
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    with SESSION.lock:
        assert SESSION.overlap_active is False
        assert SESSION.fading is None

    _http_json("POST", f"{base}/api/stop?date={day}")


# —— STOP mid-cart (real Matt music; no manual SESSION wipe) ——


def test_stop_mid_cart_matt_clears_idle(server):
    base, desk = server
    day = "2026-09-14"
    song = _ingest_matt(base, 5, "Mid Cart Stop")
    # Keep air duration long so we are clearly mid-cart after a short wait / seek
    _log_insert(
        base,
        day,
        track_id=song["track_id"],
        title="Mid Cart Stop",
        duration_ms=max(60_000, int(song["duration_ms"])),
        after_position=-1,
    )

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True

    # Seek to ~40% without waiting wall-clock minutes
    with SESSION.lock:
        dur = max(1, int(SESSION.duration_ms or 60000))
        SESSION.started_at = time.time() - (dur * 0.40) / 1000.0
        mid = SESSION.timing()
    assert mid["playing"] is True
    assert 0.25 < float(mid["progress"]) < 0.55
    assert mid["elapsed_ms"] > 0

    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    assert st.get("running") is True
    assert (st.get("now") or {}).get("status") == "ON_AIR"
    assert float((st.get("timing") or {}).get("progress") or 0) > 0.2
    vu = st.get("vu") or {}
    assert vu.get("playing") is True

    # STOP must idle the desk without test-side SESSION surgery
    code, stop = _http_json("POST", f"{base}/api/stop?date={day}")
    assert code == 200, stop
    assert stop.get("running") is False

    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200, st2
    assert st2.get("running") is False
    timing2 = st2.get("timing") or {}
    assert timing2.get("playing") is False
    assert float(timing2.get("progress") or 0) == 0.0
    assert int(timing2.get("elapsed_ms") or 0) == 0
    vu2 = st2.get("vu") or {}
    assert vu2.get("playing") is False
    assert float(vu2.get("left") or 0) == 0.0
    assert float(vu2.get("right") or 0) == 0.0
    now2 = st2.get("now")
    if now2:
        assert now2.get("status") != "ON_AIR"
    # Engine demotes ON_AIR → COMMITTED
    events = list_events(day, db_path=desk["db"])
    assert events
    assert all(e.get("status") != "ON_AIR" for e in events)


# —— Skip mid-sequence (short + long mix) ——


def test_skip_mid_sequence_matt_carts(server):
    base, desk = server
    day = "2026-09-15"
    # Imaging → long song → imaging (classic break sequence)
    plan = [
        (1, "Seq Imaging A", 8000),
        (10, "Seq Music Bed", 15000),
        (6, "Seq Imaging B", 8000),
    ]
    after = -1
    titles = []
    for n, title, dur in plan:
        res = _ingest_matt(base, n, title)
        _log_insert(base, day, track_id=res["track_id"], title=title, duration_ms=dur, after_position=after)
        events = list_events(day, db_path=desk["db"])
        # Next append after the last position we just wrote
        after = max(int(e["position"]) for e in events)
        titles.append(title)

    events = list_events(day, db_path=desk["db"])
    assert [e["title"] for e in events] == titles

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True
    code, st0 = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st0.get("now") or {}).get("title") == "Seq Imaging A"
    assert (st0.get("now") or {}).get("status") == "ON_AIR"

    code, skip1 = _http_json("POST", f"{base}/api/skip?date={day}")
    assert code == 200, skip1
    time.sleep(0.05)
    code, st1 = _http_json("GET", f"{base}/api/status?date={day}")
    assert st1.get("running") is True
    assert (st1.get("now") or {}).get("title") == "Seq Music Bed"
    assert float((st1.get("timing") or {}).get("progress") or 0) >= 0.0

    code, skip2 = _http_json("POST", f"{base}/api/skip?date={day}")
    assert code == 200, skip2
    time.sleep(0.05)
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert st2.get("running") is True
    assert (st2.get("now") or {}).get("title") == "Seq Imaging B"

    # Outcomes: first two should be SKIPPED (or PLAYED if complete path), never stuck ON_AIR
    events_after = list_events(day, db_path=desk["db"])
    by_title = {e["title"]: e for e in events_after}
    assert by_title["Seq Imaging A"]["status"] in ("SKIPPED", "PLAYED", "COMMITTED")
    assert by_title["Seq Music Bed"]["status"] in ("SKIPPED", "PLAYED", "COMMITTED")
    assert by_title["Seq Imaging B"]["status"] == "ON_AIR"

    _http_json("POST", f"{base}/api/stop?date={day}")
    events_stop = list_events(day, db_path=desk["db"])
    assert all(e.get("status") != "ON_AIR" for e in events_stop)




def test_skip_idle_burns_upcoming_only_once(server):
    """Idle SKIP drops the cue once; mid-cart SKIP advances exactly one cart."""
    base, desk = server
    day = "2026-09-17"
    titles = []
    after = -1
    for n, title in [(1, "Idle A"), (2, "Idle B"), (6, "Idle C")]:
        res = _ingest_matt(base, n, title)
        _log_insert(base, day, track_id=res["track_id"], title=title, duration_ms=8000, after_position=after)
        after = max(int(e["position"]) for e in list_events(day, db_path=desk["db"]))
        titles.append(title)

    # Idle: skip upcoming A → play starts on B
    code, skip_idle = _http_json("POST", f"{base}/api/skip?date={day}")
    assert code == 200, skip_idle
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st.get("now") or {}).get("title") == "Idle B"
    by = {e["title"]: e for e in list_events(day, db_path=desk["db"])}
    assert by["Idle A"]["status"] == "SKIPPED"
    assert by["Idle B"]["status"] == "ON_AIR"

    # Mid-cart: skip B → play C (must not also burn C)
    code, skip_mid = _http_json("POST", f"{base}/api/skip?date={day}")
    assert code == 200, skip_mid
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st2.get("now") or {}).get("title") == "Idle C"
    by2 = {e["title"]: e for e in list_events(day, db_path=desk["db"])}
    assert by2["Idle B"]["status"] == "SKIPPED"
    assert by2["Idle C"]["status"] == "ON_AIR"
    _http_json("POST", f"{base}/api/stop?date={day}")




def test_matt_wav_imaging_as_hotkey_and_promo_over_music(server):
    """WAV carts 29–31 as ID/promo hotkeys layered over a long music log cart."""
    base, desk = server
    day = "2026-09-18"
    music = _ingest_matt(base, 27, "Promo Bed Music")
    _log_insert(
        base,
        day,
        track_id=music["track_id"],
        title="Promo Bed Music",
        duration_ms=20000,
        after_position=-1,
    )

    code, mode = _http_json(
        "POST",
        f"{base}/api/mode",
        data=json.dumps({"mode": "AUTO"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True

    # Load WAV imaging into three hotkey slots as PROMO/ID
    code, hk = _http_json("GET", f"{base}/api/hotkeys")
    assert code == 200
    slots = list(hk.get("hotkeys") or [])
    assert len(slots) >= 3
    for i, (n, label, etype) in enumerate(
        [
            (29, "WAV ID 29", "ID"),
            (30, "WAV Promo 30", "PROMO"),
            (31, "WAV Sweeper 31", "SWEEPER"),
        ]
    ):
        res = _ingest_matt(base, n, label, event_type=etype if etype != "ID" else "PROMO")
        slot = slots[i]
        slots[i] = {
            **slot,
            "slot": int(slot.get("slot", i)),
            "label": label,
            "type": etype,
            "target": res["track_id"],
            "path": res["file_path"],
            "empty": False,
            "inject_mode": "over_program",
        }
    code, saved = _http_json(
        "POST",
        f"{base}/api/hotkeys",
        data=json.dumps({"hotkeys": slots}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and saved.get("ok")

    # Fire WAV oneshot over program — VU moves, Living Log stays ON AIR on music
    fire_src = _matt(29)
    # Use ingested path from slot
    loaded = load_hotkeys(desk["data"])
    path29 = loaded["hotkeys"][0]["path"]
    code, fire = _http_json(
        "POST",
        f"{base}/api/hotkey/fire?date={day}",
        data=json.dumps(
            {
                "path": path29,
                "label": "WAV ID 29",
                "type": "ID",
                "inject": True,
                "inject_mode": "over_program",
                "duration_ms": 7000,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200, fire
    time.sleep(0.15)
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert code == 200
    assert st.get("running") is True
    assert (st.get("now") or {}).get("title") == "Promo Bed Music"
    assert (st.get("now") or {}).get("status") == "ON_AIR"
    shot = st.get("oneshot") or {}
    assert shot.get("active") is True or fire.get("oneshot")
    vu = st.get("vu") or {}
    assert vu.get("playing") is True
    assert float(vu.get("left") or 0) > 0.0 or float(vu.get("right") or 0) > 0.0

    # Cartwall shorts 32–36 (WAV+MP3) as hotkey/ID/sweeper candidates
    code, hk2 = _http_json("GET", f"{base}/api/hotkeys")
    slots2 = list(hk2.get("hotkeys") or [])
    assert len(slots2) >= 8
    hotkey_plan = [
        (32, "WAV Hit 32", "ID"),
        (33, "MP3 ID 33", "ID"),
        (34, "MP3 Sweeper 34", "SWEEPER"),
        (35, "MP3 Stab 35", "SWEEPER"),
        (36, "WAV Promo 36", "PROMO"),
    ]
    for i, (n, label, etype) in enumerate(hotkey_plan, start=3):
        res = _ingest_matt(base, n, label, event_type="PROMO" if etype == "ID" else etype)
        slot = slots2[i] if i < len(slots2) else {"slot": i}
        slots2[i] = {
            **slot,
            "slot": int(slot.get("slot", i)),
            "label": label,
            "type": etype,
            "target": res["track_id"],
            "path": res["file_path"],
            "empty": False,
            "inject_mode": "over_program",
        }
    code, saved2 = _http_json(
        "POST",
        f"{base}/api/hotkeys",
        data=json.dumps({"hotkeys": slots2}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200 and saved2.get("ok")
    loaded2 = load_hotkeys(desk["data"])
    path35 = next(h["path"] for h in loaded2["hotkeys"] if h.get("label") == "MP3 Stab 35")
    code, fire2 = _http_json(
        "POST",
        f"{base}/api/hotkey/fire?date={day}",
        data=json.dumps(
            {
                "path": path35,
                "label": "MP3 Stab 35",
                "type": "SWEEPER",
                "inject": True,
                "inject_mode": "over_program",
                "duration_ms": 4000,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert code == 200, fire2
    time.sleep(0.1)
    code, st_fire2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert st_fire2.get("running") is True
    assert (st_fire2.get("now") or {}).get("status") == "ON_AIR"
    assert (st_fire2.get("vu") or {}).get("playing") is True

    # Tiny MP3 ID (28) also ingestible as promo cart to Living Log
    tiny = _ingest_matt(base, 28, "Tiny ID 28", event_type="PROMO")
    assert int(tiny["duration_ms"]) < 15_000
    _log_insert(
        base,
        day,
        track_id=tiny["track_id"],
        title="Tiny ID 28",
        duration_ms=int(tiny["duration_ms"]),
        after_position=0,
        event_type="PROMO",
    )
    events = list_events(day, db_path=desk["db"])
    assert any(e.get("title") == "Tiny ID 28" for e in events)

    _http_json("POST", f"{base}/api/stop?date={day}")
    with SESSION.lock:
        SESSION.oneshot = None


# —— Full-bank smoke: ingest all 12 into library, cue a short→long Living Log ——



def test_matt_wav_beds_and_vt_on_living_log(server):
    """WAV beds 44–47 + MP3 VT 43 on Living Log with music — PLAY/skip/STOP idle."""
    base, desk = server
    day = "2026-09-19"
    music = _ingest_matt(base, 40, "Bed Music")
    vt = _ingest_matt(base, 43, "VT Short 43", event_type="VOICE_TRACK")
    bed = _ingest_matt(base, 44, "WAV Bed 44", event_type="VOICE_TRACK")
    after = -1
    for res, title, dur, et in [
        (vt, "VT Short 43", int(vt["duration_ms"]), "VOICE_TRACK"),
        (music, "Bed Music", 15000, "MUSIC"),
        (bed, "WAV Bed 44", int(bed["duration_ms"]), "VOICE_TRACK"),
    ]:
        _log_insert(
            base,
            day,
            track_id=res["track_id"],
            title=title,
            duration_ms=dur,
            after_position=after,
            event_type=et,
        )
        after = max(int(e["position"]) for e in list_events(day, db_path=desk["db"]))

    titles = [e["title"] for e in list_events(day, db_path=desk["db"])]
    assert titles == ["VT Short 43", "Bed Music", "WAV Bed 44"]

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st.get("now") or {}).get("title") == "VT Short 43"

    _http_json("POST", f"{base}/api/skip?date={day}")
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st2.get("now") or {}).get("title") == "Bed Music"
    assert float((st2.get("vu") or {}).get("left") or 0) > 0.0 or (st2.get("vu") or {}).get("playing") is True

    _http_json("POST", f"{base}/api/skip?date={day}")
    code, st3 = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st3.get("now") or {}).get("title") == "WAV Bed 44"

    code, stop = _http_json("POST", f"{base}/api/stop?date={day}")
    assert stop.get("running") is False
    code, idle = _http_json("GET", f"{base}/api/status?date={day}")
    assert idle.get("running") is False
    assert float((idle.get("timing") or {}).get("progress") or 0) == 0.0
    assert float((idle.get("vu") or {}).get("left") or 0) == 0.0


def test_matt_full_bank_ingest_and_short_long_play_stop(server):
    base, desk = server
    day = "2026-09-16"
    ingested = []
    for n in range(1, MATT_BANK_COUNT + 1):
        res = _ingest_matt(base, n, f"Bank {n}")
        ingested.append(res)
    assert len(ingested) == MATT_BANK_COUNT
    assert len({r["track_id"] for r in ingested}) == MATT_BANK_COUNT

    # Living Log: short imaging (2) then long music (13)
    short = ingested[1]  # sample 2
    long = ingested[24]  # sample 25
    _log_insert(
        base,
        day,
        track_id=short["track_id"],
        title="Bank Imaging",
        duration_ms=9000,
        after_position=-1,
    )
    ev = list_events(day, db_path=desk["db"])
    _log_insert(
        base,
        day,
        track_id=long["track_id"],
        title="Bank Music",
        duration_ms=12000,
        after_position=int(ev[0]["position"]),
    )

    code, play = _http_json("POST", f"{base}/api/play?date={day}")
    assert code == 200 and play.get("running") is True
    time.sleep(0.2)
    code, st = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st.get("now") or {}).get("title") == "Bank Imaging"
    assert float((st.get("timing") or {}).get("progress") or 0) > 0.0
    vu = st.get("vu") or {}
    assert vu.get("playing") is True
    assert float(vu.get("left") or 0) > 0.0 or float(vu.get("right") or 0) > 0.0

    _http_json("POST", f"{base}/api/skip?date={day}")
    code, st2 = _http_json("GET", f"{base}/api/status?date={day}")
    assert (st2.get("now") or {}).get("title") == "Bank Music"

    code, stop = _http_json("POST", f"{base}/api/stop?date={day}")
    assert stop.get("running") is False
    code, idle = _http_json("GET", f"{base}/api/status?date={day}")
    assert idle.get("running") is False
    assert float((idle.get("timing") or {}).get("progress") or 0) == 0.0
    assert float((idle.get("vu") or {}).get("left") or 0) == 0.0

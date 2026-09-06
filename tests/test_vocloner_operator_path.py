"""Vocloner operator path: clipboard/script export → paste → WAV → Import VT folder.

No public API — exports are local .txt + clipboard text only.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.library.ingest import import_vt_inbox
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import generate_log
from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.service import approve_ai_breaks, list_vt
from mq_radio.voice_tracker.vocloner_export import (
    DESK_FLOW_SHORT,
    OPERATOR_STEPS,
    PUBLIC_API,
    build_clipboard_text,
    build_paste_body,
    export_approved_for_date,
    export_script_package,
    export_vt_script,
    library_root_status,
    operator_desk_flow,
    vocloner_export_dir,
)
from mq_radio.web.app import make_handler


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    return db


@pytest.fixture()
def data_dir(tmp_path: Path):
    d = tmp_path / "data"
    d.mkdir()
    return d


def _write_silence_wav(path: Path, seconds: float = 0.3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fr = 44100
    n = int(fr * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fr)
        w.writeframes(b"\x00\x00" * n)


def test_public_api_hard_false():
    assert PUBLIC_API is False
    flow = operator_desk_flow(preferred_model="Matt Warm")
    assert flow["public_api"] is False
    assert flow["preferred_model"] == "Matt Warm"
    assert "paste into Vocloner" in flow["desk_flow"]
    assert len(flow["steps"]) == len(OPERATOR_STEPS)
    assert any("Import VT" in s or "Import" in s for s in flow["steps"])


def test_clipboard_packet_and_paste_body():
    script = "That was Horizon Run on MQ Digital — you're locked in."
    body = build_paste_body(script)
    assert body == script
    packet = build_clipboard_text(
        script,
        meta={"log_event_id": 42, "variation": "back_announce"},
        preferred_model="Studio A",
    )
    assert "PASTE BELOW" in packet
    assert script in packet
    assert "Studio A" in packet
    assert "42" in packet
    assert "No public API" in packet or "no public API" in packet.lower()


def test_export_script_package_writes_txt(data_dir: Path):
    result = export_script_package(
        "Good morning Sydney — MQ Digital.",
        data_dir=data_dir,
        meta={"log_event_id": 7, "variation": "time_check", "log_date": "2099-01-01"},
        preferred_model="Matt",
    )
    assert result["ok"] is True
    assert result["public_api"] is False
    assert result["clipboard_text"].startswith("Good morning")
    txt = Path(result["txt_path"])
    assert txt.is_file()
    raw = txt.read_text(encoding="utf-8")
    assert "Good morning Sydney" in raw
    assert "paste" in raw.lower()
    assert Path(result["sidecar_path"]).is_file()
    assert vocloner_export_dir(data_dir).is_dir()
    assert DESK_FLOW_SHORT in result["desk_flow"]


def test_export_rejects_empty(data_dir: Path):
    bad = export_script_package("   ", data_dir=data_dir)
    assert bad["ok"] is False
    assert "script" in (bad.get("error") or "").lower()


def test_export_approved_for_date(demo_db: Path, data_dir: Path):
    log_date = "2099-09-06"
    generate_log(log_date, db_path=demo_db, force=True, hours=[0, 1])
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    approve_ai_breaks(log_date, db_path=demo_db)
    approved = [
        r
        for r in list_vt(log_date, db_path=demo_db, status="APPROVED")
        if (r.get("script_text") or "").strip()
        and (r.get("variation") or "").lower() != "silence"
    ]
    assert approved, "need at least one approved spoken VT"
    result = export_approved_for_date(
        log_date, db_path=demo_db, data_dir=data_dir, preferred_model="TestVoice"
    )
    assert result["ok"] is True
    assert result["public_api"] is False
    assert result["exported"] >= 1
    assert Path(result["items"][0]["txt_path"]).is_file()
    # Single event export
    one = export_vt_script(
        log_event_id=int(approved[0]["log_event_id"]),
        db_path=demo_db,
        data_dir=data_dir,
        require_approved=True,
    )
    assert one["ok"] is True
    assert one["meta"]["status"] == "APPROVED"


def test_export_require_approved_rejects_draft(demo_db: Path, data_dir: Path):
    log_date = "2099-09-07"
    generate_log(log_date, db_path=demo_db, force=True, hours=[0])
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    drafts = [
        r
        for r in list_vt(log_date, db_path=demo_db, status="DRAFT")
        if (r.get("script_text") or "").strip()
    ]
    assert drafts
    bad = export_vt_script(
        log_event_id=int(drafts[0]["log_event_id"]),
        db_path=demo_db,
        data_dir=data_dir,
        require_approved=True,
    )
    assert bad["ok"] is False
    assert "approve" in (bad.get("error") or "").lower()


def test_import_vt_inbox_tags_vocloner(demo_db: Path, data_dir: Path, tmp_path: Path):
    log_date = "2099-09-08"
    generate_log(log_date, db_path=demo_db, force=True, hours=[0])
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    approve_ai_breaks(log_date, db_path=demo_db)
    target = next(
        r
        for r in list_vt(log_date, db_path=demo_db, status="APPROVED")
        if (r.get("script_text") or "").strip()
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    wav = inbox / "vocloner_break_morning.wav"
    _write_silence_wav(wav, 0.4)
    result = import_vt_inbox(
        db_path=demo_db,
        data_dir=data_dir,
        inbox=inbox,
        attach_event_id=int(target["log_event_id"]),
    )
    assert result["ok"] is True
    assert result["count"] >= 1
    assert result["imported"][0].get("vt_source") == "VOCLONER"
    assert result["attached"]["ok"] is True
    assert result["attached"]["source"] == "VOCLONER"
    conn = get_connection(demo_db)
    row = conn.execute(
        "SELECT source, audio_path FROM vt_scripts WHERE log_event_id=?",
        (int(target["log_event_id"]),),
    ).fetchone()
    conn.close()
    assert row["source"] == "VOCLONER"
    assert row["audio_path"]


def test_library_root_status_empty_hint(tmp_path: Path):
    data = tmp_path / "station"
    data.mkdir()
    st = library_root_status(data)
    assert st["ok"] is True
    assert st["empty"] is True
    assert "empty" in (st.get("empty_hint") or "").lower() or "Import" in (
        st.get("empty_hint") or ""
    )
    assert st["is_default"] is True


def _post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return json.loads(body)
        except Exception:
            return {"ok": False, "error": body, "status": exc.code}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_http_vocloner_export_and_settings(demo_db: Path, tmp_path: Path, monkeypatch):
    import mq_radio.config as cfg
    import mq_radio.web.app as web_app

    data = tmp_path / "station"
    data.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data)
    monkeypatch.setattr(cfg, "DATA_DIR", data)

    log_date = "2099-09-09"
    generate_log(log_date, db_path=demo_db, force=True, hours=[0, 1])
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    approve_ai_breaks(log_date, db_path=demo_db)

    Handler = make_handler(demo_db)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        flow = _get_json(f"{base}/api/vocloner/operator-flow")
        assert flow.get("public_api") is False
        assert "paste into Vocloner" in (flow.get("desk_flow") or "")

        voc = _get_json(f"{base}/api/settings/vocloner")
        assert voc.get("public_api") is False
        assert voc.get("operator_flow", {}).get("public_api") is False

        lib = _get_json(f"{base}/api/settings/library-root")
        assert lib.get("ok") is True
        assert "path" in lib
        assert "operator_message" in lib or "empty_hint" in lib

        inbox = _get_json(f"{base}/api/settings/vt-inbox")
        assert inbox.get("ok") is True
        assert "desk_flow" in inbox

        exported = _post_json(
            f"{base}/api/vocloner/export-script?date={log_date}",
            {"date": log_date, "preferred_model": "HTTPVoice"},
        )
        assert exported.get("ok") is True
        assert exported.get("public_api") is False
        assert exported.get("exported", 0) >= 1
        assert Path(exported["items"][0]["txt_path"]).is_file()

        # Alias path + raw script
        raw = _post_json(
            f"{base}/api/vt/vocloner-export",
            {"script": "Alias path paste test for Vocloner."},
        )
        assert raw.get("ok") is True
        assert raw.get("clipboard_text") == "Alias path paste test for Vocloner."
        assert raw.get("public_api") is False
    finally:
        server.shutdown()

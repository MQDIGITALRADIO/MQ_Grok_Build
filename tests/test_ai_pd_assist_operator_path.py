"""PD assist / overnight operator path: approve → placeholder → Living Log attach.

AI upstairs only — never live song pick. Vocloner remains the real voice path;
placeholder is honest PCM so AUTO can play a cart until Vocloner WAV arrives.
"""

from __future__ import annotations

import wave
from datetime import date
from pathlib import Path

import pytest

from mq_radio.db.connection import get_connection, init_db
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import generate_log
from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.placeholder_render import (
    PLACEHOLDER_SOURCE,
    render_placeholder_vt,
    render_placeholders_for_date,
    run_pd_assist_operator_path,
    write_placeholder_wav,
)
from mq_radio.voice_tracker.service import approve_ai_breaks, list_vt
from mq_radio.web.app import make_handler
from http.server import ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request


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


def test_write_placeholder_wav_is_real_pcm(tmp_path: Path):
    out = tmp_path / "ph.wav"
    result = write_placeholder_wav(out, 4500, script_text="That was Horizon Run on MQ Digital.")
    assert result["ok"]
    assert out.exists()
    assert result["duration_ms"] == 4500
    assert result["source"] == PLACEHOLDER_SOURCE
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 44100
        assert w.getnframes() > 1000


def test_placeholder_rejects_draft(demo_db: Path, data_dir: Path):
    log_date = date.today().isoformat()
    generate_log(log_date, db_path=demo_db, force=True)
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    drafts = list_vt(log_date, db_path=demo_db, status="DRAFT")
    assert drafts
    # Prefer a non-silence draft
    target = next((r for r in drafts if (r.get("script_text") or "").strip()), drafts[0])
    result = render_placeholder_vt(
        int(target["log_event_id"]), db_path=demo_db, data_dir=data_dir
    )
    assert result["ok"] is False
    assert "Approve" in (result.get("error") or "")


def test_approve_then_placeholder_attaches_to_log(demo_db: Path, data_dir: Path):
    log_date = "2099-09-06"
    generate_log(log_date, db_path=demo_db, force=True)
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    ap = approve_ai_breaks(log_date, db_path=demo_db)
    assert ap["approved"] > 0

    approved = [
        r
        for r in list_vt(log_date, db_path=demo_db, status="APPROVED")
        if (r.get("script_text") or "").strip() and (r.get("variation") or "") != "silence"
    ]
    assert approved
    eid = int(approved[0]["log_event_id"])
    result = render_placeholder_vt(eid, db_path=demo_db, data_dir=data_dir)
    assert result["ok"] is True
    assert result.get("skipped") is False
    assert result["source"] == PLACEHOLDER_SOURCE
    assert result["track_id"]
    assert Path(result["absolute_path"]).exists()

    conn = get_connection(demo_db)
    ev = conn.execute("SELECT * FROM log_events WHERE id=?", (eid,)).fetchone()
    vt = conn.execute("SELECT * FROM vt_scripts WHERE log_event_id=?", (eid,)).fetchone()
    tr = conn.execute("SELECT * FROM tracks WHERE id=?", (result["track_id"],)).fetchone()
    conn.close()
    assert ev["track_id"] == result["track_id"]
    assert ev["manual_flag"] == "MANUAL"
    assert ev["event_type"] == "VOICE_TRACK"
    assert "[VT PLACEHOLDER" in (ev["notes"] or "")
    assert vt["source"] == PLACEHOLDER_SOURCE
    assert (vt["audio_path"] or "").strip()
    assert tr is not None
    assert tr["event_type"] == "VOICE_TRACK"


def test_batch_placeholder_and_idempotent_skip(demo_db: Path, data_dir: Path):
    log_date = "2099-09-07"
    generate_log(log_date, db_path=demo_db, force=True, hours=[0, 1, 2])
    generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=False)
    approve_ai_breaks(log_date, db_path=demo_db)
    first = render_placeholders_for_date(log_date, db_path=demo_db, data_dir=data_dir)
    assert first["ok"]
    assert first["rendered"] >= 1
    second = render_placeholders_for_date(log_date, db_path=demo_db, data_dir=data_dir)
    assert second["ok"]
    assert second["rendered"] == 0
    assert second["skipped"] >= first["rendered"]


def test_pd_assist_operator_path_end_to_end(demo_db: Path, data_dir: Path):
    log_date = "2099-09-08"
    generate_log(log_date, db_path=demo_db, force=True, hours=[23, 0, 1])
    result = run_pd_assist_operator_path(
        log_date, db_path=demo_db, data_dir=data_dir, insert_gaps=True
    )
    assert result["ok"] is True
    assert result["ai_upstairs_only"] is True
    assert result["music_live_pick"] is False
    assert result["approve"]["approved"] > 0
    assert result["placeholder_render"]["rendered"] >= 1

    conn = get_connection(demo_db)
    attached = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           JOIN vt_scripts v ON v.log_event_id = e.id
           WHERE d.log_date=? AND e.event_type='VOICE_TRACK'
             AND e.track_id IS NOT NULL AND v.source=?""",
        (log_date, PLACEHOLDER_SOURCE),
    ).fetchone()["c"]
    music = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           WHERE d.log_date=? AND e.event_type='MUSIC' AND e.track_id IS NOT NULL""",
        (log_date,),
    ).fetchone()["c"]
    conn.close()
    assert attached >= 1
    assert music >= 1  # music still from deterministic scheduler


def test_generate_24h_reports_full_hour_coverage(demo_db: Path):
    log_date = "2099-09-09"
    result = generate_log(log_date, db_path=demo_db, force=True)
    assert result["coverage_complete"] is True
    assert result["missing_hours"] == []
    assert result["empty_hours"] == []
    assert sorted(result["hours_covered"]) == list(range(24))
    assert len(result["events_per_hour"]) == 24
    for h in range(24):
        assert int(result["events_per_hour"][str(h)]) > 0


def test_soft_regenerate_preserves_placeholder_vt(demo_db: Path, data_dir: Path):
    log_date = "2099-09-10"
    generate_log(log_date, db_path=demo_db, force=True, hours=[2])
    run_pd_assist_operator_path(
        log_date, db_path=demo_db, data_dir=data_dir, insert_gaps=False
    )
    conn = get_connection(demo_db)
    before = conn.execute(
        """SELECT e.id, e.title, e.track_id, v.audio_path, v.source
           FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           JOIN vt_scripts v ON v.log_event_id = e.id
           WHERE d.log_date=? AND v.source=? AND e.track_id IS NOT NULL
           LIMIT 1""",
        (log_date, PLACEHOLDER_SOURCE),
    ).fetchone()
    conn.close()
    assert before is not None
    title = before["title"]
    track_id = before["track_id"]
    audio = before["audio_path"]

    generate_log(log_date, db_path=demo_db, force=False, hours=[2])
    conn = get_connection(demo_db)
    after = conn.execute(
        """SELECT e.title, e.track_id, e.manual_flag, v.audio_path, v.source
           FROM log_events e
           JOIN daily_logs d ON d.id = e.daily_log_id
           JOIN vt_scripts v ON v.log_event_id = e.id
           WHERE d.log_date=? AND e.title=?""",
        (log_date, title),
    ).fetchone()
    conn.close()
    assert after is not None
    assert after["manual_flag"] == "MANUAL"
    assert after["track_id"] == track_id
    assert after["audio_path"] == audio
    assert after["source"] == PLACEHOLDER_SOURCE


def _post_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
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


def test_http_operator_path_and_placeholder_api(demo_db: Path, tmp_path: Path, monkeypatch):
    # Point DATA_DIR at tmp so placeholders land under the test tree
    import mq_radio.web.app as web_app
    import mq_radio.config as cfg

    data = tmp_path / "station"
    data.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data)
    monkeypatch.setattr(cfg, "DATA_DIR", data)

    log_date = "2099-09-11"
    generate_log(log_date, db_path=demo_db, force=True, hours=[0, 1])

    Handler = make_handler(demo_db)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        op = _post_json(
            f"{base}/api/ai-breaks/operator-path?date={log_date}",
            {"station_name": "MQ Digital", "style": "warm"},
        )
        assert op.get("ok") is True
        assert op.get("ai_upstairs_only") is True
        assert op["placeholder_render"]["rendered"] >= 1

        # Second call should skip already-attached placeholders
        ph = _post_json(
            f"{base}/api/vt/render-placeholder?date={log_date}",
            {"date": log_date},
        )
        assert ph.get("ok") is True
        assert ph.get("rendered") == 0

        # Draft reject path: generate fresh drafts without approve
        generate_ai_breaks(log_date, db_path=demo_db, insert_gaps=True, max_per_hour=1, stride=1)
        drafts = list_vt(log_date, db_path=demo_db, status="DRAFT")
        if drafts:
            bad = _post_json(
                f"{base}/api/vt/render-placeholder?date={log_date}",
                {"event_id": drafts[0]["log_event_id"]},
            )
            assert bad.get("ok") is False
    finally:
        server.shutdown()

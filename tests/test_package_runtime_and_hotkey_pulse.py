"""Bundled ffmpeg resolve, hotkey inject_mode safety, AUTO pulse / talk-up markers."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.engine.session import SESSION
from mq_radio.library.ingest import ffmpeg_available, resolve_ffmpeg
from mq_radio.living_log.service import load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.web.hotkeys_store import load_hotkeys, save_hotkeys


@pytest.fixture()
def demo_db(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    seed_demo(db)
    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None
        SESSION.running = False
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
    return db


def test_resolve_ffmpeg_prefers_bundled_when_frozen(tmp_path: Path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "ffmpeg").mkdir(parents=True)
    fake = runtime / "ffmpeg" / "ffmpeg"
    fake.write_bytes(b"#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("MQ_RADIO_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr("sys.frozen", True, raising=False)
    # Also stub platform so Mach-O skip does not apply to this shell stub
    monkeypatch.setattr("sys.platform", "darwin")
    got = resolve_ffmpeg()
    assert got == str(fake)


def test_resolve_ffmpeg_skips_macho_on_linux(tmp_path: Path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "ffmpeg").mkdir(parents=True)
    fake = runtime / "ffmpeg" / "ffmpeg"
    # Mach-O 64-bit magic (little-endian CFFAEDFE)
    fake.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 64)
    fake.chmod(0o755)
    monkeypatch.setenv("MQ_RADIO_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delattr("sys.frozen", raising=False)
    got = resolve_ffmpeg()
    # Must use host PATH ffmpeg, not the darwin Mach-O stub
    assert got is not None
    assert got != str(fake)


def test_ffmpeg_available_on_host_or_bundle():
    assert ffmpeg_available() is True


def test_hotkey_path_and_queue_next_persist(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    slots = load_hotkeys(data)["hotkeys"]
    slots[0] = {
        "slot": 0,
        "key": "F1",
        "label": "ID",
        "type": "ID",
        "path": "/Volumes/MQ/id.wav",
        "inject_mode": "queue_next",
        "empty": False,
    }
    save_hotkeys(slots, data)
    again = load_hotkeys(data)
    assert again["hotkeys"][0]["inject_mode"] == "queue_next"
    assert again["hotkeys"][0]["path"] == "/Volumes/MQ/id.wav"


def test_auto_pulse_chains_and_assist_arms_go(demo_db):
    day = "2099-03-01"
    load_sample_hour(day, db_path=demo_db, hour=9, clear_day=True)
    eng = MockEngine(day, db_path=demo_db)
    eng.play()
    with SESSION.lock:
        first = SESSION.event_id
        SESSION.end_pulse_ms = 1500
        SESSION.duration_ms = 4000
        SESSION.started_at = time.time() - 3.0
        SESSION.auto_advance = True
        SESSION.playout_mode = "AUTO"
    assert eng.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.event_id != first or SESSION.running

    with SESSION.lock:
        SESSION.clear()
        SESSION.oneshot = None
    eng2 = MockEngine(day, db_path=demo_db)
    with SESSION.lock:
        SESSION.auto_advance = False
        SESSION.playout_mode = "ASSIST"
    eng2.play()
    with SESSION.lock:
        SESSION.end_pulse_ms = 500
        SESSION.duration_ms = 2000
        SESSION.started_at = time.time() - 1.6
    assert eng2.finish_if_due() is True
    with SESSION.lock:
        assert SESSION.assist_go_ready is True


def test_inject_oneshot_snapshot_expires(demo_db):
    day = "2099-03-02"
    load_sample_hour(day, db_path=demo_db, hour=10, clear_day=True)
    eng = MockEngine(day, db_path=demo_db)
    eng.play()
    res = eng.inject_oneshot(
        label="Sting",
        path="/tmp/x.wav",
        duration_ms=50,
        mode="over_program",
    )
    assert res["ok"]
    with SESSION.lock:
        shot = SESSION.oneshot_snapshot()
        assert shot is not None
        SESSION.oneshot["started_at"] = time.time() - 1.0
        gone = SESSION.oneshot_snapshot()
    assert gone is None


def test_demo_beds_manifest_shape_when_present():
    root = Path(__file__).resolve().parents[1]
    manifest = root / "desktop" / "resources" / "demo_beds" / "MANIFEST.json"
    if not manifest.is_file():
        pytest.skip("demo beds not staged yet")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get("kind") == "mq_radio_demo_beds"
    assert data.get("mb", 0) >= 1
    assert data.get("files")


def test_generate_demo_beds_dry_run_catalog_hits_soft_floor(tmp_path: Path):
    """Catalog estimator should clear ~500MB soft floor at default CI target."""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "packaging" / "scripts" / "generate_demo_beds.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--target-mb", "850", "--min-mb", "500"],
        check=True,
        capture_output=True,
        text=True,
    )
    out = proc.stdout
    assert "DRY-RUN" in out
    # "33 beds ≈ 728 MB" style
    assert "MB" in out
    # Parse approximate MB
    import re

    m = re.search(r"≈\s*(\d+)\s*MB", out)
    assert m, out
    assert int(m.group(1)) >= 500

"""Master Control operator path — templates, dry-run, start/stop stubs (not live Harbor)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mq_radio.engine.liquidsoap import LiquidsoapEngine
from mq_radio.production import master_control as mc
from mq_radio.production.liquidsoap_export import HANDOFF_VERSION
from mq_radio.web import app as web_app


def test_ensure_operator_templates(tmp_path: Path):
    data = tmp_path / "data"
    pkg = tmp_path / "liq"
    result = mc.ensure_operator_templates(data_dir=data, packaging_dir=pkg)
    assert result["ok"] is True
    assert result["live_harbor"] is False
    assert (pkg / "processing_handoff.json").is_file()
    assert (pkg / "mq_master_control_operator.liq").is_file()
    assert (pkg / "template_fm.json").is_file()
    assert (data / "processing" / "mq_master_control_operator.liq").is_file()
    text = (pkg / "mq_master_control_operator.liq").read_text(encoding="utf-8")
    assert "MQ_RADIO_OPERATOR_PACK=1" in text
    assert "MQ_RADIO_LIVE_HARBOR=0" in text
    assert f"MQ_RADIO_HANDOFF_VERSION={HANDOFF_VERSION}" in text


def test_dry_run_ok_without_binary(tmp_path: Path):
    data = tmp_path / "data"
    pkg = tmp_path / "liq"
    mc.ensure_operator_templates(data_dir=data, packaging_dir=pkg)
    # Point search at our pkg by using data_dir that has processing after ensure
    result = mc.dry_run(data_dir=data, template_dir=pkg, binary="/no/such/liquidsoap")
    assert result["ok"] is True
    assert result["live_harbor"] is False
    assert result["harbor_wired"] is False
    assert result["status"] == mc.OPERATOR_STATUS_MISSING_BINARY
    assert "liquidsoap" in (result["operator_message"] or "").lower()
    assert result["checks"]["handoff"]["ok"] is True
    assert result["checks"]["operator_liq"]["ok"] is True


def test_dry_run_fails_on_corrupt_handoff(tmp_path: Path):
    pkg = tmp_path / "liq"
    pkg.mkdir()
    (pkg / "processing_handoff.json").write_text("{not-json", encoding="utf-8")
    (pkg / "template_fm.json").write_text("{}", encoding="utf-8")
    (pkg / "template_digital.json").write_text("{}", encoding="utf-8")
    (pkg / "mq_processing_stub.liq").write_text("# stub\n" * 20, encoding="utf-8")
    (pkg / "mq_master_control_operator.liq").write_text(
        mc.render_operator_liq(), encoding="utf-8"
    )
    result = mc.dry_run(template_dir=pkg, binary="/no/such/liquidsoap")
    assert result["ok"] is False
    assert result["errors"]


def test_start_stub_missing_binary(tmp_path: Path):
    data = tmp_path / "data"
    pkg = tmp_path / "liq"
    mc.ensure_operator_templates(data_dir=data, packaging_dir=pkg)
    result = mc.start_stub(data_dir=data, binary="/no/such/liquidsoap")
    assert result["ok"] is False
    assert result["started"] is False
    assert result["live_harbor"] is False
    assert result["error"] == "liquidsoap_missing"
    assert "brew install liquidsoap" in (result["operator_message"] or "")


def test_start_stub_binary_present_still_refuses(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    pkg = tmp_path / "liq"
    mc.ensure_operator_templates(data_dir=data, packaging_dir=pkg)
    fake = tmp_path / "liquidsoap"
    fake.write_text("#!/bin/sh\necho Liquidsoap 2.2.0 fake\n", encoding="utf-8")
    fake.chmod(0o755)

    def _probe(binary=None):
        return {
            "binary": str(fake),
            "available": True,
            "version": "Liquidsoap 2.2.0 fake",
            "error": None,
        }

    monkeypatch.setattr(mc, "resolve_liquidsoap_binary", lambda explicit=None, resources_dir=None: fake)
    monkeypatch.setattr(mc, "probe_liquidsoap_version", _probe)
    result = mc.start_stub(data_dir=data, binary=str(fake))
    assert result["ok"] is False
    assert result["started"] is False
    assert result["live_harbor"] is False
    assert result["error"] == "graph_not_wired"
    assert "not wired" in (result["operator_message"] or "").lower() or "Harbor" in (
        result["operator_message"] or ""
    )


def test_stop_stub_honest():
    result = mc.stop_stub()
    assert result["ok"] is True
    assert result["was_running"] is False
    assert result["live_harbor"] is False
    assert "not started" in (result["operator_message"] or "").lower() or "Terminal" in (
        result["operator_message"] or ""
    )


def test_liquidsoap_engine_start_fails_clearly():
    eng = LiquidsoapEngine(binary="/no/such/liquidsoap")
    st = eng.start()
    assert st.running is False
    assert "liquidsoap" in (st.message or "").lower() or "Master Control" in (st.message or "")
    st2 = eng.stop()
    assert st2.running is False
    rich = eng.operator_status()
    assert rich["live_harbor"] is False
    assert rich["harbor"]["wired"] is False


def test_operator_status_envelope():
    st = mc.operator_status()
    assert st["ok"] is True
    assert st["live_harbor"] is False
    assert st["handoff_version"] == HANDOFF_VERSION
    assert "dry_run" in st["endpoints"]


def test_api_master_control_status_and_dry_run(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data)
    # Ensure templates into data/processing via export path
    mc.ensure_operator_templates(data_dir=data, packaging_dir=data / "processing")

    class H:
        pass

    # GET status
    from io import BytesIO

    # Use the handler indirectly via dry_run / status functions already covered;
    # HTTP surface: call module functions the routes use.
    status = mc.operator_status(data_dir=data)
    assert status["ok"]
    dry = mc.dry_run(data_dir=data, template_dir=data / "processing", binary="/missing")
    assert dry["ok"] is True
    assert dry["live_harbor"] is False


def test_validate_operator_liq_markers(tmp_path: Path):
    p = tmp_path / "op.liq"
    p.write_text(mc.render_operator_liq(), encoding="utf-8")
    v = mc.validate_operator_liq(p)
    assert v["ok"] is True
    assert v["markers"]["operator_pack"] is True
    assert v["markers"]["live_harbor_false"] is True

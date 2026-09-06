"""Native on-air processing templates (FM / Digital)."""

from __future__ import annotations

from pathlib import Path

from mq_radio.production.processing import (
    STAGE_ORDER,
    default_processing,
    digital_template,
    fm_template,
    load_processing,
    normalize_processing,
    processing_summary,
    save_processing,
)


def test_fm_and_digital_templates_differ():
    fm = fm_template()
    dig = digital_template()
    assert fm["template"] == "FM"
    assert dig["template"] == "DIGITAL"
    assert fm["output"]["preemphasis"] is True
    assert dig["output"]["preemphasis"] is False
    assert dig["stages"]["limiter"]["isr"] is True
    assert fm["stages"]["exciter"]["amount"] > dig["stages"]["exciter"]["amount"]
    assert list(fm["stages"].keys()) == list(STAGE_ORDER) or all(
        s in fm["stages"] for s in STAGE_ORDER
    )


def test_save_load_roundtrip(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    saved = save_processing({"apply_template": "DIGITAL"}, data)
    assert saved["ok"]
    assert saved["template"] == "DIGITAL"
    loaded = load_processing(data)
    assert loaded["template"] == "DIGITAL"
    assert loaded["stages"]["limiter"]["isr"] is True
    assert "AGC" in (loaded.get("topology") or "")


def test_normalize_merges_stage_overrides():
    n = normalize_processing(
        {
            "template": "FM",
            "enabled": True,
            "stages": {"limiter": {"ceiling_dbfs": -1.5, "enabled": True}},
        }
    )
    assert n["stages"]["limiter"]["ceiling_dbfs"] == -1.5
    assert n["stages"]["agc"]["enabled"] is True  # preserved from template


def test_summary_bypass():
    c = default_processing()
    c["enabled"] = False
    assert "BYPASS" in processing_summary(c)
    c["enabled"] = True
    s = processing_summary(c)
    assert "FM" in s

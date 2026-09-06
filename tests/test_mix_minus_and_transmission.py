"""Mix-minus subtract status + transmission peak/AGC WAV stub."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from mq_radio.engine.audio_router import AudioRouter, reset_audio_router
from mq_radio.production.liquidsoap_export import (
    HANDOFF_VERSION,
    export_processing_handoff,
    handoff_payload,
    render_liq_snippet,
)
from mq_radio.production.processing import (
    digital_template,
    fm_template,
    normalize_processing,
    processing_summary,
    save_processing,
)
from mq_radio.production.transmission_dsp import process_wav_file, simple_agc


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "mock")
    reset_audio_router()
    yield
    reset_audio_router()


_CATALOGUE = {
    "source": "mock",
    "platform": "linux",
    "backend": "mock",
    "devices": [
        {"id": "blackhole", "label": "BlackHole 2ch", "kind": "output"},
        {"id": "usb", "label": "USB Interface", "kind": "output"},
    ],
    "input_devices": [
        {"id": "none", "label": "None", "kind": "input"},
        {"id": "zoom_return", "label": "Zoom Return (mock)", "kind": "input"},
    ],
}


def _write_tone_wav(path: Path, *, seconds: float = 0.25, freq: float = 440.0, amp: float = 0.25):
    import math

    rate = 48000
    n = int(rate * seconds)
    frames = []
    for i in range(n):
        v = int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))
        frames.append(struct.pack("<h", v))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))


def test_mix_minus_subtract_active_reported():
    router = AudioRouter()
    st = router.apply(
        {"program": "blackhole", "mix_minus": "usb"},
        inputs={"aux_in": "zoom_return"},
        catalogue=_CATALOGUE,
    )
    mm = st["mix_minus"]
    assert mm["paired"] is True
    assert mm["subtract_active"] is False
    assert mm["subtract_mode"] == "pairing_only"
    assert "program_processed" in (mm.get("mac_engine_path") or "")

    st2 = router.set_mix_minus_subtract(
        True,
        mode="program_minus_aux",
        detail="Web Audio live",
    )
    mm2 = st2["mix_minus"]
    assert mm2["subtract_active"] is True
    assert mm2["subtract_mode"] == "program_minus_aux"
    assert "Browser subtract" in (mm2.get("description") or "") or "live" in (
        mm2.get("description") or ""
    ).lower()

    st3 = router.set_mix_minus_subtract(False, mode="pairing_only")
    assert st3["mix_minus"]["subtract_active"] is False


def test_transmission_mode_in_processing(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    saved = save_processing(
        {"apply_template": "FM", "transmission_mode": True},
        data,
    )
    assert saved["ok"]
    assert saved["transmission_mode"] is True
    assert "+TX" in processing_summary(saved)

    n = normalize_processing({"template": "DIGITAL", "transmission_mode": True})
    assert n["transmission_mode"] is True
    assert n["template"] == "DIGITAL"


def test_fm_digital_transmission_flavour_differs():
    fm = fm_template()
    dig = digital_template()
    assert fm["stages"]["agc"]["drive_db"] > dig["stages"]["agc"]["drive_db"]
    assert fm["output"]["preemphasis"] is True
    assert dig["output"]["preemphasis"] is False


def test_wav_peak_agc_stub(tmp_path: Path):
    src = tmp_path / "tone.wav"
    dst = tmp_path / "tone_tx.wav"
    _write_tone_wav(src, amp=0.15)
    result = process_wav_file(src, dst, template="FM", transmission_mode=True)
    assert result["ok"] is True
    assert Path(result["dst"]).is_file()
    assert result["output_peak"] > 0.05
    assert result["template"] == "FM"
    # Digital path should also work and differ in drive metadata
    dst2 = tmp_path / "tone_dig.wav"
    dig = process_wav_file(src, dst2, template="DIGITAL", transmission_mode=True)
    assert dig["ok"]
    assert dig["agc_drive"] != result["agc_drive"]


def test_simple_agc_raises_quiet_signal():
    quiet = [0.01 * ((i % 20) / 20.0) for i in range(4800)]
    out = simple_agc(quiet, target=0.2, drive=3.0, rate=48000)
    assert max(abs(x) for x in out) > max(abs(x) for x in quiet)


def test_liquidsoap_handoff_v3_matches_templates(tmp_path: Path):
    pkg = tmp_path / "liq"
    data = tmp_path / "data"
    data.mkdir()
    result = export_processing_handoff(data_dir=data, packaging_dir=pkg)
    assert result["ok"]
    assert result["version"] == HANDOFF_VERSION
    assert HANDOFF_VERSION >= 3
    payload = handoff_payload()
    assert "transmission_mode" in payload["current"]
    assert "mix_minus_mac" in payload["liquidsoap_hints"]
    assert "python_stub" in payload["liquidsoap_hints"]
    assert "master_control" in payload["liquidsoap_hints"]
    assert "operator_install" in payload
    assert "brew install liquidsoap" in (payload["operator_install"].get("macos_homebrew") or "")
    liq = render_liq_snippet(fm_template())
    assert "Mix-minus" in liq
    assert "program - aux_return" in liq or "mix_minus" in liq
    assert "Master Control" in liq or "brew install liquidsoap" in liq
    assert (pkg / "processing_handoff.json").is_file()
    assert (pkg / "template_fm.json").is_file()
    assert (pkg / "template_digital.json").is_file()

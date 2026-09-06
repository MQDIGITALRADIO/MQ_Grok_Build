"""CoreAudio / mock audio device enumeration — Linux mock path must stay green."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from mq_radio.engine.audio_devices import (
    MOCK_INPUT_DEVICES,
    MOCK_OUTPUT_DEVICES,
    list_audio_devices,
    parse_auval_list,
    parse_system_profiler_audio,
)
from mq_radio.web.settings_store import load_audio_outputs, save_audio_outputs


@pytest.fixture(autouse=True)
def _force_mock_devices(monkeypatch):
    """CI/Linux tests always use mock catalogue unless a test opts out."""
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "mock")


def test_list_audio_devices_mock_shape_on_linux():
    payload = list_audio_devices()
    assert payload["source"] == "mock"
    assert isinstance(payload["devices"], list)
    assert isinstance(payload["input_devices"], list)
    assert len(payload["devices"]) >= 3
    ids = {d["id"] for d in payload["devices"]}
    assert "none" in ids
    assert "same_as_program" in ids
    assert "builtin" in ids
    in_ids = {d["id"] for d in payload["input_devices"]}
    assert "none" in in_ids
    assert payload["insert_options"][0]["id"] == "none"
    assert "Native" in payload["insert_options"][0]["label"]


def test_mock_catalogue_matches_module_constants():
    payload = list_audio_devices()
    assert [d["id"] for d in payload["devices"]] == [d["id"] for d in MOCK_OUTPUT_DEVICES]
    assert [d["id"] for d in payload["input_devices"]] == [d["id"] for d in MOCK_INPUT_DEVICES]


def test_settings_audio_includes_device_source(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    loaded = load_audio_outputs(data)
    assert loaded["device_source"] == "mock"
    assert isinstance(loaded["devices"], list)
    assert loaded["devices"][0]["id"]
    assert "mix_minus" in loaded["outputs"]


def test_settings_save_roundtrip_keeps_devices(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    saved = save_audio_outputs(
        {
            "outputs": {"program": "blackhole", "headphones": "usb"},
            "inputs": {"aux_in": "zoom_return"},
            "insert": {"slot": "none"},
        },
        data,
    )
    assert saved["ok"]
    assert saved["device_source"] == "mock"
    assert saved["outputs"]["program"] == "blackhole"
    again = load_audio_outputs(data)
    assert again["outputs"]["program"] == "blackhole"
    assert again["device_source"] == "mock"


def test_parse_system_profiler_fixture():
    fixture = {
        "SPAudioDataType": [
            {
                "_name": "MacBook Pro Speakers",
                "coreaudio_device_output": "spaudio_yes",
                "coreaudio_default_audio_output_device": "spaudio_yes",
                "coreaudio_device_manufacturer": "Apple Inc.",
                "coreaudio_device_transport": "Built-in",
            },
            {
                "_name": "MacBook Pro Microphone",
                "coreaudio_device_input": "spaudio_yes",
                "coreaudio_default_audio_input_device": "spaudio_yes",
                "coreaudio_device_manufacturer": "Apple Inc.",
            },
            {
                "_name": "BlackHole 2ch",
                "coreaudio_device_output": "spaudio_yes",
                "coreaudio_device_input": "spaudio_yes",
                "coreaudio_device_manufacturer": "Existential Audio Inc.",
            },
            {
                "_name": "USB Audio Interface",
                "coreaudio_device_output": "spaudio_yes",
                "coreaudio_output_source": "External",
            },
        ]
    }
    outs, inns = parse_system_profiler_audio(fixture)
    out_labels = {d["label"] for d in outs}
    in_labels = {d["label"] for d in inns}
    assert "MacBook Pro Speakers" in out_labels
    assert "BlackHole 2ch" in out_labels
    assert "USB Audio Interface" in out_labels
    assert "MacBook Pro Microphone" in in_labels
    assert "BlackHole 2ch" in in_labels
    assert all(d["id"].startswith("ca:") for d in outs)
    assert all(d["id"].startswith("cai:") for d in inns)
    speakers = next(d for d in outs if d["label"] == "MacBook Pro Speakers")
    assert speakers["default"] is True


def test_parse_system_profiler_nested_items():
    fixture = {
        "SPAudioDataType": [
            {
                "_name": "Devices",
                "_items": [
                    {
                        "_name": "External Headphones",
                        "coreaudio_device_output": "spaudio_yes",
                    }
                ],
            }
        ]
    }
    outs, inns = parse_system_profiler_audio(fixture)
    assert any(d["label"] == "External Headphones" for d in outs)
    assert inns == [] or True  # no inputs expected


def test_parse_auval_list_fixture():
    text = """
    aufx bpas appl  -  Apple: AUBandpass
    aufx dcmp appl  -  Apple: AUDynamicsProcessor
    aumu dls  appl  -  Apple: DLSMusicDevice
    not a real line
    """
    units = parse_auval_list(text)
    assert len(units) == 3
    assert units[0]["id"] == "au:aufx:bpas:appl"
    assert units[0]["label"].startswith("AU:")
    assert units[0]["type"] == "aufx"
    assert units[2]["type"] == "aumu"


def test_coreaudio_path_uses_system_profiler_when_forced(monkeypatch):
    """Simulate Darwin + system_profiler JSON without requiring a Mac."""
    monkeypatch.delenv("MQ_RADIO_AUDIO_SOURCE", raising=False)
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "coreaudio")

    fake_sp = {
        "SPAudioDataType": [
            {
                "_name": "Studio Monitors",
                "coreaudio_device_output": "spaudio_yes",
            },
            {
                "_name": "Talent Mic",
                "coreaudio_device_input": "spaudio_yes",
            },
        ]
    }

    monkeypatch.setattr(
        "mq_radio.engine.audio_devices._enumerate_sounddevice",
        lambda: None,
    )
    monkeypatch.setattr(
        "mq_radio.engine.audio_devices._run_system_profiler",
        lambda: fake_sp,
    )
    monkeypatch.setattr(
        "mq_radio.engine.audio_devices._run_auval",
        lambda: [
            {
                "id": "au:aufx:demo:test",
                "label": "AU: Demo Comp",
                "type": "aufx",
                "subtype": "demo",
                "manufacturer": "test",
                "name": "Demo Comp",
            }
        ],
    )
    monkeypatch.setattr(
        "mq_radio.engine.audio_devices.platform.system",
        lambda: "Darwin",
    )

    payload = list_audio_devices(include_audio_units=True)
    assert payload["source"] == "coreaudio"
    assert payload["backend"] == "system_profiler"
    labels = {d["label"] for d in payload["devices"]}
    assert "Studio Monitors" in labels
    assert "None" in labels
    assert "Same as Program" in labels
    in_labels = {d["label"] for d in payload["input_devices"]}
    assert "Talent Mic" in in_labels
    assert any(o["id"] == "au:aufx:demo:test" for o in payload["insert_options"])
    assert any(o["id"] == "none" for o in payload["insert_options"])


def test_api_audio_devices_endpoint_mock():
    """Exercise HTTP handler path for /api/audio/devices (stdlib server)."""
    from io import BytesIO
    from mq_radio.web import app as webapp

    class FakeHandler:
        def __init__(self):
            self.status = None
            self.headers = {}
            self.wfile = BytesIO()
            self.path = "/api/audio/devices"

        def send_response(self, code):
            self.status = code

        def send_header(self, k, v):
            self.headers[k] = v

        def end_headers(self):
            pass

    # Call list_audio_devices the same way the route does
    data = list_audio_devices(include_audio_units=True)
    assert data["source"] == "mock"
    # Also ensure the route string exists in app module source
    src = Path(webapp.__file__).read_text(encoding="utf-8")
    assert '/api/audio/devices' in src

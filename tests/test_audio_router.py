"""Mock / CoreAudio audio output router — Linux mock path must stay green."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from mq_radio.engine.audio_router import (
    AudioRouter,
    apply_audio_route_from_settings,
    get_audio_router,
    reset_audio_router,
)
from mq_radio.web.settings_store import load_audio_outputs, save_audio_outputs


@pytest.fixture(autouse=True)
def _force_mock_and_reset(monkeypatch):
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "mock")
    reset_audio_router()
    yield
    reset_audio_router()


def test_mock_router_records_program_device():
    router = AudioRouter()
    st = router.apply(
        {
            "program": "blackhole",
            "headphones": "usb",
            "aux1": "none",
            "aux2": "aggregate",
        },
        catalogue={
            "source": "mock",
            "platform": "linux",
            "backend": "mock",
            "devices": [
                {"id": "blackhole", "label": "BlackHole 2ch", "kind": "output"},
                {"id": "usb", "label": "USB Interface", "kind": "output"},
                {"id": "aggregate", "label": "Aggregate Device", "kind": "output"},
                {"id": "none", "label": "None", "kind": "output"},
            ],
        },
    )
    assert st["source"] == "mock"
    assert st["backend"] == "mock"
    assert st["active"] is True
    assert st["program"]["device_id"] == "blackhole"
    assert st["program"]["label"] == "BlackHole 2ch"
    assert st["program"]["state"] == "mock"
    assert st["headphones"]["device_id"] == "usb"
    assert st["headphones"]["state"] == "mock"
    assert st["aux1"]["state"] == "off"
    assert st["aux2"]["device_id"] == "aggregate"
    assert st["sink_label"] == "BlackHole 2ch"


def test_same_as_program_resolves_for_secondary_roles():
    router = AudioRouter()
    st = router.apply(
        {"program": "builtin", "headphones": "same_as_program", "aux1": "none"},
        catalogue={
            "source": "mock",
            "devices": [
                {"id": "builtin", "label": "Built-in Output", "kind": "output"},
            ],
        },
    )
    assert st["headphones"]["device_id"] == "builtin"
    assert st["headphones"]["label"] == "Built-in Output"


def test_none_program_is_off_but_mock_still_active():
    router = AudioRouter()
    st = router.apply(
        {"program": "none", "headphones": "none"},
        catalogue={"source": "mock", "devices": [{"id": "none", "label": "None"}]},
    )
    assert st["program"]["state"] == "off"
    assert st["active"] is True  # mock no-op success
    assert st["sink_label"] is None


def test_settings_save_applies_router(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "mock")
    reset_audio_router()
    data = tmp_path / "data"
    data.mkdir()
    saved = save_audio_outputs(
        {"outputs": {"program": "blackhole", "headphones": "usb"}},
        data,
    )
    assert saved["ok"]
    route = saved["audio_route"]
    assert route["program"]["device_id"] == "blackhole"
    assert route["active"] is True
    assert route["backend"] == "mock"
    # Singleton reflects same apply
    assert get_audio_router().status()["program"]["device_id"] == "blackhole"


def test_status_shape_has_program_source_active():
    st = apply_audio_route_from_settings(
        {
            "outputs": {"program": "usb", "headphones": "none"},
            "inputs": {},
            "device_source": "mock",
            "device_platform": "linux",
            "device_backend": "mock",
            "devices": [{"id": "usb", "label": "USB Interface", "kind": "output"}],
        }
    )
    assert "program" in st
    assert "source" in st
    assert "active" in st
    assert st["program"]["device_id"] == "usb"


def test_coreaudio_path_opens_with_fake_sounddevice(monkeypatch):
    """Simulate Darwin + sounddevice OutputStream without real hardware."""
    monkeypatch.delenv("MQ_RADIO_AUDIO_SOURCE", raising=False)
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "coreaudio")
    monkeypatch.setattr(
        "mq_radio.engine.audio_router.platform.system",
        lambda: "Darwin",
    )

    class FakeStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            self.closed = False

        def start(self):
            self.started = True

        def stop(self):
            pass

        def close(self):
            self.closed = True

    fake_devices = [
        {
            "name": "Studio Monitors",
            "max_output_channels": 2,
            "max_input_channels": 0,
            "default_samplerate": 48000.0,
            "hostapi": 0,
        },
        {
            "name": "Talent HP",
            "max_output_channels": 2,
            "max_input_channels": 0,
            "default_samplerate": 48000.0,
            "hostapi": 0,
        },
    ]

    class FakeSD:
        default = type("D", (), {"device": (0, 0)})()

        @staticmethod
        def query_devices(idx=None):
            if idx is None:
                return fake_devices
            return fake_devices[idx]

        @staticmethod
        def query_hostapis():
            return [{"name": "Core Audio"}]

        OutputStream = FakeStream

    import sys

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD)

    router = AudioRouter()
    st = router.apply(
        {
            "program": "ca:studio_monitors",
            "headphones": "ca:talent_hp",
            "aux1": "none",
        },
        catalogue={
            "source": "coreaudio",
            "platform": "darwin",
            "backend": "sounddevice",
            "devices": [
                {
                    "id": "ca:studio_monitors",
                    "label": "Studio Monitors",
                    "kind": "output",
                    "index": 0,
                },
                {
                    "id": "ca:talent_hp",
                    "label": "Talent HP",
                    "kind": "output",
                    "index": 1,
                },
            ],
        },
    )
    assert st["backend"] == "sounddevice"
    assert st["active"] is True
    assert st["program"]["state"] == "open"
    assert st["program"]["index"] == 0
    assert st["headphones"]["state"] == "open"
    assert st["aux1"]["state"] == "off"
    router.close()


def test_load_envelope_includes_audio_route(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    loaded = load_audio_outputs(data)
    assert "audio_route" in loaded
    assert "program" in loaded["audio_route"]

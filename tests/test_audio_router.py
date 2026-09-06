"""Mock / CoreAudio audio output router — Linux mock path must stay green."""

from __future__ import annotations

from pathlib import Path

import pytest

from mq_radio.engine.audio_router import (
    ALL_ROUTE_BUSES,
    PROGRAM_PATH,
    SECONDARY_BUSES,
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


_CATALOGUE = {
    "source": "mock",
    "platform": "linux",
    "backend": "mock",
    "devices": [
        {"id": "blackhole", "label": "BlackHole 2ch", "kind": "output"},
        {"id": "usb", "label": "USB Interface", "kind": "output"},
        {"id": "aggregate", "label": "Aggregate Device", "kind": "output"},
        {"id": "builtin", "label": "Built-in Output", "kind": "output"},
        {"id": "none", "label": "None", "kind": "output"},
        {"id": "same_as_program", "label": "Same as Program", "kind": "output"},
    ],
    "input_devices": [
        {"id": "none", "label": "None", "kind": "input"},
        {"id": "zoom_return", "label": "Zoom Return (mock)", "kind": "input"},
        {"id": "usb_in", "label": "USB Interface In", "kind": "input"},
    ],
}


def test_mock_router_records_program_device():
    router = AudioRouter()
    st = router.apply(
        {
            "program": "blackhole",
            "headphones": "usb",
            "aux1": "none",
            "aux2": "aggregate",
        },
        catalogue=_CATALOGUE,
    )
    assert st["source"] == "mock"
    assert st["backend"] == "mock"
    assert st["active"] is True
    assert st["program"]["device_id"] == "blackhole"
    assert st["program"]["label"] == "BlackHole 2ch"
    assert st["program"]["state"] == "mock"
    assert st["program"]["primary"] is True
    assert st["headphones"]["device_id"] == "usb"
    assert st["headphones"]["state"] == "mock"
    assert st["aux1"]["state"] == "off"
    assert st["aux2"]["device_id"] == "aggregate"
    assert st["sink_label"] == "BlackHole 2ch"
    assert st["primary_bus"] == "program"
    assert "source →" in st["program_path"]


def test_mock_multi_bus_monitor_stream_record():
    """Monitor / Stream / Record are recorded like Headphones/Aux (mock)."""
    router = AudioRouter()
    st = router.apply(
        {
            "program": "blackhole",
            "monitor": "usb",
            "headphones": "none",
            "stream": "same_as_program",
            "record": "aggregate",
            "mix_minus": "usb",
            "aux1": "none",
            "aux2": "none",
        },
        inputs={"aux_in": "zoom_return", "mic": "none"},
        catalogue=_CATALOGUE,
    )
    assert st["monitor"]["device_id"] == "usb"
    assert st["monitor"]["state"] == "mock"
    assert st["monitor"]["label"] == "USB Interface"
    assert st["stream"]["device_id"] == "blackhole"
    assert st["stream"]["state"] == "mock"
    assert st["record"]["device_id"] == "aggregate"
    assert st["record"]["state"] == "mock"
    assert "monitor" in st["buses"]
    assert "stream" in st["buses"]
    assert "record" in st["buses"]
    assert "mix_minus" in st["buses"]
    assert set(ALL_ROUTE_BUSES) >= {
        "program",
        "monitor",
        "mix_minus",
        "stream",
        "record",
        "headphones",
    }
    assert "monitor" in SECONDARY_BUSES
    assert "mix_minus" in SECONDARY_BUSES


def test_mix_minus_pairing_fields():
    """Status mix_minus exposes {out, aux_in, paired}."""
    router = AudioRouter()
    st = router.apply(
        {
            "program": "blackhole",
            "mix_minus": "usb",
            "monitor": "none",
            "headphones": "none",
        },
        inputs={"aux_in": "zoom_return"},
        catalogue=_CATALOGUE,
    )
    mm = st["mix_minus"]
    assert mm["out"] == "usb"
    assert mm["aux_in"] == "zoom_return"
    assert mm["paired"] is True
    assert mm["subtract_active"] is False
    assert mm["subtract_mode"] == "pairing_only"
    assert mm["out_label"] == "USB Interface"
    assert mm["aux_in_label"] == "Zoom Return (mock)"
    assert mm["state"] == "mock"
    assert "mac_engine_path" in mm

    st2 = router.apply(
        {"program": "blackhole", "mix_minus": "usb"},
        inputs={"aux_in": "none"},
        catalogue=_CATALOGUE,
    )
    assert st2["mix_minus"]["out"] == "usb"
    assert st2["mix_minus"]["aux_in"] == "none"
    assert st2["mix_minus"]["paired"] is False

    st3 = router.apply(
        {"program": "blackhole", "mix_minus": "same_as_program"},
        inputs={"aux_in": "usb_in"},
        catalogue=_CATALOGUE,
    )
    assert st3["mix_minus"]["out"] == "blackhole"
    assert st3["mix_minus"]["paired"] is True


def test_au_insert_inactive_warning_when_au_selected():
    """Without AU host, selecting an AU warns au_insert_inactive; native still runs."""
    router = AudioRouter()
    st = router.apply(
        {"program": "blackhole", "headphones": "none"},
        catalogue=_CATALOGUE,
        insert={
            "slot": "au:aufx:dely:appl",
            "label": "AUDelay (Apple)",
            "name": "AUDelay",
            "mode": "au_insert",
        },
    )
    assert st["insert"]["slot"] == "au:aufx:dely:appl"
    assert st["insert"]["name"] == "AUDelay"
    assert st["au_insert"]["warning"] == "au_insert_inactive"
    assert st["au_insert"]["active"] is False
    assert st["au_insert"]["native_runs"] is True
    assert st["au_insert"]["host_available"] is False
    msg = st["au_insert"]["operator_message"] or ""
    assert ("native chain active" in msg) or ("AU insert unavailable" in msg)
    assert st["au_insert"].get("real_au_host") is False
    assert "au_insert" in (st["au_insert"].get("docs") or "")
    assert "au_insert_inactive" in st["warnings"]
    assert st["program_path"] == PROGRAM_PATH
    assert st["active"] is True

    st_none = router.apply(
        {"program": "blackhole"},
        catalogue=_CATALOGUE,
        insert={"slot": "none", "label": "(none) — Native processing"},
    )
    assert st_none["au_insert"]["warning"] is None
    assert "au_insert_inactive" not in st_none["warnings"]

    st_nat = router.apply(
        {"program": "blackhole"},
        catalogue=_CATALOGUE,
        insert={"slot": "native_only", "mode": "force_native"},
    )
    assert st_nat["au_insert"]["warning"] is None
    assert st_nat["insert"]["mode"] == "force_native"


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
    assert st["active"] is True
    assert st["sink_label"] is None


def test_settings_save_applies_router_and_persists_au_name(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "mock")
    reset_audio_router()
    data = tmp_path / "data"
    data.mkdir()
    saved = save_audio_outputs(
        {
            "outputs": {
                "program": "blackhole",
                "headphones": "usb",
                "monitor": "aggregate",
                "mix_minus": "usb",
                "stream": "same_as_program",
                "record": "none",
            },
            "inputs": {"aux_in": "zoom_return"},
            "insert": {
                "slot": "au:aufx:dist:demo",
                "label": "Demo Distortion AU",
                "name": "Demo Distortion AU",
                "mode": "au_insert",
            },
        },
        data,
    )
    assert saved["ok"]
    route = saved["audio_route"]
    assert route["program"]["device_id"] == "blackhole"
    assert route["active"] is True
    assert route["backend"] == "mock"
    assert route["monitor"]["device_id"] == "aggregate"
    assert route["mix_minus"]["out"] == "usb"
    assert route["mix_minus"]["aux_in"] == "zoom_return"
    assert route["mix_minus"]["paired"] is True
    assert route["au_insert"]["warning"] == "au_insert_inactive"
    assert saved["insert"]["name"] == "Demo Distortion AU"
    assert saved["mix_minus"]["out"] == "usb"
    assert saved["mix_minus"]["paired"] is True
    assert get_audio_router().status()["program"]["device_id"] == "blackhole"
    again = load_audio_outputs(data)
    assert again["insert"]["slot"] == "au:aufx:dist:demo"
    assert again["insert"]["name"]


def test_status_shape_has_program_source_active():
    st = apply_audio_route_from_settings(
        {
            "outputs": {"program": "usb", "headphones": "none", "monitor": "usb"},
            "inputs": {"aux_in": "none"},
            "insert": {"slot": "none"},
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
    assert st["monitor"]["device_id"] == "usb"
    assert st["mix_minus"]["paired"] is False
    assert st["au_insert"]["warning"] is None


def test_coreaudio_path_opens_multi_bus_with_fake_sounddevice(monkeypatch):
    """Simulate Darwin + sounddevice OutputStream for Program + secondary buses."""
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
        {
            "name": "Cue Speakers",
            "max_output_channels": 2,
            "max_input_channels": 0,
            "default_samplerate": 48000.0,
            "hostapi": 0,
        },
        {
            "name": "MixMinus Out",
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
            "monitor": "ca:cue_speakers",
            "mix_minus": "ca:mixminus_out",
            "stream": "same_as_program",
            "record": "none",
            "aux1": "none",
        },
        inputs={"aux_in": "zoom_return"},
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
                {
                    "id": "ca:cue_speakers",
                    "label": "Cue Speakers",
                    "kind": "output",
                    "index": 2,
                },
                {
                    "id": "ca:mixminus_out",
                    "label": "MixMinus Out",
                    "kind": "output",
                    "index": 3,
                },
            ],
            "input_devices": [
                {"id": "zoom_return", "label": "Zoom Return", "kind": "input"},
            ],
        },
        insert={"slot": "none"},
    )
    assert st["backend"] == "sounddevice"
    assert st["active"] is True
    assert st["program"]["state"] == "open"
    assert st["program"]["index"] == 0
    assert st["program"]["primary"] is True
    assert st["headphones"]["state"] == "open"
    assert st["monitor"]["state"] == "open"
    assert st["monitor"]["index"] == 2
    assert st["mix_minus"]["out"] == "ca:mixminus_out"
    assert st["mix_minus"]["aux_in"] == "zoom_return"
    assert st["mix_minus"]["paired"] is True
    assert st["mix_minus"]["state"] == "open"
    assert st["stream"]["state"] == "open"
    assert st["stream"]["device_id"] == "ca:studio_monitors"
    assert st["record"]["state"] == "off"
    assert st["aux1"]["state"] == "off"
    router.close()


def test_load_envelope_includes_audio_route(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    loaded = load_audio_outputs(data)
    assert "audio_route" in loaded
    assert "program" in loaded["audio_route"]
    assert "out" in loaded["mix_minus"]
    assert "paired" in loaded["mix_minus"]

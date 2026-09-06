"""Studio routing matrix, AU insert stub, hotkey path-as-is (no library copy)."""

from __future__ import annotations

from pathlib import Path

from mq_radio.web.hotkeys_store import load_hotkeys, save_hotkeys
from mq_radio.web.settings_store import (
    DEFAULT_INSERT,
    DEFAULT_OUTPUTS,
    load_audio_outputs,
    save_audio_outputs,
)


def test_routing_matrix_persists_mixminus_and_insert(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    saved = save_audio_outputs(
        {
            "outputs": {
                **DEFAULT_OUTPUTS,
                "mix_minus": "phone_hybrid",
                "aux1": "blackhole",
            },
            "inputs": {"aux_in": "zoom_return", "mic": "usb_in"},
            "insert": {"slot": "native_only", "mode": "force_native"},
        },
        data,
    )
    assert saved["ok"]
    loaded = load_audio_outputs(data)
    assert loaded["outputs"]["mix_minus"] == "phone_hybrid"
    assert loaded["outputs"]["aux1"] == "blackhole"
    assert loaded["inputs"]["aux_in"] == "zoom_return"
    assert loaded["insert"]["slot"] == "native_only"
    assert loaded["mix_minus"]["paired_input_role"] == "aux_in"
    assert "Program" in loaded["mix_minus"]["description"] or "minus" in loaded["mix_minus"]["description"].lower()


def test_default_insert_is_native_when_empty():
    assert DEFAULT_INSERT["slot"] == "none"
    assert "Native" in DEFAULT_INSERT["label"]


def test_hotkey_stores_absolute_path_without_ingest(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    abs_path = "/Users/matt/Audio/Sweeper_Brand.wav"
    slots = load_hotkeys(data)["hotkeys"]
    slots[2] = {
        "slot": 2,
        "key": "F3",
        "label": "Brand Sweeper",
        "type": "SWEEPER",
        "target": None,
        "path": abs_path,
        "macro": None,
        "empty": False,
    }
    saved = save_hotkeys(slots, data)
    assert saved["ok"]
    again = load_hotkeys(data)
    hit = again["hotkeys"][2]
    assert hit["path"] == abs_path
    assert hit["empty"] is False
    # Ensure we did not invent a library copy path under data/
    assert not str(hit["path"]).startswith(str(data))

def test_default_hotkeys_include_path_and_inject(tmp_path: Path):
    """Fresh defaults must match persisted slot shape (path + inject_mode)."""
    data = tmp_path / "data"
    data.mkdir()
    loaded = load_hotkeys(data)
    assert loaded["source"] == "default"
    hit = loaded["hotkeys"][0]
    assert hit["label"] == "Top of Hour ID"
    assert "path" in hit
    assert hit.get("inject_mode") == "over_program"
    empty = loaded["hotkeys"][8]
    assert empty["empty"] is True
    assert empty.get("inject_mode") == "over_program"


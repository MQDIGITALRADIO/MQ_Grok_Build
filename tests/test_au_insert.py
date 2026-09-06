"""AU insert interface — inactive path (no fake plugin processing)."""

from __future__ import annotations

import platform

import pytest

from mq_radio.engine import au_insert
from mq_radio.engine.au_insert import (
    OPERATOR_INACTIVE_MSG,
    AuHostNotAvailable,
    AuInsertNotSelected,
    host_available,
    is_au_slot,
    load,
    probe_pyobjc,
    status_for_insert,
)
from mq_radio.engine.audio_router import AudioRouter, PROGRAM_PATH


def test_host_available_is_false():
    assert host_available() is False


def test_is_au_slot():
    assert is_au_slot("au:aufx:dely:appl") is True
    assert is_au_slot("none") is False
    assert is_au_slot("native_only") is False
    assert is_au_slot("") is False
    assert is_au_slot(None) is False


def test_load_au_process_raises_not_implemented():
    ins = load("AUDelay", slot="au:aufx:dely:appl")
    assert ins.active is False
    assert ins.host_available is False
    assert ins.warning == "au_insert_inactive"
    assert OPERATOR_INACTIVE_MSG in (ins.operator_message or "")
    with pytest.raises(AuHostNotAvailable) as ei:
        ins.process([0.0, 0.1, -0.1])
    assert "AU host not loaded" in str(ei.value)
    # Also subclass of NotImplementedError for unfinished-interface callers
    assert isinstance(ei.value, NotImplementedError)


def test_load_native_process_raises_not_selected():
    ins = load(slot="none")
    assert ins.warning is None
    with pytest.raises(AuInsertNotSelected):
        ins.process([0.0])
    nat = load(slot="native_only")
    with pytest.raises(AuInsertNotSelected):
        nat.process([0.0])


def test_status_for_insert_inactive():
    st = status_for_insert(
        {
            "slot": "au:aufx:dist:demo",
            "name": "Demo Distortion AU",
            "mode": "au_insert",
        }
    )
    assert st["warning"] == "au_insert_inactive"
    assert st["active"] is False
    assert st["host_available"] is False
    assert st["native_runs"] is True
    assert st["operator_message"] == OPERATOR_INACTIVE_MSG
    assert st["docs"].endswith("au_insert/README.md")
    assert "au_insert" in st["interface"]


def test_status_for_native_no_warning():
    st = status_for_insert({"slot": "none"})
    assert st["warning"] is None
    assert st["operator_message"] is None


def test_probe_pyobjc_safe_on_linux():
    probe = probe_pyobjc()
    assert "platform" in probe
    assert probe["host_available"] is False
    if platform.system().lower() != "darwin":
        assert probe["supports_au_platform"] is False or probe.get("detail")


def test_router_enriches_au_insert_operator_message():
    router = AudioRouter()
    st = router.apply(
        {"program": "blackhole"},
        catalogue={
            "source": "mock",
            "devices": [{"id": "blackhole", "label": "BlackHole 2ch", "kind": "output"}],
        },
        insert={
            "slot": "au:aufx:dely:appl",
            "label": "AUDelay (Apple)",
            "name": "AUDelay",
            "mode": "au_insert",
        },
    )
    au = st["au_insert"]
    assert au["warning"] == "au_insert_inactive"
    assert au["operator_message"] == OPERATOR_INACTIVE_MSG
    assert au["docs"]
    assert au["docs_url"]
    assert au["native_runs"] is True
    assert au["host_available"] is False
    assert au["active"] is False
    assert st["program_path"] == PROGRAM_PATH
    assert "au_insert_inactive" in st["warnings"]


def test_module_exports_on_engine_package():
    assert hasattr(au_insert, "load")
    assert callable(au_insert.load)

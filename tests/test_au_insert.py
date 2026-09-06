"""AU insert interface — inactive path (no fake plugin processing)."""

from __future__ import annotations

import platform

import pytest

from mq_radio.engine import au_insert
from mq_radio.engine.au_insert import (
    OPERATOR_INACTIVE_MSG,
    OPERATOR_NON_MAC_MSG,
    OPERATOR_UNAVAILABLE_MSG,
    AuHostNotAvailable,
    AuInsertNotSelected,
    host_available,
    is_au_slot,
    load,
    probe_pyobjc,
    status_for_insert,
)

def _assert_au_operator_msg(msg: str | None):
    text = msg or ""
    assert OPERATOR_INACTIVE_MSG in text or OPERATOR_NON_MAC_MSG in text or "AU host" in text or "AU insert unavailable" in text
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
    _assert_au_operator_msg(ins.operator_message)
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
    _assert_au_operator_msg(st["operator_message"])
    assert st.get("unavailable_reason") in {"au_host_not_loaded", "au_unavailable_platform"}
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
    _assert_au_operator_msg(au["operator_message"])
    assert au.get("unavailable_reason") in {"au_host_not_loaded", "au_unavailable_platform"}
    assert au.get("real_au_host") is False
    assert au.get("unavailable_message")
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


def test_describe_insert_and_process_buffer():
    from mq_radio.engine.au_insert import (
        describe_insert,
        process_buffer,
        unavailable_reason,
        operator_message_for,
    )

    desc = describe_insert(slot="au:aufx:dely:appl", name="AUDelay")
    assert desc["wants_au"] is True
    assert desc["active"] is False
    assert desc["real_au_host"] is False
    assert desc["native_runs"] is True
    _assert_au_operator_msg(desc["operator_message"])
    assert desc["unavailable_message"] == OPERATOR_UNAVAILABLE_MSG
    assert unavailable_reason(slot="none") is None
    assert unavailable_reason(slot="au:x") in {"au_host_not_loaded", "au_unavailable_platform"}
    assert operator_message_for(slot="none") is None

    ins = load("AUDelay", slot="au:aufx:dely:appl")
    with pytest.raises(AuHostNotAvailable):
        process_buffer(ins, [0.0, 0.5])
    native = load(slot="none")
    with pytest.raises(AuInsertNotSelected):
        process_buffer(native, [0.0])


def test_load_process_scaffold_never_passthrough():
    """Scaffold: process must raise — never return the buffer unchanged."""
    ins = load("Demo", slot="au:aufx:dist:demo")
    buf = [0.1, -0.2, 0.3]
    with pytest.raises(AuHostNotAvailable) as ei:
        out = ins.process(buf)
        # If we somehow got here, fail hard
        assert out is not buf  # pragma: no cover
    assert "not loaded" in str(ei.value).lower() or "AU host" in str(ei.value)


def test_au_insert_api_status_shape(monkeypatch, tmp_path):
    """GET /api/settings/au-insert returns honest unavailable envelope."""
    from mq_radio.web import app as web_app
    from mq_radio.engine.audio_router import reset_audio_router

    monkeypatch.setenv("MQ_RADIO_AUDIO_SOURCE", "mock")
    reset_audio_router()
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path)
    # Apply an AU selection via router
    from mq_radio.engine.audio_router import AudioRouter
    from mq_radio.web.settings_store import save_audio_outputs

    save_audio_outputs(
        {
            "outputs": {"program": "default"},
            "inputs": {"aux_in": "none", "mic": "none"},
            "insert": {
                "slot": "au:aufx:dely:appl",
                "name": "AUDelay",
                "mode": "au_insert",
            },
        },
        tmp_path,
    )
    st = web_app._status_audio_route()
    au = st.get("au_insert") or {}
    assert au.get("warning") == "au_insert_inactive"
    assert au.get("host_available") is False
    assert au.get("real_au_host") is False
    _assert_au_operator_msg(au.get("operator_message"))

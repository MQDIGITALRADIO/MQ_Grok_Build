"""Program-bus Audio Unit insert — architecture interface (not a full AU host).

Documented Program path::

    source → [AU insert if set] → native processing → device

This module defines the **practical** Python-side contract for a future Mac host:

* ``load(name)`` → insert handle
* ``process(buffer)`` → process PCM through the loaded AU

Until a real Audio Unit host exists (Electron native helper, pyobjc render
graph, or similar), ``host_available()`` is **False**, ``process()`` raises
``AuHostNotAvailable``, and the engine keeps the **native** chain running
(see ``audio_router`` → ``au_insert_inactive``).

Do **not** claim DMG-bar AU hosting from this stub. Optional ``pyobjc`` /
AudioToolbox probes are diagnostic only — they never fake plugin DSP.

See also ``desktop/au_insert/README.md`` for the Electron native-addon path.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

# Operator-facing copy (Settings banner + status envelope)
OPERATOR_INACTIVE_MSG = "native chain active — AU host not loaded"
DOCS_RELPATH = "desktop/au_insert/README.md"
DOCS_URL = (
    "https://github.com/MQDIGITALRADIO/MQ_Grok_Build/blob/main/desktop/au_insert/README.md"
)
PROGRAM_PATH = "source → [AU insert if set] → native processing → device"

_NATIVE_SLOTS = frozenset({"none", "native_only", "", "(none)"})


class AuHostNotAvailable(NotImplementedError):
    """Raised when ``process()`` is called without a real AU host.

    Subclasses ``NotImplementedError`` so callers treating the interface as
    unfinished get the familiar signal; never silent passthrough.
    """


class AuInsertNotSelected(ValueError):
    """Raised when ``process()`` is called on a none / native-only handle."""


@runtime_checkable
class AuInsert(Protocol):
    """Insert handle: ``load(name)`` → ``process(buffer)``."""

    name: str
    slot: str
    active: bool

    def process(self, buffer: Any) -> Any:
        """Process interleaved or planar float PCM through the AU.

        Must raise ``AuHostNotAvailable`` until a real host is wired.
        Must **not** silently return ``buffer`` unchanged while claiming
        an AU was applied.
        """
        ...


def is_au_slot(name_or_slot: Optional[str]) -> bool:
    """True when the Settings insert slot requests a real AU (not native)."""
    s = (name_or_slot or "").strip()
    if not s or s in _NATIVE_SLOTS:
        return False
    if s.startswith("au:"):
        return True
    # Any non-native slot id counts as AU-selected (persisted name / auval id)
    return True


def _normalize_name(name: Optional[str]) -> str:
    s = (name or "").strip()
    return s or "none"


def host_available() -> bool:
    """Whether a real AU host can process buffers.

    Always False until an in-process / helper host is implemented.
    Env ``MQ_RADIO_AU_HOST=1`` is reserved for future Mac CI — still False
    here so we never fake hosting via an env flag alone.
    """
    # Explicit refuse-fake: even forced env does not flip this without code.
    _ = (os.environ.get("MQ_RADIO_AU_HOST") or "").strip()
    return False


def platform_supports_au() -> bool:
    """macOS is the only platform where an AU host could eventually load."""
    if platform.system().lower() == "darwin":
        return True
    # Tests may claim Darwin-like probe without a Mac
    val = (os.environ.get("MQ_RADIO_AU_PROBE") or "").strip().lower()
    return val in {"1", "true", "yes", "darwin"}


def probe_pyobjc() -> dict[str, Any]:
    """Best-effort diagnostic: can we import AudioUnit-related pyobjc bindings?

    Never loads a plugin or processes audio. Safe on Linux/CI (reports missing).
    """
    result: dict[str, Any] = {
        "platform": platform.system().lower(),
        "supports_au_platform": platform_supports_au(),
        "pyobjc_core": False,
        "audio_unit_framework": False,
        "detail": None,
        "host_available": False,
    }
    if not platform_supports_au() and platform.system().lower() != "darwin":
        result["detail"] = "non-Mac — AU host not applicable"
        return result
    try:
        import objc  # type: ignore  # noqa: F401

        result["pyobjc_core"] = True
    except ImportError:
        result["detail"] = "pyobjc not installed"
        return result
    # Prefer modern AudioToolbox / AVFAudio; fall back to AudioUnit bridge name
    for mod_name in (
        "AudioUnit",
        "AudioToolbox",
        "AVFAudio",
    ):
        try:
            __import__(mod_name)
            result["audio_unit_framework"] = True
            result["detail"] = f"imported {mod_name} (probe only — no render graph)"
            break
        except ImportError:
            continue
    if result["pyobjc_core"] and not result["audio_unit_framework"]:
        result["detail"] = (
            "pyobjc present but AudioUnit/AudioToolbox/AVFAudio not importable"
        )
    return result


@dataclass
class StubAuInsert:
    """Architecture stub — remembers the selected AU name; never processes.

    ``process()`` always raises ``AuHostNotAvailable`` (or
    ``AuInsertNotSelected`` for none/native slots). Native MQ processing
    continues on the Program path via the browser / engine chain.
    """

    name: str
    slot: str
    active: bool = False
    host_available: bool = False
    warning: Optional[str] = "au_insert_inactive"
    operator_message: str = OPERATOR_INACTIVE_MSG
    docs: str = DOCS_RELPATH
    docs_url: str = DOCS_URL
    chain: str = PROGRAM_PATH
    probe: dict[str, Any] = field(default_factory=dict)

    def process(self, buffer: Any) -> Any:
        if not is_au_slot(self.slot):
            raise AuInsertNotSelected(
                f"No AU selected (slot={self.slot!r}) — native chain only; "
                f"do not call process() on a native-only insert."
            )
        raise AuHostNotAvailable(
            f"AU host not loaded for {self.name!r} (slot={self.slot!r}). "
            f"{OPERATOR_INACTIVE_MSG}. See {DOCS_RELPATH}."
        )

    def status(self) -> dict[str, Any]:
        wants = is_au_slot(self.slot)
        return {
            "slot": self.slot,
            "name": self.name,
            "active": bool(self.active and self.host_available),
            "host_available": False,
            "warning": "au_insert_inactive" if wants else None,
            "native_runs": True,
            "operator_message": OPERATOR_INACTIVE_MSG if wants else None,
            "docs": DOCS_RELPATH,
            "docs_url": DOCS_URL,
            "chain": PROGRAM_PATH,
            "probe": dict(self.probe) if self.probe else probe_pyobjc(),
            "interface": "mq_radio.engine.au_insert",
        }


def load(name: Optional[str] = None, *, slot: Optional[str] = None) -> StubAuInsert:
    """Load an AU insert handle by display name and/or Settings slot id.

    Returns a stub that will **not** process audio until a real host exists.
    On non-Mac platforms the same stub is returned (process raises).
    """
    raw_slot = _normalize_name(slot if slot is not None else name)
    display = _normalize_name(name) if name else raw_slot
    if display in _NATIVE_SLOTS and raw_slot not in _NATIVE_SLOTS:
        display = raw_slot
    # Prefer au:… slot as canonical when both given
    if slot and str(slot).startswith("au:"):
        raw_slot = str(slot).strip()
    wants = is_au_slot(raw_slot)
    probe = probe_pyobjc()
    return StubAuInsert(
        name=display if wants else ("(none)" if raw_slot == "none" else display),
        slot=raw_slot,
        active=False,
        host_available=False,
        warning="au_insert_inactive" if wants else None,
        operator_message=OPERATOR_INACTIVE_MSG if wants else "",
        probe=probe,
    )


def status_for_insert(insert: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build ``audio_route.au_insert``-compatible status from a Settings insert dict."""
    raw = insert if isinstance(insert, dict) else {}
    slot = str(raw.get("slot") or "none").strip() or "none"
    name = str(raw.get("name") or raw.get("label") or slot).strip() or slot
    handle = load(name, slot=slot)
    return handle.status()


__all__ = [
    "AuHostNotAvailable",
    "AuInsertNotSelected",
    "AuInsert",
    "StubAuInsert",
    "OPERATOR_INACTIVE_MSG",
    "DOCS_RELPATH",
    "DOCS_URL",
    "PROGRAM_PATH",
    "is_au_slot",
    "host_available",
    "platform_supports_au",
    "probe_pyobjc",
    "load",
    "status_for_insert",
]

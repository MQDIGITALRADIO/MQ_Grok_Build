"""Audio output routing — Program (primary) + multi-bus → CoreAudio devices.

Settings store device IDs/names via ``audio_devices`` / ``settings_store``.
This module *applies* those choices:

* **macOS (Darwin):** open PortAudio/CoreAudio output streams via optional
  ``sounddevice`` so Program (primary) and best-effort secondary buses
  (Headphones, Aux, Monitor, Mix-minus, Stream, Record) target selected
  hardware. When ``sounddevice`` is missing, route config is still recorded
  and exposed; browser Web Audio uses ``setSinkId`` / AudioContext sink
  matching by device label (Electron/Mac).
* **Linux / CI / web:** mock router — records selections in status, never fails.

Multi-bus (this pass)
---------------------
**Program / On-Air is the primary routed bus** (stream open + browser sink hint
+ default PortAudio output). All other configured output roles open as
secondary best-effort streams when PortAudio resolves a distinct device;
otherwise they stay ``configured`` / ``mock`` / ``unresolved`` stubs.

Mix-minus pairing + subtract
----------------------------
Status exposes ``mix_minus: {out, aux_in, paired, subtract_active, ...}`` —
Mix-minus *output* paired with Aux input (caller/Zoom return). ``paired`` is
true when both sides are set to a real (non-``none``) device.

**Browser On-Air:** when Aux capture is live, Web Audio builds
``mix_minus = program_processed − aux_return`` (invert + sum) and reports
``subtract_active=true`` via ``AudioRouter.set_mix_minus_subtract``.
Without Aux capture, pairing-only behaviour remains (``subtract_active=false``).

**Mac engine path (documented, not fully hosted here):**
``aux_return → invert → sum with program_processed → mix_minus device``.
CoreAudio dual-device PCM subtract is still an engine milestone; browser graph
is the live subtract today.

Program insert chain (AU architecture — not a full AU host)
-------------------------------------------------------------
Documented Program path::

    source → [AU insert if set] → native processing → device

Interface: ``mq_radio.engine.au_insert`` (``load(name)`` → ``process(buffer)``).
Selected AU name/slot persists via Settings ``insert``. Without an AU host,
``process()`` raises ``AuHostNotAvailable``, status warns ``au_insert_inactive``
with operator message *native chain active — AU host not loaded*, and **native
processing still runs**. Electron native-addon path: ``desktop/au_insert/README.md``.
"""

from __future__ import annotations

import os
import platform
import threading
import time
from typing import Any, Optional

from mq_radio.engine.audio_devices import list_audio_devices
from mq_radio.engine import au_insert as au_insert_mod

# Program is primary; everything else is best-effort secondary.
PRIMARY_BUS = "program"
SECONDARY_BUSES = (
    "headphones",
    "aux1",
    "aux2",
    "monitor",
    "mix_minus",
    "stream",
    "record",
)
ALL_ROUTE_BUSES = (PRIMARY_BUS,) + SECONDARY_BUSES

# Insert slots that mean "no AU plugin" — native chain is the Program path.
_NATIVE_INSERT_SLOTS = frozenset({"none", "native_only", ""})

# Documented Program signal path (desk / status / docs)
PROGRAM_PATH = "source → [AU insert if set] → native processing → device"

_SYNTHETIC = frozenset({"none", "same_as_program"})

_lock = threading.RLock()
_singleton: Optional["AudioRouter"] = None


def _force_mock() -> bool:
    val = (os.environ.get("MQ_RADIO_AUDIO_SOURCE") or "").strip().lower()
    return val in {"mock", "force_mock", "0", "false", "no"}


def _want_coreaudio() -> bool:
    if _force_mock():
        return False
    plat = platform.system().lower()
    if plat == "darwin":
        return True
    # Tests may force CoreAudio resolution path without a Mac
    val = (os.environ.get("MQ_RADIO_AUDIO_SOURCE") or "").strip().lower()
    return val in {"coreaudio", "force_coreaudio", "1", "true", "yes"}


def _silence_callback(outdata, frames, time_info, status):  # noqa: ARG001
    """Keepalive callback — zeros so the device stays claimed without noise."""
    outdata.fill(0)


def _resolve_effective_id(role: str, outputs: dict[str, str]) -> str:
    """Map same_as_program → program device; none stays none."""
    raw = str(outputs.get(role) or "none").strip() or "none"
    if raw == "same_as_program":
        return str(outputs.get("program") or "none").strip() or "none"
    return raw


def _label_for_id(device_id: str, catalogue: dict[str, Any]) -> Optional[str]:
    if not device_id or device_id in _SYNTHETIC:
        return None
    for d in catalogue.get("devices") or []:
        if d.get("id") == device_id:
            return str(d.get("label") or "") or None
    # Inputs catalogue (for aux_in labels in mix-minus pairing)
    for d in catalogue.get("input_devices") or []:
        if d.get("id") == device_id:
            return str(d.get("label") or "") or None
    return None


def _is_real_device(device_id: Optional[str]) -> bool:
    d = (device_id or "").strip()
    return bool(d) and d not in _SYNTHETIC and d != "none"


def _normalize_insert(insert: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Persist-friendly insert dict with slot / label / name / mode."""
    raw = insert if isinstance(insert, dict) else {}
    slot = str(raw.get("slot") or "none").strip() or "none"
    label = str(raw.get("label") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not name:
        # Derive display name from label (strip parenthetical notes) or slot
        if label:
            name = label.split("—")[0].split("-")[0].strip() or label
        elif slot.startswith("au:"):
            name = slot
        elif slot == "native_only":
            name = "Native only"
        else:
            name = "(none)"
    mode = str(raw.get("mode") or "").strip()
    if not mode:
        if slot == "native_only":
            mode = "force_native"
        elif slot.startswith("au:") or (
            slot not in _NATIVE_INSERT_SLOTS and slot != "none"
        ):
            mode = "au_insert"
        else:
            mode = "native_when_empty"
    return {
        "slot": slot,
        "label": label or name,
        "name": name,
        "mode": mode,
    }


def _au_insert_status(insert: dict[str, Any], *, host_available: bool = False) -> dict[str, Any]:
    """AU insert architecture status — warn when selected but no host."""
    # Shared module status (docs / operator_message / probe); host flag from router.
    # Router starts from au_insert.host_available(); a future Electron addon may
    # flip ``_au_host_available`` only when a real Program-bus graph is live.
    base = au_insert_mod.status_for_insert(insert)
    slot = insert.get("slot") or base.get("slot") or "none"
    wants_au = au_insert_mod.is_au_slot(str(slot))
    host_ok = bool(host_available)
    active = bool(wants_au and host_ok)
    warning = None
    if wants_au and not host_ok:
        warning = "au_insert_inactive"
    return {
        "slot": slot,
        "name": insert.get("name") or base.get("name"),
        "label": insert.get("label"),
        "mode": insert.get("mode"),
        "active": active,
        "host_available": host_ok,
        "warning": warning,
        "chain": PROGRAM_PATH,
        "native_runs": True,
        "operator_message": (
            au_insert_mod.OPERATOR_INACTIVE_MSG if warning else None
        ),
        "docs": au_insert_mod.DOCS_RELPATH,
        "docs_url": au_insert_mod.DOCS_URL,
        "interface": "mq_radio.engine.au_insert",
        "probe": base.get("probe") or au_insert_mod.probe_pyobjc(),
    }



def _mix_minus_pairing(
    outputs: dict[str, str],
    inputs: dict[str, str],
    bus_state: Optional[dict[str, Any]] = None,
    catalogue: Optional[dict[str, Any]] = None,
    *,
    subtract_active: bool = False,
    subtract_mode: Optional[str] = None,
    subtract_detail: Optional[str] = None,
) -> dict[str, Any]:
    """Mix-minus out ↔ Aux-in pairing + subtract status for desk/API."""
    out = _resolve_effective_id("mix_minus", outputs)
    aux_in = str(inputs.get("aux_in") or "none").strip() or "none"
    paired = _is_real_device(out) and _is_real_device(aux_in)
    cat = catalogue or {}
    bus = bus_state or {}
    mode = subtract_mode or (
        "program_minus_aux" if subtract_active else ("pairing_only" if paired else "idle")
    )
    return {
        "out": out,
        "aux_in": aux_in,
        "paired": paired,
        "subtract_active": bool(subtract_active),
        "subtract_mode": mode,
        "subtract_detail": subtract_detail,
        "out_label": _label_for_id(out, cat) or bus.get("label"),
        "aux_in_label": _label_for_id(aux_in, cat),
        "state": bus.get("state"),
        "index": bus.get("index"),
        "mac_engine_path": (
            "program_processed - aux_in_return → mix_minus device "
            "(CoreAudio PCM subtract still engine milestone; browser Web Audio "
            "implements live subtract when Aux capture succeeds)"
        ),
        "description": (
            "Mix-minus = Program (processed) minus Aux input return — "
            "caller/Zoom hears the show without their own voice. "
            + (
                "Browser subtract graph live (program − aux)."
                if subtract_active
                else (
                    "Paired; waiting for Aux capture / browser graph "
                    "(fallback: pairing-only until subtract_active)."
                    if paired
                    else "Select Mix-minus out + Aux in to pair."
                )
            )
        ),
    }


def _sounddevice_index_for(
    device_id: str,
    label: Optional[str],
    catalogue: dict[str, Any],
) -> Optional[int]:
    """Map Settings id / label → PortAudio device index via sounddevice."""
    if not device_id or device_id in _SYNTHETIC:
        return None

    # Prefer index already on catalogue entry (sounddevice enum backend)
    for d in catalogue.get("devices") or []:
        if d.get("id") == device_id and d.get("index") is not None:
            try:
                return int(d["index"])
            except (TypeError, ValueError):
                pass

    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        return None

    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return None

    ca_index = None
    for i, api in enumerate(hostapis):
        name = str(api.get("name") or "")
        if "core audio" in name.lower() or "coreaudio" in name.lower():
            ca_index = i
            break

    want_label = (label or "").strip().lower()
    # Also derive from slug id: ca:blackhole_2ch → blackhole 2ch heuristics
    slug = (
        device_id.split(":", 1)[-1].replace("_", " ").strip().lower()
        if ":" in device_id
        else device_id.lower()
    )

    candidates: list[tuple[int, int]] = []  # (score, index)
    for idx, dev in enumerate(devices):
        if not isinstance(dev, dict):
            continue
        if int(dev.get("max_output_channels") or 0) <= 0:
            continue
        if ca_index is not None and dev.get("hostapi") != ca_index:
            continue
        name = str(dev.get("name") or "").strip()
        low = name.lower()
        score = 0
        if want_label and low == want_label:
            score = 100
        elif want_label and want_label in low:
            score = 80
        elif slug and low == slug:
            score = 90
        elif slug and slug in low:
            score = 70
        elif device_id.startswith("ca:") and slug and all(
            p in low for p in slug.split() if len(p) > 2
        ):
            score = 60
        if score:
            candidates.append((score, idx))

    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[0], t[1]))
    return candidates[0][1]


class AudioRouter:
    """Applies Settings output map to CoreAudio (Mac) or mock (Linux/CI)."""

    def __init__(self) -> None:
        self._outputs: dict[str, str] = {}
        self._inputs: dict[str, str] = {}
        self._insert: dict[str, Any] = _normalize_insert(None)
        self._bus_state: dict[str, dict[str, Any]] = {}
        self._streams: dict[str, Any] = {}  # role → OutputStream
        self._catalogue: dict[str, Any] = {}
        self._backend: str = "mock"
        self._source: str = "mock"
        self._platform: str = platform.system().lower()
        self._active: bool = False
        self._error: Optional[str] = None
        self._applied_at: Optional[float] = None
        self._note: str = "Router idle — apply Settings to open Program route."
        self._warnings: list[str] = []
        # No AU host until au_insert.host_available() is real (Electron addon / Mac helper)
        self._au_host_available: bool = bool(au_insert_mod.host_available())
        # Browser (or future Mac engine) reports live Program−Aux subtract
        self._mix_minus_subtract_active: bool = False
        self._mix_minus_subtract_mode: Optional[str] = None
        self._mix_minus_subtract_detail: Optional[str] = None

    # ------------------------------------------------------------------ API

    def apply(
        self,
        outputs: Optional[dict[str, str]] = None,
        inputs: Optional[dict[str, str]] = None,
        *,
        catalogue: Optional[dict[str, Any]] = None,
        insert: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Apply routing from Settings maps. Never raises to callers."""
        with _lock:
            try:
                return self._apply_locked(
                    outputs, inputs, catalogue=catalogue, insert=insert
                )
            except Exception as exc:  # pragma: no cover — defensive
                self._error = str(exc)
                self._note = f"Router apply failed: {exc}"
                self._active = False
                return self.status()

    def _apply_locked(
        self,
        outputs: Optional[dict[str, str]],
        inputs: Optional[dict[str, str]],
        *,
        catalogue: Optional[dict[str, Any]],
        insert: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        if outputs is not None:
            self._outputs = {
                k: str(v) for k, v in outputs.items() if isinstance(v, str)
            }
        if inputs is not None:
            self._inputs = {
                k: str(v) for k, v in inputs.items() if isinstance(v, str)
            }
        if insert is not None:
            self._insert = _normalize_insert(insert)

        if catalogue is None:
            try:
                catalogue = list_audio_devices(include_audio_units=False)
            except Exception:
                catalogue = {"source": "mock", "devices": [], "backend": "mock"}
        self._catalogue = catalogue
        self._source = str(catalogue.get("source") or "mock")
        self._platform = str(
            catalogue.get("platform") or platform.system().lower()
        )
        self._error = None
        self._warnings = []

        # Close previous streams before reopening
        self._close_streams_locked()

        want_ca = _want_coreaudio() and not _force_mock()
        sd_ok = False
        if want_ca:
            try:
                import sounddevice as sd  # noqa: F401

                sd_ok = True
            except ImportError:
                sd_ok = False

        if want_ca and sd_ok:
            self._backend = "sounddevice"
            self._open_coreaudio_buses_locked()
        elif want_ca:
            # Darwin without sounddevice — config + browser sink hints only
            self._backend = "config"
            self._record_config_buses_locked(active_hint="configured")
            self._note = (
                "macOS route recorded (sounddevice not installed). "
                "Program bus uses browser setSinkId / AudioContext sink by device label. "
                "Install PortAudio + sounddevice for engine-side CoreAudio streams. "
                "Program is primary; Monitor/Mix-minus/Stream/Record/Headphones/Aux "
                "are config-recorded until streams can open."
            )
            self._active = bool(
                _resolve_effective_id(PRIMARY_BUS, self._outputs) not in _SYNTHETIC
                and _resolve_effective_id(PRIMARY_BUS, self._outputs)
            )
        else:
            self._backend = "mock"
            self._record_config_buses_locked(active_hint="mock")
            self._note = (
                "Mock audio router (Linux/CI/web) — multi-bus selections recorded "
                "in status (Program primary; Monitor/Mix-minus/Stream/Record/"
                "Headphones/Aux secondary); no CoreAudio streams opened."
            )
            self._active = True  # mock is "active" as a no-op success

        # AU insert: without host, warn and keep native running
        au = _au_insert_status(
            self._insert, host_available=self._au_host_available
        )
        if au.get("warning"):
            self._warnings.append(str(au["warning"]))
            if au["warning"] not in (self._note or ""):
                self._note = (
                    (self._note + " ") if self._note else ""
                ) + (
                    f"AU insert {au.get('name') or au.get('slot')!r} selected but "
                    f"host inactive ({au['warning']}) — native processing still runs. "
                    f"Program path: {PROGRAM_PATH}."
                )

        self._applied_at = time.time()
        return self.status()

    def _record_config_buses_locked(self, *, active_hint: str) -> None:
        self._bus_state = {}
        for role in ALL_ROUTE_BUSES:
            eff = _resolve_effective_id(role, self._outputs)
            label = _label_for_id(eff, self._catalogue)
            if eff in _SYNTHETIC or not eff:
                self._bus_state[role] = {
                    "device_id": eff or "none",
                    "label": None,
                    "state": "off",
                    "index": None,
                }
            else:
                self._bus_state[role] = {
                    "device_id": eff,
                    "label": label,
                    "state": active_hint,
                    "index": None,
                }

    def _open_coreaudio_buses_locked(self) -> None:
        import sounddevice as sd  # type: ignore

        self._bus_state = {}
        opened_program = False
        opened_secondary = 0
        notes: list[str] = []

        for role in ALL_ROUTE_BUSES:
            eff = _resolve_effective_id(role, self._outputs)
            label = _label_for_id(eff, self._catalogue)
            if eff in _SYNTHETIC or not eff:
                self._bus_state[role] = {
                    "device_id": eff or "none",
                    "label": None,
                    "state": "off",
                    "index": None,
                }
                continue

            idx = _sounddevice_index_for(eff, label, self._catalogue)
            if idx is None:
                self._bus_state[role] = {
                    "device_id": eff,
                    "label": label,
                    "state": "unresolved",
                    "index": None,
                }
                if role == PRIMARY_BUS:
                    notes.append(f"Program device {eff!r} not found in PortAudio")
                continue

            # Prefer opening Program; secondaries (incl. Monitor/Mix-minus/
            # Stream/Record) are best-effort — same open path as Headphones/Aux
            try:
                info = sd.query_devices(idx)
                channels = min(2, int(info.get("max_output_channels") or 2) or 2)
                rate = int(info.get("default_samplerate") or 48000)
                stream = sd.OutputStream(
                    device=idx,
                    channels=channels,
                    samplerate=rate,
                    dtype="float32",
                    callback=_silence_callback,
                    finished_callback=None,
                )
                stream.start()
                self._streams[role] = stream
                self._bus_state[role] = {
                    "device_id": eff,
                    "label": label or str(info.get("name") or ""),
                    "state": "open",
                    "index": idx,
                    "channels": channels,
                    "samplerate": rate,
                }
                if role == PRIMARY_BUS:
                    opened_program = True
                    # Point Python default output at Program for any future engine PCM
                    try:
                        sd.default.device = (
                            (sd.default.device[0], idx)
                            if isinstance(sd.default.device, (list, tuple))
                            else idx
                        )
                    except Exception:
                        try:
                            sd.default.device = idx
                        except Exception:
                            pass
                else:
                    opened_secondary += 1
            except Exception as exc:
                self._bus_state[role] = {
                    "device_id": eff,
                    "label": label,
                    "state": "error",
                    "index": idx,
                    "error": str(exc),
                }
                if role == PRIMARY_BUS:
                    notes.append(f"Program open failed: {exc}")

        self._active = opened_program or any(
            (self._bus_state.get(r) or {}).get("state") == "open"
            for r in ALL_ROUTE_BUSES
        )
        prog = self._bus_state.get(PRIMARY_BUS) or {}
        if prog.get("state") == "open":
            self._note = (
                f"Program CoreAudio stream open → {prog.get('label') or prog.get('device_id')} "
                f"(index {prog.get('index')}; primary bus). "
                f"Secondary buses opened best-effort ({opened_secondary} open): "
                "Headphones/Aux/Monitor/Mix-minus/Stream/Record when devices resolve. "
                "Browser Program bus also matches sink by label when available. "
                f"Program path: {PROGRAM_PATH}."
            )
        elif notes:
            self._note = "; ".join(notes)
            self._error = notes[0]
        else:
            self._note = (
                "CoreAudio router applied; Program device is none/off. "
                f"Program path: {PROGRAM_PATH}."
            )

    def _close_streams_locked(self) -> None:
        for role, stream in list(self._streams.items()):
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            self._streams.pop(role, None)

    def close(self) -> None:
        with _lock:
            self._close_streams_locked()
            self._active = False
            for role, st in self._bus_state.items():
                if st.get("state") == "open":
                    st["state"] = "closed"

    def set_mix_minus_subtract(
        self,
        active: bool,
        *,
        mode: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record browser/engine mix-minus subtract liveness for status."""
        with _lock:
            self._mix_minus_subtract_active = bool(active)
            self._mix_minus_subtract_mode = mode
            self._mix_minus_subtract_detail = detail
            return self.status()

    def status(self) -> dict[str, Any]:
        """Status envelope for ``/api/status`` → ``audio_route``."""
        with _lock:
            def _bus(role: str) -> dict[str, Any]:
                return self._bus_state.get(role) or {
                    "device_id": self._outputs.get(role, "none"),
                    "label": None,
                    "state": "idle",
                    "index": None,
                }

            prog = _bus(PRIMARY_BUS)
            # Browser sink hint — match MediaDevices by label
            sink_label = prog.get("label")
            if not sink_label:
                sink_label = _label_for_id(
                    _resolve_effective_id(PRIMARY_BUS, self._outputs),
                    self._catalogue,
                )

            insert = _normalize_insert(self._insert)
            au = _au_insert_status(
                insert, host_available=self._au_host_available
            )
            mix = _mix_minus_pairing(
                self._outputs,
                self._inputs,
                bus_state=self._bus_state.get("mix_minus"),
                catalogue=self._catalogue,
                subtract_active=self._mix_minus_subtract_active,
                subtract_mode=self._mix_minus_subtract_mode,
                subtract_detail=self._mix_minus_subtract_detail,
            )

            warnings = list(self._warnings)
            if au.get("warning") and au["warning"] not in warnings:
                warnings.append(au["warning"])

            buses_snapshot = {
                role: self._bus_state.get(role)
                for role in ALL_ROUTE_BUSES
                if self._bus_state.get(role) is not None
            }

            scope = (
                "program primary + multi-bus best-effort "
                "(headphones/aux/monitor/mix_minus/stream/record)"
                if self._backend == "sounddevice"
                else (
                    "program config + browser sink; multi-bus recorded "
                    "(monitor/mix_minus/stream/record/headphones/aux)"
                )
            )

            return {
                "program": {
                    "device_id": prog.get("device_id"),
                    "label": prog.get("label") or sink_label,
                    "state": prog.get("state"),
                    "index": prog.get("index"),
                    "primary": True,
                },
                "headphones": _bus("headphones") if "headphones" in self._bus_state else None,
                "aux1": _bus("aux1") if "aux1" in self._bus_state else None,
                "aux2": _bus("aux2") if "aux2" in self._bus_state else None,
                "monitor": _bus("monitor") if "monitor" in self._bus_state else None,
                "stream": _bus("stream") if "stream" in self._bus_state else None,
                "record": _bus("record") if "record" in self._bus_state else None,
                # Compact pairing contract requested for desk / tests
                "mix_minus": {
                    "out": mix["out"],
                    "aux_in": mix["aux_in"],
                    "paired": mix["paired"],
                    "subtract_active": mix["subtract_active"],
                    "subtract_mode": mix.get("subtract_mode"),
                    "subtract_detail": mix.get("subtract_detail"),
                    # Extra desk context (safe additive fields)
                    "out_label": mix.get("out_label"),
                    "aux_in_label": mix.get("aux_in_label"),
                    "state": mix.get("state"),
                    "index": mix.get("index"),
                    "mac_engine_path": mix.get("mac_engine_path"),
                    "description": mix.get("description"),
                },
                "buses": buses_snapshot,
                "outputs": dict(self._outputs),
                "inputs": dict(self._inputs),
                "insert": insert,
                "au_insert": au,
                "program_path": PROGRAM_PATH,
                "source": self._source,
                "backend": self._backend,
                "platform": self._platform,
                "active": bool(self._active),
                "error": self._error,
                "warnings": warnings,
                "note": self._note,
                "applied_at": self._applied_at,
                "scope": scope,
                "sink_label": sink_label,
                "primary_bus": PRIMARY_BUS,
            }

    def apply_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Apply from ``load_audio_outputs`` / ``save_audio_outputs`` envelope."""
        outputs = (
            settings.get("outputs")
            if isinstance(settings.get("outputs"), dict)
            else {}
        )
        inputs = (
            settings.get("inputs")
            if isinstance(settings.get("inputs"), dict)
            else {}
        )
        insert = (
            settings.get("insert")
            if isinstance(settings.get("insert"), dict)
            else None
        )
        catalogue = {
            "source": settings.get("device_source")
            or settings.get("source")
            or "mock",
            "platform": settings.get("device_platform")
            or platform.system().lower(),
            "backend": settings.get("device_backend"),
            "devices": settings.get("devices") or [],
            "input_devices": settings.get("input_devices") or [],
            "note": settings.get("device_note"),
        }
        return self.apply(outputs, inputs, catalogue=catalogue, insert=insert)


def get_audio_router() -> AudioRouter:
    """Process-wide router singleton."""
    global _singleton
    with _lock:
        if _singleton is None:
            _singleton = AudioRouter()
        return _singleton


def reset_audio_router() -> AudioRouter:
    """Close and replace singleton (tests)."""
    global _singleton
    with _lock:
        if _singleton is not None:
            try:
                _singleton.close()
            except Exception:
                pass
            _singleton = None
        _singleton = AudioRouter()
        return _singleton


def apply_audio_route_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Convenience used by settings save + status."""
    return get_audio_router().apply_from_settings(settings)


__all__ = [
    "AudioRouter",
    "ALL_ROUTE_BUSES",
    "PRIMARY_BUS",
    "SECONDARY_BUSES",
    "PROGRAM_PATH",
    "get_audio_router",
    "reset_audio_router",
    "apply_audio_route_from_settings",
]

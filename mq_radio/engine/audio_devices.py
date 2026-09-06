"""Audio device enumeration for Settings routing.

Mac (Darwin): real CoreAudio device names via ``system_profiler`` (no new deps).
Optional upgrade path: ``sounddevice`` if installed (PortAudio).

Linux / CI / web / non-Mac: mock studio device names for UX continuity.

API shape (also embedded in ``/api/settings/audio``)::

    {
      "source": "coreaudio" | "mock",
      "platform": "darwin" | "linux" | ...,
      "devices": [{"id", "label", "kind", ...}],
      "input_devices": [...],
      "audio_units": [...],          # Mac auval read-only, best-effort
      "insert_options": [...],       # native stubs (+ discovered AUs on Mac)
      "note": "..."
    }

Real CoreAudio *routing* (opening streams to specific devices) and AU *hosting*
remain Mac-later / transmission DSP work — this module is enumeration + config only.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Mock catalogue (Linux / CI / web demo — keep in sync with Settings UX copy)
# ---------------------------------------------------------------------------

MOCK_OUTPUT_DEVICES: list[dict[str, Any]] = [
    {"id": "builtin", "label": "Built-in Output", "kind": "output"},
    {"id": "usb", "label": "USB Interface", "kind": "output"},
    {"id": "aggregate", "label": "Aggregate Device", "kind": "output"},
    {"id": "blackhole", "label": "BlackHole 2ch", "kind": "output"},
    {"id": "zoom_virtual", "label": "ZoomAudioDevice (mock)", "kind": "output"},
    {"id": "phone_hybrid", "label": "Phone Hybrid (mock)", "kind": "output"},
    {"id": "none", "label": "None", "kind": "output"},
    {"id": "same_as_program", "label": "Same as Program", "kind": "output"},
]

MOCK_INPUT_DEVICES: list[dict[str, Any]] = [
    {"id": "none", "label": "None", "kind": "input"},
    {"id": "usb_in", "label": "USB Interface In", "kind": "input"},
    {"id": "builtin_in", "label": "Built-in Mic / Line", "kind": "input"},
    {"id": "zoom_return", "label": "Zoom Return (mock)", "kind": "input"},
    {"id": "phone_return", "label": "Phone Hybrid Return (mock)", "kind": "input"},
    {"id": "aggregate_in", "label": "Aggregate Input", "kind": "input"},
]

NATIVE_INSERT_OPTIONS: list[dict[str, str]] = [
    {"id": "none", "label": "(none) — Native processing"},
    {"id": "native_only", "label": "Native only (force MQ chain)"},
]

_SYNTHETIC_OUTPUT_IDS = frozenset({"none", "same_as_program"})
_SYNTHETIC_INPUT_IDS = frozenset({"none"})

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str, prefix: str = "ca") -> str:
    base = _SLUG_RE.sub("_", (name or "").strip().lower()).strip("_")
    if not base:
        base = "device"
    return f"{prefix}:{base}"


def _force_mock() -> bool:
    """Allow tests / operators to force mock catalogue even on Darwin."""
    val = (os.environ.get("MQ_RADIO_AUDIO_SOURCE") or "").strip().lower()
    return val in {"mock", "force_mock", "0", "false", "no"}


def _force_coreaudio() -> bool:
    """Tests can force CoreAudio path with fixture parsers (still needs Darwin or inject)."""
    val = (os.environ.get("MQ_RADIO_AUDIO_SOURCE") or "").strip().lower()
    return val in {"coreaudio", "force_coreaudio", "1", "true", "yes"}


# ---------------------------------------------------------------------------
# system_profiler (preferred Mac path — zero new dependencies)
# ---------------------------------------------------------------------------

def _truthy_sp(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str):
        return val.lower() in {"spaudio_yes", "yes", "true", "1"}
    return bool(val)


def parse_system_profiler_audio(payload: dict[str, Any] | list[Any]) -> tuple[list[dict], list[dict]]:
    """Parse ``system_profiler SPAudioDataType -json`` into output/input device lists.

    Returns (outputs, inputs) without synthetic none/same_as_program entries.
    """
    items: list[Any]
    if isinstance(payload, dict):
        items = payload.get("SPAudioDataType") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    outputs: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    seen_out: set[str] = set()
    seen_in: set[str] = set()

    for entry in items:
        if not isinstance(entry, dict):
            continue
        # Newer macOS nests devices under an "_items" / "items" list on a root node
        nested = entry.get("_items") or entry.get("items") or entry.get("_children")
        if isinstance(nested, list) and nested and not entry.get("_name"):
            nested_out, nested_in = parse_system_profiler_audio(nested)
            for d in nested_out:
                if d["id"] not in seen_out:
                    seen_out.add(d["id"])
                    outputs.append(d)
            for d in nested_in:
                if d["id"] not in seen_in:
                    seen_in.add(d["id"])
                    inputs.append(d)
            continue
        if isinstance(nested, list):
            # Device group with name + children
            child_out, child_in = parse_system_profiler_audio(nested)
            for d in child_out:
                if d["id"] not in seen_out:
                    seen_out.add(d["id"])
                    outputs.append(d)
            for d in child_in:
                if d["id"] not in seen_in:
                    seen_in.add(d["id"])
                    inputs.append(d)

        name = str(entry.get("_name") or entry.get("name") or "").strip()
        if not name:
            continue

        has_out = (
            _truthy_sp(entry.get("coreaudio_device_output"))
            or "coreaudio_output_source" in entry
            or "coreaudio_default_audio_output_device" in entry
            or entry.get("coreaudio_device_output_channels") is not None
            or entry.get("Output Channels") is not None
        )
        has_in = (
            _truthy_sp(entry.get("coreaudio_device_input"))
            or "coreaudio_input_source" in entry
            or "coreaudio_default_audio_input_device" in entry
            or entry.get("coreaudio_device_input_channels") is not None
            or entry.get("Input Channels") is not None
        )

        # Ambiguous entries with neither flag: treat speakers/output-ish names as out,
        # mic/input-ish as in; otherwise skip (virtual wrappers often duplicate).
        if not has_out and not has_in:
            low = name.lower()
            if any(k in low for k in ("mic", "input", "line in", "return")):
                has_in = True
            elif any(k in low for k in ("speaker", "output", "headphone", "blackhole", "aggregate")):
                has_out = True
            else:
                continue

        manufacturer = str(
            entry.get("coreaudio_device_manufacturer")
            or entry.get("Manufacturer")
            or ""
        ).strip()
        transport = str(
            entry.get("coreaudio_device_transport") or entry.get("Transport") or ""
        ).strip()

        if has_out:
            oid = _slug(name, "ca")
            if oid not in seen_out:
                seen_out.add(oid)
                outputs.append(
                    {
                        "id": oid,
                        "label": name,
                        "kind": "output",
                        "manufacturer": manufacturer or None,
                        "transport": transport or None,
                        "default": _truthy_sp(
                            entry.get("coreaudio_default_audio_output_device")
                        )
                        or str(entry.get("Default Output Device") or "").lower()
                        in {"yes", "true", "1"},
                    }
                )
        if has_in:
            iid = _slug(name, "cai")
            if iid not in seen_in:
                seen_in.add(iid)
                inputs.append(
                    {
                        "id": iid,
                        "label": name,
                        "kind": "input",
                        "manufacturer": manufacturer or None,
                        "transport": transport or None,
                        "default": _truthy_sp(
                            entry.get("coreaudio_default_audio_input_device")
                        )
                        or str(entry.get("Default Input Device") or "").lower()
                        in {"yes", "true", "1"},
                    }
                )

    return outputs, inputs


def _run_system_profiler() -> Optional[dict[str, Any]]:
    bin_path = shutil.which("system_profiler")
    if not bin_path:
        return None
    try:
        proc = subprocess.run(
            [bin_path, "SPAudioDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Optional sounddevice (PortAudio) — richer channel counts when present
# ---------------------------------------------------------------------------

def _enumerate_sounddevice() -> Optional[tuple[list[dict], list[dict]]]:
    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        return None
    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception:
        return None

    # Prefer Core Audio host API when present
    ca_index = None
    for i, api in enumerate(hostapis):
        name = str(api.get("name") or "")
        if "core audio" in name.lower() or "coreaudio" in name.lower():
            ca_index = i
            break

    outputs: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    seen_out: set[str] = set()
    seen_in: set[str] = set()

    for idx, dev in enumerate(devices):
        if not isinstance(dev, dict):
            continue
        if ca_index is not None and dev.get("hostapi") != ca_index:
            continue
        name = str(dev.get("name") or f"Device {idx}").strip()
        max_out = int(dev.get("max_output_channels") or 0)
        max_in = int(dev.get("max_input_channels") or 0)
        if max_out > 0:
            oid = _slug(name, "ca")
            if oid not in seen_out:
                seen_out.add(oid)
                outputs.append(
                    {
                        "id": oid,
                        "label": name,
                        "kind": "output",
                        "channels": max_out,
                        "index": idx,
                        "hostapi": dev.get("hostapi"),
                    }
                )
        if max_in > 0:
            iid = _slug(name, "cai")
            if iid not in seen_in:
                seen_in.add(iid)
                inputs.append(
                    {
                        "id": iid,
                        "label": name,
                        "kind": "input",
                        "channels": max_in,
                        "index": idx,
                        "hostapi": dev.get("hostapi"),
                    }
                )

    if not outputs and not inputs:
        return None
    return outputs, inputs


# ---------------------------------------------------------------------------
# Audio Units (auval) — read-only names for insert dropdown (Mac only)
# ---------------------------------------------------------------------------

_AUVAL_LINE = re.compile(
    # AU type/subtype/manufacturer are four-char codes (may be space-padded, e.g. "dls ")
    r"^\s*([a-zA-Z0-9 ]{4})\s+([a-zA-Z0-9 ]{4})\s+([a-zA-Z0-9 ]{4})\s+-\s+(.+?)\s*$"
)


def parse_auval_list(text: str) -> list[dict[str, str]]:
    """Parse ``auval -a`` stdout into insert-option dicts (id=au:type:subtype:manu)."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        m = _AUVAL_LINE.match(line.strip())
        if not m:
            continue
        type_code, subtype, manu, label = m.groups()
        type_code = type_code.replace(" ", "")
        subtype = subtype.replace(" ", "")
        manu = manu.replace(" ", "")
        # Keep effect-class aufx / aumu etc. — hosting is still Mac-later
        au_id = f"au:{type_code}:{subtype}:{manu}"
        if au_id in seen:
            continue
        seen.add(au_id)
        found.append(
            {
                "id": au_id,
                "label": f"AU: {label.strip()}",
                "type": type_code,
                "subtype": subtype,
                "manufacturer": manu,
                "name": label.strip(),
            }
        )
    return found


def _run_auval() -> list[dict[str, str]]:
    bin_path = shutil.which("auval") or (
        "/usr/bin/auval" if os.path.isfile("/usr/bin/auval") else None
    )
    if not bin_path:
        return []
    try:
        proc = subprocess.run(
            [bin_path, "-a"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    # auval writes to both stdout and stderr depending on version
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return parse_auval_list(text)


def _with_synthetic_outputs(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(devices)
    have = {d["id"] for d in out}
    if "none" not in have:
        out.append({"id": "none", "label": "None", "kind": "output"})
    if "same_as_program" not in have:
        out.append({"id": "same_as_program", "label": "Same as Program", "kind": "output"})
    return out


def _with_synthetic_inputs(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(devices)
    have = {d["id"] for d in out}
    if "none" not in have:
        out.insert(0, {"id": "none", "label": "None", "kind": "input"})
    return out


def _mock_payload(platform_name: str, note: Optional[str] = None) -> dict[str, Any]:
    return {
        "source": "mock",
        "platform": platform_name,
        "devices": [dict(d) for d in MOCK_OUTPUT_DEVICES],
        "input_devices": [dict(d) for d in MOCK_INPUT_DEVICES],
        "audio_units": [],
        "insert_options": [dict(o) for o in NATIVE_INSERT_OPTIONS],
        "note": note
        or (
            "Mock studio devices (Linux/CI/web). "
            "On macOS the engine enumerates real CoreAudio names via system_profiler."
        ),
        "backend": "mock",
    }


def list_audio_devices(*, include_audio_units: bool = True) -> dict[str, Any]:
    """Return device catalogue with ``source`` of ``coreaudio`` or ``mock``.

    Prefer CoreAudio on Darwin unless ``MQ_RADIO_AUDIO_SOURCE=mock``.
    Enumeration backends (in order): optional ``sounddevice``, then
    ``system_profiler SPAudioDataType -json``. Falls back to mock if empty.
    """
    plat = platform.system().lower()  # darwin / linux / windows
    if _force_mock():
        return _mock_payload(plat, note="Forced mock via MQ_RADIO_AUDIO_SOURCE.")

    want_mac = plat == "darwin" or _force_coreaudio()
    if not want_mac:
        return _mock_payload(plat)

    outputs: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    backend = "none"

    sd_result = _enumerate_sounddevice()
    if sd_result:
        outputs, inputs = sd_result
        backend = "sounddevice"

    if not outputs and not inputs:
        sp = _run_system_profiler()
        if sp is not None:
            outputs, inputs = parse_system_profiler_audio(sp)
            backend = "system_profiler"

    if not outputs and not inputs:
        return _mock_payload(
            plat,
            note=(
                "macOS detected but CoreAudio enumeration returned no devices; "
                "using mock catalogue. Check system_profiler / PortAudio."
            ),
        )

    audio_units: list[dict[str, str]] = []
    if include_audio_units:
        try:
            audio_units = _run_auval()
        except Exception:
            audio_units = []

    # Cap AU list in the insert dropdown (keep desk usable); full list still returned
    insert_options = [dict(o) for o in NATIVE_INSERT_OPTIONS]
    for au in audio_units:
        # Prefer effect units (aufx) for Program insert; still include others after
        if au.get("type") == "aufx":
            insert_options.append({"id": au["id"], "label": au["label"]})
    for au in audio_units:
        if au.get("type") != "aufx":
            insert_options.append({"id": au["id"], "label": au["label"]})
    # Soft cap so Settings select stays navigable
    if len(insert_options) > 80:
        insert_options = insert_options[:80]

    return {
        "source": "coreaudio",
        "platform": plat,
        "devices": _with_synthetic_outputs(outputs),
        "input_devices": _with_synthetic_inputs(inputs),
        "audio_units": audio_units,
        "insert_options": insert_options,
        "note": (
            "Real CoreAudio device names from the Mac engine "
            f"(via {backend}). Routing to these devices and AU hosting "
            "are still Mac-later / transmission DSP — Settings stores the choice."
        ),
        "backend": backend,
    }


__all__ = [
    "MOCK_OUTPUT_DEVICES",
    "MOCK_INPUT_DEVICES",
    "NATIVE_INSERT_OPTIONS",
    "list_audio_devices",
    "parse_system_profiler_audio",
    "parse_auval_list",
]

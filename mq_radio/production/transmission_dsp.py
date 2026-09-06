"""Server-side transmission-path peak/AGC stub for exported WAV paths.

Not a full Optimod / Liquidsoap chain — a honest, audible peak-normalise +
simple AGC applied to PCM WAV so operators can preview transmission flavour
offline. Browser On-Air remains the live Program processor; Liquidsoap handoff
JSON/liq documents the Mac/engine path.

Usage:
    from mq_radio.production.transmission_dsp import process_wav_file
    result = process_wav_file(src, dst, template="FM")
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any, Optional, Union

from mq_radio.production.processing import (
    digital_template,
    fm_template,
    normalize_processing,
)

PathLike = Union[str, Path]


def _chain_for(template: Optional[str] = None, chain: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if chain and isinstance(chain, dict):
        return normalize_processing(chain)
    name = str(template or "FM").upper()
    if name == "DIGITAL":
        return digital_template()
    return fm_template()


def _read_wav_mono_float(path: Path) -> tuple[list[float], int, int, int]:
    """Return (samples float -1..1 interleaved or mono), rate, channels, sampwidth."""
    with wave.open(str(path), "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if sw == 2:
        fmt = "<" + "h" * (len(raw) // 2)
        ints = struct.unpack(fmt, raw)
        scale = 32768.0
        samples = [max(-1.0, min(1.0, i / scale)) for i in ints]
    elif sw == 1:
        ints = list(raw)
        samples = [(b - 128) / 128.0 for b in ints]
    elif sw == 3:
        # 24-bit little-endian packed
        samples = []
        for i in range(0, len(raw) - 2, 3):
            b0, b1, b2 = raw[i], raw[i + 1], raw[i + 2]
            val = b0 | (b1 << 8) | (b2 << 16)
            if val & 0x800000:
                val -= 0x1000000
            samples.append(max(-1.0, min(1.0, val / 8388608.0)))
    elif sw == 4:
        fmt = "<" + "i" * (len(raw) // 4)
        ints = struct.unpack(fmt, raw)
        samples = [max(-1.0, min(1.0, i / 2147483648.0)) for i in ints]
    else:
        raise ValueError(f"unsupported sample width {sw}")
    return samples, rate, nch, sw


def _write_wav_float(path: Path, samples: list[float], rate: int, nch: int, sw: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sw != 2:
        sw = 2  # always write 16-bit PCM for stub predictability
    clamped = [max(-1.0, min(1.0, s)) for s in samples]
    ints = [int(round(s * 32767.0)) for s in clamped]
    raw = struct.pack("<" + "h" * len(ints), *ints)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(raw)


def peak_normalize(samples: list[float], ceiling: float = 0.89) -> tuple[list[float], float]:
    """Scale so peak abs == ceiling. Returns (out, applied_gain)."""
    peak = max((abs(s) for s in samples), default=0.0)
    if peak < 1e-9:
        return list(samples), 1.0
    gain = ceiling / peak
    return [s * gain for s in samples], gain


def simple_agc(
    samples: list[float],
    *,
    target: float = 0.18,
    drive: float = 2.5,
    attack: float = 0.015,
    release: float = 0.25,
    rate: int = 48000,
) -> list[float]:
    """Single-band envelope follower AGC (audible, not broadcast-grade)."""
    if not samples:
        return []
    # Convert time constants to per-sample coefficients
    atk = math.exp(-1.0 / max(1.0, attack * rate))
    rel = math.exp(-1.0 / max(1.0, release * rate))
    env = 0.0
    out: list[float] = []
    # drive maps dB-ish into makeup aggressiveness
    makeup = 1.0 + max(0.0, drive) * 0.12
    tgt = max(0.02, min(0.5, target))
    for s in samples:
        a = abs(s)
        if a > env:
            env = atk * env + (1.0 - atk) * a
        else:
            env = rel * env + (1.0 - rel) * a
        if env < 1e-6:
            g = makeup
        else:
            # Soft toward target RMS-ish level
            g = (tgt / env) * makeup
            g = max(0.15, min(6.0, g))
        out.append(max(-1.0, min(1.0, s * g)))
    return out


def apply_transmission_stub(
    samples: list[float],
    *,
    rate: int,
    chain: dict[str, Any],
) -> dict[str, Any]:
    """Apply peak + AGC stub shaped by FM/Digital template params."""
    stages = chain.get("stages") or {}
    agc = stages.get("agc") or {}
    lim = stages.get("limiter") or {}
    tmpl = str(chain.get("template") or "FM").upper()
    transmission = bool(chain.get("transmission_mode"))

    # Template flavour — FM denser/louder; Digital cleaner ceiling
    if tmpl == "DIGITAL":
        ceiling_db = float(lim.get("ceiling_dbfs") or -1.0)
        if transmission:
            ceiling_db = min(ceiling_db, -1.5)
        ceiling = 10 ** (ceiling_db / 20.0)
        target = 0.14
        drive = float(agc.get("drive_db") or 5.0) * (1.35 if transmission else 1.0)
        attack = max(0.01, float(agc.get("attack_ms") or 50) / 1000.0)
        release = max(0.08, float(agc.get("release_ms") or 1400) / 1000.0)
    else:
        ceiling_db = float(lim.get("ceiling_dbfs") or -1.0)
        if transmission:
            ceiling_db = max(ceiling_db, -0.8)  # denser FM push toward ceiling
        ceiling = 10 ** (ceiling_db / 20.0) * (0.95 if not transmission else 0.98)
        target = 0.22 if transmission else 0.18
        drive = float(agc.get("drive_db") or 7.0) * (1.55 if transmission else 1.15)
        attack = max(0.008, float(agc.get("attack_ms") or 50) / 1000.0 * 0.85)
        release = max(0.05, float(agc.get("release_ms") or 900) / 1000.0 * 0.75)

    worked = simple_agc(
        samples,
        target=target,
        drive=drive,
        attack=attack,
        release=release,
        rate=rate,
    )
    worked, peak_gain = peak_normalize(worked, ceiling=max(0.05, min(0.99, ceiling)))
    return {
        "samples": worked,
        "peak_gain": peak_gain,
        "template": tmpl,
        "transmission_mode": transmission,
        "ceiling": ceiling,
        "agc_target": target,
        "agc_drive": drive,
    }


def process_wav_file(
    src: PathLike,
    dst: Optional[PathLike] = None,
    *,
    template: Optional[str] = None,
    chain: Optional[dict[str, Any]] = None,
    transmission_mode: Optional[bool] = None,
) -> dict[str, Any]:
    """Read WAV → peak/AGC stub → write WAV. Returns metrics + paths."""
    src_path = Path(src)
    if not src_path.is_file():
        return {"ok": False, "error": f"missing source: {src_path}"}
    proc = _chain_for(template, chain)
    if transmission_mode is not None:
        proc["transmission_mode"] = bool(transmission_mode)
    elif "transmission_mode" not in proc:
        proc["transmission_mode"] = True  # this API is the transmission stub

    try:
        samples, rate, nch, sw = _read_wav_mono_float(src_path)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "src": str(src_path)}

    result = apply_transmission_stub(samples, rate=rate, chain=proc)
    out_path = Path(dst) if dst else src_path.with_name(src_path.stem + "_tx.wav")
    try:
        _write_wav_float(out_path, result["samples"], rate, nch, sw)
    except Exception as exc:
        return {"ok": False, "error": f"write failed: {exc}", "src": str(src_path)}

    # Peak of output for honesty
    out_peak = max((abs(s) for s in result["samples"]), default=0.0)
    return {
        "ok": True,
        "src": str(src_path),
        "dst": str(out_path),
        "template": result["template"],
        "transmission_mode": result["transmission_mode"],
        "samplerate": rate,
        "channels": nch,
        "frames": len(result["samples"]) // max(1, nch),
        "peak_gain_applied": round(result["peak_gain"], 4),
        "output_peak": round(out_peak, 4),
        "agc_target": result["agc_target"],
        "agc_drive": result["agc_drive"],
        "ceiling": round(result["ceiling"], 4),
        "note": (
            "Server-side peak/AGC stub for transmission preview — not a full "
            "Liquidsoap/Mac chain. Browser Program processor remains live On-Air DSP."
        ),
    }


__all__ = [
    "apply_transmission_stub",
    "peak_normalize",
    "process_wav_file",
    "simple_agc",
]

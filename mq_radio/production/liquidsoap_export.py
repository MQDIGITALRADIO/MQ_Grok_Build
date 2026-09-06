"""Export MQ native processing templates as Liquidsoap handoff stubs.

Not a full Optimod clone — documents the AGC→EQ→Multiband→Exciter→Limiter
topology as JSON + a readable .liq snippet for a future Mac/Liquidsoap chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR, ROOT
from mq_radio.production.processing import (
    STAGE_LABELS,
    STAGE_ORDER,
    digital_template,
    fm_template,
    load_processing,
    normalize_processing,
)

HANDOFF_VERSION = 3


def _repo_packaging_dir() -> Path:
    return ROOT / "packaging" / "liquidsoap"


def _data_processing_dir(data_dir: Optional[Path] = None) -> Path:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    d = root / "processing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def handoff_payload(
    chain: Optional[dict[str, Any]] = None,
    *,
    include_templates: bool = True,
) -> dict[str, Any]:
    """Documented JSON handoff for FM/Digital (or current) processing chain."""
    current = normalize_processing(chain) if chain else load_processing()
    payload: dict[str, Any] = {
        "version": HANDOFF_VERSION,
        "kind": "mq_radio_processing_handoff",
        "engine_target": "liquidsoap",
        "status": "stub",
        "notes": (
            "MQ native on-air processing handoff — NOT an Orban Optimod schematic clone. "
            "Topology is public broadcast practice: AGC → EQ → Multiband → Exciter → Peak Limiter. "
            "Browser On-Air is the live Program processor (desk or transmission_mode). "
            "Server peak/AGC stub: mq_radio.production.transmission_dsp.process_wav_file on exported WAV. "
            "Mac/Liquidsoap should wire these params on the transmission path; AU/AAX hosting remains later."
        ),
        "topology": " → ".join(STAGE_LABELS[s] for s in STAGE_ORDER),
        "stage_order": list(STAGE_ORDER),
        "stage_labels": dict(STAGE_LABELS),
        "current": {
            "enabled": current.get("enabled"),
            "template": current.get("template"),
            "transmission_mode": bool(current.get("transmission_mode")),
            "output": current.get("output"),
            "stages": current.get("stages"),
            "notes": current.get("notes"),
        },
        "liquidsoap_hints": {
            "input": "harbor / playlist / request.queue (program bus)",
            "insert_policy": current.get("insert_policy") or "native_when_empty",
            "map_stages": {
                "agc": "compress / normalize (target_db, attack_ms, release_ms)",
                "eq": "eq.filter / filter.iir (shelf + presence + air + high_cut)",
                "multiband": "compress.multiband or parallel band compressors at crossovers_hz",
                "exciter": "subtle harmonic / high-shelf wet-dry (amount, mix) — keep mild",
                "limiter": "limit (ceiling_dbfs, lookahead_ms); ISR flag for digital path",
            },
            "fm_output": "preemphasis flag + stereo_enhance — apply only on FM path",
            "digital_output": "no preemphasis; ISR-aware limiter ceiling",
            "transmission_mode": (
                "When true, push denser FM (more drive / tighter release) vs cleaner Digital "
                "(lower ceiling, milder exciter) — mirrors browser Program processor TX toggle"
            ),
            "python_stub": "mq_radio.production.transmission_dsp.process_wav_file(src, dst, template=...)",
            "mix_minus_mac": (
                "Mac engine path: mix_minus_out = program_processed - aux_in_return "
                "(polarity invert + sum). Browser Web Audio implements this when Aux capture is live; "
                "CoreAudio dual-device subtract remains engine milestone."
            ),
            "master_control": (
                "Operator path: install Liquidsoap on the Mac playout host, map stages from "
                "processing_handoff.json / template_*.json, run as Master Control for TX. "
                "Desk Web Audio remains the live Program processor until that graph is live."
            ),
        },
        "operator_install": {
            "role": "Master Control / transmission chain (Mac playout host)",
            "status": "documented — not auto-installed by MQ Radio DMG",
            "macos_homebrew": "brew install liquidsoap",
            "verify": "liquidsoap --version",
            "config_inputs": [
                "packaging/liquidsoap/processing_handoff.json",
                "packaging/liquidsoap/template_fm.json",
                "packaging/liquidsoap/template_digital.json",
                "packaging/liquidsoap/mq_processing_stub.liq",
                "packaging/liquidsoap/mq_master_control_operator.liq",
                "desktop/resources/master_control/liquidsoap/",
            ],
            "steps": [
                "Install Liquidsoap on the Mac that owns the transmitter / encoder path (Homebrew or official binary).",
                "Export or copy current FM/Digital params (Settings → processing export, or regenerate via Python).",
                "Wire operators in a real .liq: harbor/playlist → AGC → EQ → Multiband → Exciter → Limiter → Icecast/soundcard.",
                "Honour transmission_mode and output.preemphasis from the handoff JSON (FM denser / Digital cleaner).",
                "Keep MQ Radio desk as control UI + Living Log; Liquidsoap owns Master Control TX audio.",
            ],
            "not_included": [
                "Guaranteed Liquidsoap binary in every Electron DMG (copied only when brew present on Mac CI)",
                "Live Telnet/Harbor control from MockEngine (LiquidsoapEngine start/stop stubs only)",
                "Auto-started Master Control graph from the desk",
                "AU/AAX hosting",
            ],
            "dry_run": "POST /api/settings/master-control/dry-run",
            "start_stop": "POST /api/settings/master-control/{start,stop} — fail clearly; never fake Harbor",
        },
    }
    if include_templates:
        payload["templates"] = {
            "FM": fm_template(),
            "DIGITAL": digital_template(),
        }
    return payload


def render_liq_snippet(chain: Optional[dict[str, Any]] = None) -> str:
    """Readable Liquidsoap-oriented snippet (documented stub, not a full script)."""
    c = normalize_processing(chain) if chain else load_processing()
    stages = c.get("stages") or {}
    agc = stages.get("agc") or {}
    eq = stages.get("eq") or {}
    mb = stages.get("multiband") or {}
    exc = stages.get("exciter") or {}
    lim = stages.get("limiter") or {}
    out = c.get("output") or {}
    tmpl = c.get("template") or "FM"
    lines = [
        "# MQ Radio — Liquidsoap processing handoff stub",
        f"# Template: {tmpl} | Topology: AGC → EQ → Multiband → Exciter → Limiter",
        "# STATUS: stub — wire real operators for Master Control on Mac.",
        "# Operator install: brew install liquidsoap  (see packaging/liquidsoap/README.md)",
        "# NOT an Optimod clone. Params mirror data/processing.json / native desk.",
        "#",
        "# Suggested program chain (pseudo / documented — wire real operators on Mac):",
        "#   program = input  # harbor / playlist / request.queue",
        "#   program = compress(target=agc.target_db, attack=..., release=..., program)",
        "#   program = eq(...)  # low_shelf + presence + air + high_cut from stages.eq",
        "#   program = compress.multiband(crossovers=mb.crossovers_hz, drive=mb.drive_db, program)",
        "#   program = dry_wet(highshelf_harmonics(...), mix=exc.mix)  # mild",
        "#   program = limit(ceiling=lim.ceiling_dbfs, lookahead=lim.lookahead_ms, program)",
        "#   # FM only: preemphasis(us=out.preemphasis_us, program)",
        "#   output.icecast(%mp3, ... , program)  # or FM encoder / soundcard",
        "#",
        "# Mix-minus (Mac engine):",
        "#   aux_return = input.microphone(...)  # or harbor from Zoom/hybrid",
        "#   mix_minus = program - aux_return    # polarity invert aux, sum with program",
        "#   output.speaker(mix_minus)           # hybrid send / USB out",
        "#",
        f"# enabled={bool(c.get('enabled'))}  path={out.get('path')}  "
        f"transmission_mode={bool(c.get('transmission_mode'))}  "
        f"preemphasis={out.get('preemphasis')} us={out.get('preemphasis_us')}",
        "#",
        f"# AGC: target_db={agc.get('target_db')} drive_db={agc.get('drive_db')} "
        f"attack_ms={agc.get('attack_ms')} release_ms={agc.get('release_ms')} "
        f"gate_db={agc.get('gate_db')} enabled={agc.get('enabled')}",
        f"# EQ: low_shelf {eq.get('low_shelf_hz')}Hz/{eq.get('low_shelf_db')}dB · "
        f"presence {eq.get('presence_hz')}Hz/{eq.get('presence_db')}dB · "
        f"air {eq.get('air_hz')}Hz/{eq.get('air_db')}dB · high_cut {eq.get('high_cut_hz')}Hz",
        f"# Multiband: bands={mb.get('bands')} crossovers_hz={mb.get('crossovers_hz')} "
        f"drive_db={mb.get('drive_db')} release_ms={mb.get('release_ms')} couple={mb.get('couple')}",
        f"# Exciter: amount={exc.get('amount')} harmonics={exc.get('harmonics')} "
        f"mix={exc.get('mix')} enabled={exc.get('enabled')}",
        f"# Limiter: ceiling_dbfs={lim.get('ceiling_dbfs')} release_ms={lim.get('release_ms')} "
        f"lookahead_ms={lim.get('lookahead_ms')} isr={lim.get('isr')} enabled={lim.get('enabled')}",
        "#",
        "# See packaging/liquidsoap/README.md and processing_handoff.json for full templates.",
        "",
    ]
    return "\n".join(lines)


def export_processing_handoff(
    *,
    data_dir: Optional[Path] = None,
    packaging_dir: Optional[Path] = None,
    chain: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Write JSON + .liq stub under packaging/liquidsoap and data/processing/."""
    payload = handoff_payload(chain, include_templates=True)
    liq = render_liq_snippet(chain or payload.get("current"))

    targets: list[Path] = []
    pkg = Path(packaging_dir) if packaging_dir else _repo_packaging_dir()
    pkg.mkdir(parents=True, exist_ok=True)
    targets.append(pkg)

    data_proc = _data_processing_dir(data_dir)
    targets.append(data_proc)

    written: list[str] = []
    for root in targets:
        jpath = root / "processing_handoff.json"
        lpath = root / "mq_processing_stub.liq"
        rpath = root / "README.md"
        jpath.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        lpath.write_text(liq, encoding="utf-8")
        if not rpath.exists() or root == pkg:
            rpath.write_text(
                _readme_text(),
                encoding="utf-8",
            )
        written.extend([str(jpath), str(lpath), str(rpath)])

    # Also write per-template JSON for clarity
    for name, tmpl in (("FM", fm_template()), ("DIGITAL", digital_template())):
        for root in targets:
            p = root / f"template_{name.lower()}.json"
            p.write_text(json.dumps(tmpl, indent=2) + "\n", encoding="utf-8")
            written.append(str(p))

    # Operator sketch beside handoff (imported lazily to avoid cycles at import)
    try:
        from mq_radio.production.master_control import render_operator_liq

        op_text = render_operator_liq()
        for root in targets:
            op = root / "mq_master_control_operator.liq"
            op.write_text(op_text, encoding="utf-8")
            written.append(str(op))
    except Exception:
        pass

    return {
        "ok": True,
        "version": HANDOFF_VERSION,
        "written": written,
        "topology": payload["topology"],
        "template": (chain or payload["current"]).get("template")
        if isinstance(chain or payload.get("current"), dict)
        else payload["current"].get("template"),
        "status": "stub",
        "live_harbor": False,
    }


def _readme_text() -> str:
    return """# MQ Radio → Liquidsoap processing handoff

Documented handoff for a **Mac / Liquidsoap Master Control** transmission chain.
Handoff version 3 — FM/Digital templates + `transmission_mode` + operator install notes.

## What this is

- Exports the **native desk** processing templates (**FM** / **Digital**)
- Topology (public broadcast practice, **not** an Optimod clone):

  **AGC → EQ → Multiband → Exciter → Peak Limiter**

- `processing_handoff.json` — current + both templates + Liquidsoap mapping hints + `operator_install`
- `mq_processing_stub.liq` — commented snippet mirroring current params
- `template_fm.json` / `template_digital.json` — standalone template dumps

## Operator install (Master Control path)

Liquidsoap is **not** bundled in the MQ Radio DMG. Install it on the Mac that owns
the transmitter / encoder path:

```bash
brew install liquidsoap
liquidsoap --version
```

Then:

1. Copy or regenerate this folder (`export_processing_handoff` / Settings → processing export).
2. Build a real `.liq` from `mq_processing_stub.liq` + `processing_handoff.json` stage map.
3. Honour **FM vs Digital** and **`transmission_mode`** (denser FM / cleaner Digital).
4. Run Liquidsoap as Master Control for TX; keep MQ Radio as Living Log + desk control UI.

Optional Harbor / Telnet control from `LiquidsoapEngine` remains a later wire-up
(`mq_radio/engine/liquidsoap.py` is still a stub).

## What this is not

- Not a running production Liquidsoap script (stub comments only)
- Not AU/AAX hosting
- Not a multiband Optimod schematic clone
- Not auto-installed by the Electron package

Browser On-Air is the live Program processor (optional **transmission_mode** for denser FM vs cleaner Digital).
Python peak/AGC stub: `mq_radio.production.transmission_dsp.process_wav_file` on exported WAV.
Mix-minus: browser subtracts Aux return when capture is live; Mac path is `program - aux_return`.

Regenerate from Python:

```bash
python -c "from mq_radio.production.liquidsoap_export import export_processing_handoff; print(export_processing_handoff())"
```

Or `POST /api/settings/processing/export`.

Operator dry-run / start stubs: `mq_radio.production.master_control` and
`GET|POST /api/settings/master-control…` — never claim live Harbor Done.
"""

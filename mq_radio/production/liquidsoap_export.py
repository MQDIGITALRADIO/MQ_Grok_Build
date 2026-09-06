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

HANDOFF_VERSION = 1


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
            "Browser On-Air approximates this; transmission-path DSP applies these params in Liquidsoap/Mac later. "
            "AU/AAX hosting is out of scope here (optional Mac production-bus later)."
        ),
        "topology": " → ".join(STAGE_LABELS[s] for s in STAGE_ORDER),
        "stage_order": list(STAGE_ORDER),
        "stage_labels": dict(STAGE_LABELS),
        "current": {
            "enabled": current.get("enabled"),
            "template": current.get("template"),
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
        "# STATUS: stub — wire real operators in Mac/Liquidsoap milestone.",
        "# NOT an Optimod clone. Params mirror data/processing.json / native desk.",
        "#",
        "# Suggested program chain (pseudo / documented):",
        "#   program = input  # harbor / playlist / request.queue",
        "#   program = mq_agc(program, ...)",
        "#   program = mq_eq(program, ...)",
        "#   program = mq_multiband(program, ...)",
        "#   program = mq_exciter(program, ...)",
        "#   program = mq_limiter(program, ...)",
        "#   output.icecast(%mp3, ... , program)  # or FM encoder path",
        "#",
        f"# enabled={bool(c.get('enabled'))}  path={out.get('path')}  "
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

    return {
        "ok": True,
        "version": HANDOFF_VERSION,
        "written": written,
        "topology": payload["topology"],
        "template": (chain or payload["current"]).get("template")
        if isinstance(chain or payload.get("current"), dict)
        else payload["current"].get("template"),
        "status": "stub",
    }


def _readme_text() -> str:
    return """# MQ Radio → Liquidsoap processing handoff

Documented stub for a future Mac / Liquidsoap transmission chain.

## What this is

- Exports the **native desk** processing templates (**FM** / **Digital**)
- Topology (public broadcast practice, **not** an Optimod clone):

  **AGC → EQ → Multiband → Exciter → Peak Limiter**

- `processing_handoff.json` — full current + both templates + Liquidsoap mapping hints
- `mq_processing_stub.liq` — commented snippet mirroring current params
- `template_fm.json` / `template_digital.json` — standalone template dumps

## What this is not

- Not a running Liquidsoap script
- Not AU/AAX hosting
- Not a multiband Optimod schematic clone

Browser On-Air already approximates this chain for desk audition.
Wire these params into Liquidsoap operators when the Mac engine owns the transmission path.

Regenerate from Python:

```bash
python -c "from mq_radio.production.liquidsoap_export import export_processing_handoff; print(export_processing_handoff())"
```

Or `POST /api/settings/processing/export`.
"""

"""Liquidsoap Master Control — operator path (bundled templates + dry-run + stubs).

Honest scope
------------
* Ships FM/Digital handoff templates and an operator ``.liq`` sketch.
* Discovers a Liquidsoap binary (PATH or bundled Mac runtime) when present.
* Dry-runs validate that templates / handoff JSON are coherent for an operator.
* ``start`` / ``stop`` are **stubs**: they fail clearly when the binary is missing
  or when no live Harbor graph is wired. They never pretend On-Air TX is live.

Do **not** mark P2 "Live Liquidsoap / Harbor" Done from this module.
Desk Web Audio remains the live Program processor until ``LiquidsoapEngine``
owns a real Telnet/Harbor graph on the Mac playout host.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from mq_radio.config import DATA_DIR, ROOT
from mq_radio.production.liquidsoap_export import (
    HANDOFF_VERSION,
    export_processing_handoff,
    handoff_payload,
)

# Operator-facing honesty
OPERATOR_STATUS_STUB = "operator_pack"  # bundled templates — not live Harbor
OPERATOR_STATUS_MISSING_BINARY = "liquidsoap_missing"
OPERATOR_STATUS_READY_OFFLINE = "binary_present_graph_not_wired"
LIVE_HARBOR = False  # hard rule until LiquidsoapEngine owns a real graph

REQUIRED_HANDOFF_KEYS = (
    "version",
    "kind",
    "topology",
    "stage_order",
    "current",
    "liquidsoap_hints",
    "operator_install",
)

REQUIRED_TEMPLATE_FILES = (
    "processing_handoff.json",
    "mq_processing_stub.liq",
    "template_fm.json",
    "template_digital.json",
    "mq_master_control_operator.liq",
)


def _unique_existing(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        key = str(rp)
        if key in seen:
            continue
        if p.is_dir():
            seen.add(key)
            out.append(p)
    return out


def template_search_roots(
    *,
    data_dir: Optional[Path] = None,
    extra: Optional[list[Path]] = None,
) -> list[Path]:
    """Ordered roots that may hold Master Control Liquidsoap templates."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    candidates = [
        ROOT / "packaging" / "liquidsoap",
        ROOT / "desktop" / "resources" / "master_control" / "liquidsoap",
        root / "processing",
        root / "master_control" / "liquidsoap",
    ]
    # Bundled Mac app resources (Electron process.resourcesPath → env)
    env_res = (os.environ.get("MQ_RADIO_RESOURCES") or "").strip()
    if env_res:
        candidates.insert(0, Path(env_res) / "master_control" / "liquidsoap")
        candidates.insert(1, Path(env_res) / "runtime" / "liquidsoap")
    if extra:
        candidates.extend(extra)
    return _unique_existing(candidates)


def find_template_dir(*, data_dir: Optional[Path] = None) -> Optional[Path]:
    """First template root that has the handoff JSON (operator pack)."""
    for root in template_search_roots(data_dir=data_dir):
        if (root / "processing_handoff.json").is_file():
            return root
        # packaging root may lack operator.liq until staged — still usable
        if (root / "template_fm.json").is_file() and (root / "mq_processing_stub.liq").is_file():
            return root
    return None


def ensure_operator_templates(
    *,
    data_dir: Optional[Path] = None,
    packaging_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Write / refresh handoff + operator ``.liq`` into packaging + data dirs.

    Always regenerates the documented handoff; also ensures the operator sketch
    ``mq_master_control_operator.liq`` exists beside the handoff files.
    """
    pkg = Path(packaging_dir) if packaging_dir else (ROOT / "packaging" / "liquidsoap")
    data_root = Path(data_dir) if data_dir is not None else DATA_DIR
    result = export_processing_handoff(data_dir=data_root, packaging_dir=pkg)
    written = list(result.get("written") or [])

    operator_text = render_operator_liq()
    for root in (pkg, data_root / "processing"):
        root.mkdir(parents=True, exist_ok=True)
        op = root / "mq_master_control_operator.liq"
        op.write_text(operator_text, encoding="utf-8")
        written.append(str(op))
        # Operator handoff README for the data copy
        docs = root / "OPERATOR.md"
        if root == pkg or not docs.exists():
            docs.write_text(_operator_doc_text(), encoding="utf-8")
            written.append(str(docs))

    # Desktop resources pack (when present in repo checkout)
    mc = ROOT / "desktop" / "resources" / "master_control"
    if mc.is_dir() or True:
        liq_dir = mc / "liquidsoap"
        docs_dir = mc / "docs"
        liq_dir.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        # Mirror packaging into the staged pack
        for name in (
            "processing_handoff.json",
            "mq_processing_stub.liq",
            "template_fm.json",
            "template_digital.json",
            "mq_master_control_operator.liq",
            "README.md",
            "OPERATOR.md",
        ):
            src = pkg / name
            if src.is_file():
                dest = liq_dir / name
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                written.append(str(dest))
        (docs_dir / "OPERATOR.md").write_text(_operator_doc_text(), encoding="utf-8")
        written.append(str(docs_dir / "OPERATOR.md"))
        (mc / "README.md").write_text(
            "# Master Control runtime pack\n\n"
            "Liquidsoap handoff v{ver} + operator `.liq` sketches for the TX Mac.\n\n"
            "- Desk = Living Log + On-Air UI\n"
            "- Liquidsoap = Master Control TX when installed and wired\n"
            "- **Not** a live Harbor graph until `LiquidsoapEngine` owns Telnet/Harbor\n"
            "- See `docs/OPERATOR.md` and `liquidsoap/OPERATOR.md`\n\n"
            "Music library stays external (MQ Digital drive).\n".format(ver=HANDOFF_VERSION),
            encoding="utf-8",
        )
        written.append(str(mc / "README.md"))

    result["written"] = written
    result["operator_liq"] = "mq_master_control_operator.liq"
    result["live_harbor"] = False
    result["status"] = OPERATOR_STATUS_STUB
    return result


def render_operator_liq(*, harbor_port: int = 8005, aux_port: int = 8006) -> str:
    """Bundled operator sketch — commented; safe to ship; not auto-started."""
    return f"""# MQ Radio — Master Control operator sketch (Liquidsoap)
# Handoff version {HANDOFF_VERSION} — pair with processing_handoff.json
# STATUS: operator pack / dry-run target — NOT a live Harbor graph
# Install on the TX Mac: brew install liquidsoap && liquidsoap --version
# Desk keeps Living Log + On-Air; this script is for Master Control TX only.
# Do not claim live Harbor Done until LiquidsoapEngine wires Telnet/Harbor.

# --- Dry-run markers (parsed by mq_radio.production.master_control) ---
# MQ_RADIO_OPERATOR_PACK=1
# MQ_RADIO_HANDOFF_VERSION={HANDOFF_VERSION}
# MQ_RADIO_LIVE_HARBOR=0
# MQ_RADIO_TOPOLOGY=AGC>EQ>Multiband>Exciter>Limiter

# settings.init.allow_root.set(false)

# --- Suggested Harbor inputs (wire when TX host is ready) ---
# program = input.harbor("mq.program", port={harbor_port}, headers=[], buffer=0.5)
# aux = input.harbor("mq.aux", port={aux_port}, headers=[], buffer=0.5)
# mix_minus = program  # when wired: program - aux (polarity invert aux, sum)

# --- Processing chain (public practice — not an Optimod clone) ---
# Map stages from processing_handoff.json / template_fm.json / template_digital.json
# Honour transmission_mode (denser FM / cleaner Digital) and output.preemphasis.
# AGC → EQ → Multiband → Exciter → Peak Limiter
# See mq_processing_stub.liq for current param mirrors from the desk.

# program = compress(...)       # AGC
# program = eq(...)             # EQ
# program = compress.multiband(...)
# program = dry_wet(...)        # mild exciter
# program = limit(...)          # peak limiter
# # FM only: preemphasis(...)

# --- Outputs (examples — operator edits host/password/mount) ---
# output.icecast(%mp3, host="127.0.0.1", port=8000, password="hackme",
#   mount="mq-fm", program)
# output.ao(program)  # or CoreAudio soundcard sink on Mac

# --- Operator check ---
# liquidsoap --check mq_master_control_operator.liq
# (Expect warnings on commented-only sketches; use a filled .liq for --check green.)
"""


def _operator_doc_text() -> str:
    return f"""# Master Control operator path

Handoff **v{HANDOFF_VERSION}**. Paying-client honesty: this pack is the **operator path**
(templates + dry-run + clear start/stop stubs). It is **not** a live Harbor graph.

## Bundled files

| File | Role |
|------|------|
| `processing_handoff.json` | Current + FM/Digital templates + Liquidsoap mapping hints |
| `template_fm.json` / `template_digital.json` | Standalone template dumps |
| `mq_processing_stub.liq` | Commented param mirror of the desk chain |
| `mq_master_control_operator.liq` | Operator sketch (Harbor ports + topology markers) |

## Install Liquidsoap (TX Mac)

```bash
brew install liquidsoap
liquidsoap --version
```

Optional: re-run `packaging/scripts/stage_mac_resources.sh` on a Mac that has
Liquidsoap so the binary is copied into `Resources/runtime/liquidsoap/`.

## Dry-run (no live audio)

From the repo / engine:

```bash
python -c "from mq_radio.production.master_control import dry_run; import json; print(json.dumps(dry_run(), indent=2))"
```

Or `POST /api/settings/master-control/dry-run`.

Dry-run checks handoff JSON shape, template files, operator `.liq` markers, and
whether a `liquidsoap` binary is on PATH / bundled. It never starts Harbor.

## Start / stop stubs

`POST /api/settings/master-control/start` and `.../stop` call
`LiquidsoapEngine` / `master_control.start_stub` / `stop_stub`.

* Binary missing → clear error (`liquidsoap_missing`) — install via Homebrew.
* Binary present → still **not** live Harbor (`graph_not_wired`) until Telnet/Harbor
  is implemented in `mq_radio/engine/liquidsoap.py`.

## What stays on the desk

Browser On-Air = live Program processor (optional transmission_mode).
Living Log, clocks, cartwall, VT stay in MQ Radio. Liquidsoap owns TX Master
Control **after** an operator wires a real `.liq` on the playout host.

Regenerate templates: `POST /api/settings/processing/export` or
`ensure_operator_templates()`.
"""


def resolve_liquidsoap_binary(
    *,
    explicit: Optional[str] = None,
    resources_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Locate a liquidsoap executable without claiming it is running a graph."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    env = (os.environ.get("MQ_RADIO_LIQUIDSOAP") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    which = shutil.which("liquidsoap")
    if which:
        return Path(which)
    roots: list[Path] = []
    if resources_dir:
        roots.append(Path(resources_dir))
    env_res = (os.environ.get("MQ_RADIO_RESOURCES") or "").strip()
    if env_res:
        roots.append(Path(env_res))
    roots.append(ROOT / "desktop" / "resources")
    for root in roots:
        for cand in (
            root / "runtime" / "liquidsoap" / "liquidsoap",
            root / "liquidsoap" / "liquidsoap",
            root / "runtime" / "liquidsoap.bin",
        ):
            if cand.is_file() and os.access(cand, os.X_OK):
                return cand
    return None


def probe_liquidsoap_version(binary: Optional[Path] = None) -> dict[str, Any]:
    """Best-effort ``liquidsoap --version`` (never starts a Harbor graph)."""
    bin_path = binary or resolve_liquidsoap_binary()
    out: dict[str, Any] = {
        "binary": str(bin_path) if bin_path else None,
        "available": bool(bin_path),
        "version": None,
        "error": None,
    }
    if not bin_path:
        out["error"] = (
            "liquidsoap binary not found — brew install liquidsoap "
            "(or stage via packaging/scripts/stage_mac_resources.sh on Mac)"
        )
        return out
    try:
        proc = subprocess.run(
            [str(bin_path), "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        out["version"] = text.splitlines()[0] if text else None
        if proc.returncode != 0 and not text:
            out["error"] = f"liquidsoap --version exit {proc.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        out["error"] = str(exc)
        out["available"] = False
    return out


def _load_json(path: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "handoff JSON root must be an object"
    return data, None


def validate_handoff_file(path: Path) -> dict[str, Any]:
    """Validate processing_handoff.json shape for operator dry-run."""
    result: dict[str, Any] = {
        "path": str(path),
        "ok": False,
        "errors": [],
        "warnings": [],
        "version": None,
    }
    if not path.is_file():
        result["errors"].append("processing_handoff.json missing")
        return result
    data, err = _load_json(path)
    if err or data is None:
        result["errors"].append(err or "unreadable handoff JSON")
        return result
    missing = [k for k in REQUIRED_HANDOFF_KEYS if k not in data]
    if missing:
        result["errors"].append(f"missing keys: {', '.join(missing)}")
    result["version"] = data.get("version")
    if data.get("version") != HANDOFF_VERSION:
        result["warnings"].append(
            f"handoff version {data.get('version')!r} != code HANDOFF_VERSION {HANDOFF_VERSION}"
        )
    if data.get("kind") != "mq_radio_processing_handoff":
        result["warnings"].append("unexpected kind — expected mq_radio_processing_handoff")
    if data.get("status") == "stub":
        result["warnings"].append("status=stub (expected until live Harbor)")
    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    if "transmission_mode" not in current:
        result["errors"].append("current.transmission_mode missing")
    stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
    for stage in ("agc", "eq", "multiband", "exciter", "limiter"):
        if stage not in stages:
            result["warnings"].append(f"current.stages.{stage} missing")
    result["ok"] = not result["errors"]
    return result


def validate_operator_liq(path: Path) -> dict[str, Any]:
    """Check operator sketch markers (does not execute Liquidsoap)."""
    result: dict[str, Any] = {
        "path": str(path),
        "ok": False,
        "errors": [],
        "warnings": [],
        "markers": {},
    }
    if not path.is_file():
        result["errors"].append("mq_master_control_operator.liq missing")
        return result
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        result["errors"].append(str(exc))
        return result
    markers = {
        "operator_pack": "MQ_RADIO_OPERATOR_PACK=1" in text,
        "live_harbor_false": "MQ_RADIO_LIVE_HARBOR=0" in text,
        "topology": "MQ_RADIO_TOPOLOGY=" in text or "AGC" in text,
        "harbor_comment": "input.harbor" in text,
        "not_autostart": "NOT a live Harbor" in text or "not auto-started" in text.lower()
        or "STATUS: operator pack" in text,
    }
    result["markers"] = markers
    if not markers["operator_pack"]:
        result["warnings"].append("missing MQ_RADIO_OPERATOR_PACK=1 marker (older sketch)")
    if not markers["live_harbor_false"]:
        result["warnings"].append("missing MQ_RADIO_LIVE_HARBOR=0 honesty marker")
    if not markers["topology"]:
        result["errors"].append("operator .liq missing topology / AGC chain notes")
    if "output.icecast" not in text and "output.ao" not in text:
        result["warnings"].append("no example output.* lines in operator sketch")
    # Must not look like an uncommented live script claiming harbor
    live_lines = [
        ln
        for ln in text.splitlines()
        if ln.strip()
        and not ln.strip().startswith("#")
        and "input.harbor" in ln
    ]
    if live_lines:
        result["warnings"].append(
            "uncommented input.harbor lines present — operator must own live wiring; "
            "desk still does not claim Harbor Done"
        )
    result["ok"] = not result["errors"]
    return result


def dry_run(
    *,
    data_dir: Optional[Path] = None,
    template_dir: Optional[Path] = None,
    binary: Optional[str] = None,
    refresh_templates: bool = False,
) -> dict[str, Any]:
    """Validate operator pack + binary probe. Never starts Liquidsoap / Harbor."""
    if refresh_templates:
        ensure_operator_templates(data_dir=data_dir)

    tmpl = Path(template_dir) if template_dir else find_template_dir(data_dir=data_dir)
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    if tmpl is None:
        errors.append(
            "no Master Control template directory found — run ensure_operator_templates() "
            "or POST /api/settings/processing/export"
        )
    else:
        checks["template_dir"] = str(tmpl)
        handoff = validate_handoff_file(tmpl / "processing_handoff.json")
        checks["handoff"] = handoff
        if not handoff["ok"]:
            errors.extend(handoff["errors"])
        warnings.extend(handoff.get("warnings") or [])

        for name in ("template_fm.json", "template_digital.json", "mq_processing_stub.liq"):
            p = tmpl / name
            ok = p.is_file() and p.stat().st_size > 40
            checks[name] = {"path": str(p), "ok": ok}
            if not ok:
                errors.append(f"missing or tiny {name}")

        op_liq = tmpl / "mq_master_control_operator.liq"
        if not op_liq.is_file():
            # packaging/ may lag until ensure — try sibling / regenerate note
            warnings.append(
                "mq_master_control_operator.liq missing in template dir — "
                "call ensure_operator_templates() or re-stage Mac resources"
            )
            checks["operator_liq"] = {"path": str(op_liq), "ok": False}
        else:
            op_val = validate_operator_liq(op_liq)
            checks["operator_liq"] = op_val
            if not op_val["ok"]:
                errors.extend(op_val["errors"])
            warnings.extend(op_val.get("warnings") or [])

    bin_path = resolve_liquidsoap_binary(explicit=binary)
    version = probe_liquidsoap_version(bin_path)
    checks["liquidsoap"] = version

    if not version.get("available"):
        status = OPERATOR_STATUS_MISSING_BINARY
        warnings.append(version.get("error") or "liquidsoap binary missing")
    else:
        status = OPERATOR_STATUS_READY_OFFLINE
        warnings.append(
            "liquidsoap binary present — Master Control graph still not wired "
            "(live Harbor remains Missing)"
        )

    ok = not errors
    return {
        "ok": ok,
        "status": status if ok else "dry_run_failed",
        "live_harbor": False,
        "harbor_wired": False,
        "engine_target": "liquidsoap",
        "handoff_version": HANDOFF_VERSION,
        "platform": platform.system().lower(),
        "template_dir": str(tmpl) if tmpl else None,
        "binary": version.get("binary"),
        "version_line": version.get("version"),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "operator_message": _dry_run_operator_message(ok, status, errors, warnings),
        "next_steps": _next_steps(status),
    }


def _dry_run_operator_message(
    ok: bool,
    status: str,
    errors: list[str],
    warnings: list[str],
) -> str:
    if not ok:
        return "Master Control dry-run failed — " + (errors[0] if errors else "see errors")
    if status == OPERATOR_STATUS_MISSING_BINARY:
        return (
            "Operator pack OK — liquidsoap binary missing. "
            "Install with brew install liquidsoap. Live Harbor still not wired."
        )
    return (
        "Operator pack OK — liquidsoap found, but live Harbor / Telnet graph "
        "is not wired. Desk On-Air remains the live Program processor."
    )


def _next_steps(status: str) -> list[str]:
    steps = [
        "Keep MQ Radio desk as Living Log + On-Air control UI",
        "Map FM/Digital params from processing_handoff.json into a real .liq",
        "Honour transmission_mode and output.preemphasis on the TX host",
    ]
    if status == OPERATOR_STATUS_MISSING_BINARY:
        steps.insert(0, "brew install liquidsoap && liquidsoap --version")
        steps.insert(1, "Optional: re-run packaging/scripts/stage_mac_resources.sh on Mac CI")
    else:
        steps.insert(
            0,
            "Wire Harbor/Telnet in mq_radio/engine/liquidsoap.py before claiming live Master Control",
        )
    steps.append("Do not mark P2 live Liquidsoap/Harbor Done until the graph runs on-air")
    return steps


def start_stub(
    *,
    data_dir: Optional[Path] = None,
    binary: Optional[str] = None,
    script: Optional[str] = None,
) -> dict[str, Any]:
    """Refuse to fake a live Master Control start.

    Fails clearly when the binary is missing. When present, still refuses to
    spawn Harbor until the engine graph is implemented — paying-client honesty.
    """
    probe = dry_run(data_dir=data_dir, binary=binary)
    bin_path = resolve_liquidsoap_binary(explicit=binary)
    if not bin_path:
        return {
            "ok": False,
            "started": False,
            "live_harbor": False,
            "error": "liquidsoap_missing",
            "status": OPERATOR_STATUS_MISSING_BINARY,
            "operator_message": (
                "Cannot start Master Control — liquidsoap binary not found. "
                "Install: brew install liquidsoap. "
                "Templates remain available under packaging/liquidsoap and "
                "Resources/master_control/."
            ),
            "dry_run": probe,
            "hint": "POST /api/settings/master-control/dry-run",
        }
    script_path = Path(script) if script else None
    if script_path is None:
        tmpl = find_template_dir(data_dir=data_dir)
        if tmpl:
            candidate = tmpl / "mq_master_control_operator.liq"
            if candidate.is_file():
                script_path = candidate
    return {
        "ok": False,
        "started": False,
        "live_harbor": False,
        "error": "graph_not_wired",
        "status": OPERATOR_STATUS_READY_OFFLINE,
        "binary": str(bin_path),
        "script": str(script_path) if script_path else None,
        "operator_message": (
            f"liquidsoap found at {bin_path}, but MQ Radio will not auto-start a "
            "Harbor/Telnet Master Control graph yet (LiquidsoapEngine stub). "
            "Run a filled .liq manually on the TX Mac if you need TX now; "
            "desk On-Air remains the live Program processor."
        ),
        "dry_run": probe,
        "manual": (
            f"liquidsoap {script_path}"
            if script_path
            else "liquidsoap /path/to/your_master_control.liq"
        ),
    }


def stop_stub(*, reason: Optional[str] = None) -> dict[str, Any]:
    """Stop stub — nothing to stop; clear operator copy."""
    return {
        "ok": True,
        "stopped": False,
        "was_running": False,
        "live_harbor": False,
        "status": "not_running",
        "operator_message": (
            reason
            or "Master Control was not started by MQ Radio (no live Harbor process). "
            "If you launched liquidsoap manually in Terminal, stop it there (Ctrl+C)."
        ),
    }


def operator_status(*, data_dir: Optional[Path] = None) -> dict[str, Any]:
    """Settings / status envelope for Master Control operator path."""
    tmpl = find_template_dir(data_dir=data_dir)
    bin_path = resolve_liquidsoap_binary()
    version = probe_liquidsoap_version(bin_path)
    if not tmpl:
        pack_status = "templates_missing"
    elif not version.get("available"):
        pack_status = OPERATOR_STATUS_MISSING_BINARY
    else:
        pack_status = OPERATOR_STATUS_READY_OFFLINE

    payload = handoff_payload()
    return {
        "ok": True,
        "kind": "mq_radio_master_control",
        "live_harbor": False,
        "harbor_wired": False,
        "status": pack_status,
        "handoff_version": HANDOFF_VERSION,
        "topology": payload.get("topology"),
        "template_dir": str(tmpl) if tmpl else None,
        "bundled_files": list(REQUIRED_TEMPLATE_FILES),
        "liquidsoap": version,
        "operator_install": payload.get("operator_install"),
        "operator_message": (
            "Master Control operator pack — templates + dry-run only. "
            "Live Harbor graph not wired."
            if tmpl
            else "Master Control templates missing — export processing handoff first."
        ),
        "docs": [
            "packaging/liquidsoap/README.md",
            "packaging/liquidsoap/OPERATOR.md",
            "desktop/resources/master_control/docs/OPERATOR.md",
        ],
        "endpoints": {
            "status": "GET /api/settings/master-control",
            "dry_run": "POST /api/settings/master-control/dry-run",
            "start": "POST /api/settings/master-control/start",
            "stop": "POST /api/settings/master-control/stop",
            "export": "POST /api/settings/processing/export",
        },
    }


__all__ = [
    "LIVE_HARBOR",
    "HANDOFF_VERSION",
    "OPERATOR_STATUS_STUB",
    "OPERATOR_STATUS_MISSING_BINARY",
    "OPERATOR_STATUS_READY_OFFLINE",
    "REQUIRED_TEMPLATE_FILES",
    "template_search_roots",
    "find_template_dir",
    "ensure_operator_templates",
    "render_operator_liq",
    "resolve_liquidsoap_binary",
    "probe_liquidsoap_version",
    "validate_handoff_file",
    "validate_operator_liq",
    "dry_run",
    "start_stub",
    "stop_stub",
    "operator_status",
]

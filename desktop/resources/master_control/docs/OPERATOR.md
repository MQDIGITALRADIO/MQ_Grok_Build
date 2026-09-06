# Master Control operator path

Handoff **v3**. Paying-client honesty: this pack is the **operator path**
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

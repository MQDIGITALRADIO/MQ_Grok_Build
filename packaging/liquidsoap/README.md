# MQ Radio → Liquidsoap processing handoff

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

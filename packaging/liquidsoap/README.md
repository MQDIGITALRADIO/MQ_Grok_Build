# MQ Radio → Liquidsoap processing handoff

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

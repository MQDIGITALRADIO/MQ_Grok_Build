# Mac package size target — real substance

Target: **500MB–1GB+** DMG/ZIP so the product feels like broadcast software, not a thin Electron shell.

## Allowed bulk (real tools / media)
1. **ffmpeg + ffprobe** static builds (mp4/flac extract, segment cut, duration probe)
2. **Liquidsoap** runtime matching handoff v3 templates (Master Control path) — brew binary when available on macOS CI
3. **Demo / imaging beds** — legal IDs, sweepers, liners, VT/news/overnight pads (minutes of real noise-textured PCM WAV)
4. **Engine extras** — PyInstaller MQRadioEngine + Python deps already needed for CoreAudio bridges
5. **Operator docs** — README-INSTALL, Liquidsoap notes, Gatekeeper helper, Master Control pack

## Forbidden
- Zero-fill / random junk / duplicated empty trees to inflate size
- Pure sine pads that squash to near-nothing under ZIP/DMG DEFLATE
- Stuffing the commercial **music library** into the .app (stays on MQ Digital external drive / library root)

## Stage locally or in CI
```bash
./packaging/scripts/stage_mac_resources.sh
# optional: MQ_DEMO_BED_MB=850 MQ_RUNTIME_ARCH=arm64
```

Writes into `desktop/resources/{runtime,demo_beds,master_control}/` for electron-builder `extraResources`.

Beds are **noise-dominant** (pink/white/brown textured pads, sweeper whooshes, liners) so packaged ZIP/DMG stay in range — sine-only synth beds compressed away in v0.1.2-preview (~301 MB ZIP).

## CI hooks
- `packaging/scripts/stage_mac_resources.sh` before electron-builder (`MQ_DEMO_BED_MB=850`)
- electron-builder `extraResources` copies runtime + beds + master_control next to MQRadioEngine
- Post-build: soft-warn if ZIP or DMG &lt; **500MB**; always verify ffmpeg + demo_beds appear in ZIP listing
- Stage step soft-warns if demo beds &lt; 500MB
- Electron shell prepends `Resources/runtime` to PATH (`MQ_RADIO_RUNTIME_DIR`)

## Size plan (honest)
| Piece | Approx |
|-------|--------|
| Electron arm64 shell | ~150–200 MB |
| MQRadioEngine (PyInstaller) | ~40–80 MB |
| ffmpeg + ffprobe static | ~87 MB |
| Demo / imaging beds (CI ~850 MB raw, noise-textured) | ~450–650 MB in ZIP |
| Master Control / Liquidsoap assets (+ brew binary when present) | ~1–50 MB |
| **ZIP/DMG total** | **~500 MB–1 GB class** (aim ~650–900 MB) |

Desktop **0.1.2** release notes cite **~637MB** package substance class (ffmpeg + noise-textured demo beds + Master Control + engine after ZIP — music library remains external).

Music library remains external.

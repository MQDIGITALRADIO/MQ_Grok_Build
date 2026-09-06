# Mac package size target — real substance

Target: **500MB–1GB+** DMG/ZIP so the product feels like broadcast software, not a thin Electron shell.

## Allowed bulk (real tools / media)
1. **ffmpeg + ffprobe** static builds (mp4/flac extract, segment cut, duration probe)
2. **Liquidsoap** runtime matching handoff v3 templates (Master Control path) — brew binary when available on macOS CI
3. **Demo / imaging beds** — legal IDs, sweepers, beds, VT beds (minutes of real PCM WAV)
4. **Engine extras** — PyInstaller MQRadioEngine + Python deps already needed for CoreAudio bridges
5. **Operator docs** — README-INSTALL, Liquidsoap notes, Gatekeeper helper, Master Control pack

## Forbidden
- Zero-fill / random junk / duplicated empty trees to inflate size
- Stuffing the commercial **music library** into the .app (stays on MQ Digital external drive / library root)

## Stage locally or in CI
```bash
./packaging/scripts/stage_mac_resources.sh
# optional: MQ_DEMO_BED_MB=450 MQ_RUNTIME_ARCH=arm64
```

Writes into `desktop/resources/{runtime,demo_beds,master_control}/` for electron-builder `extraResources`.

## CI hooks
- `packaging/scripts/stage_mac_resources.sh` before electron-builder
- electron-builder `extraResources` copies runtime + beds + master_control next to MQRadioEngine
- Post-build: soft-warn if ZIP &lt; 400MB; always verify ffmpeg + demo_beds appear in ZIP listing
- Electron shell prepends `Resources/runtime` to PATH (`MQ_RADIO_RUNTIME_DIR`)

## Size plan (honest)
| Piece | Approx |
|-------|--------|
| Electron arm64 shell | ~150–200 MB |
| MQRadioEngine (PyInstaller) | ~40–80 MB |
| ffmpeg + ffprobe static | ~87 MB |
| Demo / imaging beds (CI ~420–450 MB) | ~400 MB |
| Master Control / Liquidsoap assets (+ brew binary when present) | ~1–50 MB |
| **ZIP/DMG total** | **~700 MB–1 GB class** |

Music library remains external.

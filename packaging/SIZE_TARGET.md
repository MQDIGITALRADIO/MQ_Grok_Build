# Mac package size target — real substance

Target: **500MB–1GB+** DMG/ZIP so the product feels like broadcast software, not a thin Electron shell.

## Allowed bulk (real tools / media)
1. **ffmpeg + ffprobe** static builds (mp4/flac extract, segment cut, duration probe)
2. **Liquidsoap** runtime matching handoff v3 templates (Master Control path)
3. **Demo / imaging beds** — legal IDs, sweepers, beds, VT beds (short WAV/MP3)
4. **Engine extras** — PyInstaller MQRadioEngine + Python deps already needed for CoreAudio bridges
5. **Operator docs** — README-INSTALL, Liquidsoap notes, Gatekeeper helper

## Forbidden
- Zero-fill / random junk / duplicated empty trees to inflate size
- Stuffing the commercial **music library** into the .app (stays on MQ Digital external drive / library root)

## CI hooks
- Stage runtimes into `desktop/resources/runtime/{ffmpeg,ffprobe,liquidsoap}/`
- electron-builder `extraResources` copy them next to MQRadioEngine
- Post-build: fail soft-warn if artifact &lt; 400MB; always verify ffmpeg binary exists in ZIP listing

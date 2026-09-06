# Bundled runtime (Mac)

- `ffmpeg/ffmpeg` + `ffprobe/ffprobe` — static binaries for ingest extract, segment cut, duration probe
- `liquidsoap/` — optional Liquidsoap binary when staged from Homebrew on macOS CI
- Electron `main.js` prepends this folder to PATH for MQRadioEngine

Do not replace with empty stubs. See `packaging/SIZE_TARGET.md`.

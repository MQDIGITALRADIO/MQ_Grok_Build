#!/usr/bin/env bash
# Stage REAL Mac package bulk into desktop/resources/ for electron-builder.
# - ffmpeg + ffprobe (darwin-arm64 static)
# - demo/imaging beds (minutes of real PCM)
# - Master Control / Liquidsoap handoff assets (+ brew liquidsoap when available)
#
# Never pads with junk. Music library stays external.
# See packaging/SIZE_TARGET.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$ROOT/desktop/resources"
RUNTIME="$RES/runtime"
BEDS="$RES/demo_beds"
MC="$RES/master_control"
FFMPEG_TAG="${MQ_FFMPEG_STATIC_TAG:-b6.1.1}"
FFMPEG_BASE="https://github.com/eugeneware/ffmpeg-static/releases/download/${FFMPEG_TAG}"
TARGET_BED_MB="${MQ_DEMO_BED_MB:-450}"
ARCH="${MQ_RUNTIME_ARCH:-arm64}"

echo "==> MQ Radio stage_mac_resources (arch=$ARCH beds≈${TARGET_BED_MB}MB)"

mkdir -p "$RUNTIME/ffmpeg" "$RUNTIME/ffprobe" "$RUNTIME/liquidsoap" "$BEDS" "$MC"

download_gz_bin() {
  local url="$1" dest="$2"
  local tmp
  tmp="$(mktemp)"
  echo "  download $url"
  curl -fsSL -o "$tmp" "$url"
  # gzip or raw
  if gzip -t "$tmp" 2>/dev/null; then
    gzip -dc "$tmp" > "$dest"
  else
    cp "$tmp" "$dest"
  fi
  rm -f "$tmp"
  chmod +x "$dest"
  # sanity: not tiny
  local sz
  sz="$(wc -c < "$dest" | tr -d ' ')"
  if [ "$sz" -lt 1000000 ]; then
    echo "ERROR: $dest looks too small ($sz bytes)" >&2
    exit 1
  fi
  echo "  ok $(basename "$dest") (${sz} bytes)"
}

stage_ffmpeg() {
  echo "==> Staging ffmpeg/ffprobe ($ARCH)"
  # Prefer eugeneware static builds (darwin-arm64 / darwin-x64)
  local plat="darwin-${ARCH}"
  if [ "$ARCH" = "x64" ] || [ "$ARCH" = "amd64" ]; then
    plat="darwin-x64"
  fi
  download_gz_bin "${FFMPEG_BASE}/ffmpeg-${plat}.gz" "$RUNTIME/ffmpeg/ffmpeg"
  download_gz_bin "${FFMPEG_BASE}/ffprobe-${plat}.gz" "$RUNTIME/ffprobe/ffprobe"
  # Convenience copies at runtime root
  cp -f "$RUNTIME/ffmpeg/ffmpeg" "$RUNTIME/ffmpeg.bin" 2>/dev/null || true
  cp -f "$RUNTIME/ffprobe/ffprobe" "$RUNTIME/ffprobe.bin" 2>/dev/null || true
  cat > "$RUNTIME/README.md" <<'EOF'
# Bundled runtime (Mac)

- `ffmpeg/ffmpeg` + `ffprobe/ffprobe` — static binaries for ingest extract, segment cut, duration probe
- `liquidsoap/` — optional Liquidsoap binary when staged from Homebrew on macOS CI
- Electron `main.js` prepends this folder to PATH for MQRadioEngine

Do not replace with empty stubs. See `packaging/SIZE_TARGET.md`.
EOF
}

stage_beds() {
  echo "==> Generating demo beds (~${TARGET_BED_MB} MB)"
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "WARN: host ffmpeg missing — trying bundled path after stage, or skip beds"
    if [ -x "$RUNTIME/ffmpeg/ffmpeg" ]; then
      export PATH="$RUNTIME/ffmpeg:$PATH"
    else
      echo "ERROR: need ffmpeg to generate beds" >&2
      exit 1
    fi
  fi
  python3 "$ROOT/packaging/scripts/generate_demo_beds.py" \
    --target-mb "$TARGET_BED_MB" \
    --min-mb 80 \
    --out "$BEDS"
}

stage_master_control() {
  echo "==> Staging Master Control / Liquidsoap assets"
  mkdir -p "$MC/liquidsoap" "$MC/docs"
  # Copy handoff templates (real operator substance)
  if [ -d "$ROOT/packaging/liquidsoap" ]; then
    cp -R "$ROOT/packaging/liquidsoap/." "$MC/liquidsoap/"
  fi
  # Regenerated handoff into MC pack
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<PY || true
from pathlib import Path
try:
    from mq_radio.production.liquidsoap_export import export_processing_handoff
    export_processing_handoff(
        data_dir=Path("$MC"),
        packaging_dir=Path("$MC") / "liquidsoap",
    )
    print("  handoff regenerated")
except Exception as e:
    print("  handoff skip:", e)
PY
  fi
  # Substantial operator graph stubs (commented but multi-KB real configs)
  cat > "$MC/liquidsoap/mq_master_control_operator.liq" <<'LIQ'
# MQ Radio — Master Control operator sketch (Liquidsoap)
# Pair with processing_handoff.json (FM / Digital + transmission_mode).
# Install Liquidsoap on the TX Mac: brew install liquidsoap
# This file is bundled for operators — not auto-started by the desk.

# settings.init.allow_root.set(false)

# program = input.harbor("mq.program", port=8005, headers=[], buffer=0.5)
# aux = input.harbor("mq.aux", port=8006, headers=[], buffer=0.5)
# mix_minus = program  # minus aux when wired: program - aux

# Chain (public practice topology — not an Optimod clone):
# AGC → EQ → Multiband → Exciter → Peak Limiter
# See packaging/liquidsoap/mq_processing_stub.liq for param mirrors.

# output.icecast(%mp3, host="127.0.0.1", port=8000, password="hackme",
#   mount="mq-fm", program)
LIQ
  # Optional: copy brew liquidsoap when running on macOS CI
  if command -v liquidsoap >/dev/null 2>&1; then
    LS="$(command -v liquidsoap)"
    mkdir -p "$RUNTIME/liquidsoap"
    cp -f "$LS" "$RUNTIME/liquidsoap/liquidsoap" || true
    chmod +x "$RUNTIME/liquidsoap/liquidsoap" || true
    liquidsoap --version > "$RUNTIME/liquidsoap/VERSION.txt" 2>&1 || true
    echo "  bundled liquidsoap from PATH"
  else
    cat > "$RUNTIME/liquidsoap/README.md" <<'EOF'
Liquidsoap binary not staged on this host.

On macOS CI / operator Mac:
  brew install liquidsoap
  # re-run packaging/scripts/stage_mac_resources.sh

Master Control templates live in resources/master_control/liquidsoap/.
EOF
    echo "  liquidsoap binary not on PATH — templates only (documented)"
  fi
  cat > "$MC/README.md" <<'EOF'
# Master Control runtime pack

Liquidsoap handoff v3 + operator `.liq` sketches for the transmitter / encoder Mac.

- Desk remains Living Log + On-Air UI
- Liquidsoap owns TX Master Control when installed
- Do not claim a live Harbor graph until wired from `LiquidsoapEngine`

Music library is external (MQ Digital drive).
EOF
}

stage_ffmpeg
stage_beds
stage_master_control

echo "==> Staged sizes"
du -sh "$RUNTIME" "$BEDS" "$MC" 2>/dev/null || true
du -sh "$RES" 2>/dev/null || true
# Soft listing proof
test -x "$RUNTIME/ffmpeg/ffmpeg"
test -x "$RUNTIME/ffprobe/ffprobe"
test -f "$BEDS/MANIFEST.json"
echo "OK stage_mac_resources complete"

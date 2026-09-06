#!/bin/bash
# MQ Radio — first-open Gatekeeper helper
# Double-click after installing from the CI ZIP/DMG (unsigned / ad-hoc signed).
# Clears quarantine, ad-hoc codesigns, then opens the app. Safe to re-run.

set -euo pipefail

APP="/Applications/MQ Radio.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANDIDATES=(
  "$APP"
  "$SCRIPT_DIR/MQ Radio.app"
  "$HOME/Applications/MQ Radio.app"
  "$HOME/Downloads/MQ Radio.app"
)

pick=""
for c in "${CANDIDATES[@]}"; do
  if [ -d "$c" ]; then
    pick="$c"
    break
  fi
done

if [ -z "$pick" ]; then
  echo "MQ Radio.app not found. Drag MQ Radio.app into Applications, then re-run this helper." >&2
  exit 1
fi

echo "Preparing: $pick"
# Clear Gatekeeper quarantine + ad-hoc re-sign (no Apple Developer cert yet)
xattr -cr "$pick" 2>/dev/null || true
codesign --force --deep --sign - "$pick" 2>/dev/null || true

open "$pick" || open -a "$pick"
exit 0

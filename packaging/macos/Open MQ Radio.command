#!/bin/bash
# MQ Radio — first-open Gatekeeper helper
# Double-click after installing from the CI ZIP/DMG (unsigned / ad-hoc signed).
# Clears quarantine, ad-hoc codesigns, then opens the app. Safe to re-run.
#
# If macOS says the app is "damaged", this is the normal fix until Apple
# Developer ID notarization ships (still Missing on the acceptance matrix).

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
  echo "" >&2
  echo "MQ Radio.app not found." >&2
  echo "1) Unzip the Mac ZIP (or open the DMG)" >&2
  echo "2) Drag MQ Radio.app into Applications" >&2
  echo "3) Double-click this helper again (Open MQ Radio.command)" >&2
  echo "" >&2
  if [ -f "$SCRIPT_DIR/README-INSTALL.txt" ]; then
    echo "See: $SCRIPT_DIR/README-INSTALL.txt" >&2
  fi
  exit 1
fi

echo "Preparing: $pick"
echo "(Unsigned / ad-hoc CI build — Gatekeeper quarantine clear is expected.)"
if [ -f "$SCRIPT_DIR/README-INSTALL.txt" ]; then
  echo "Install notes: $SCRIPT_DIR/README-INSTALL.txt"
fi

# Clear Gatekeeper quarantine + ad-hoc re-sign (no Apple Developer cert yet)
xattr -cr "$pick" 2>/dev/null || true
codesign --force --deep --sign - "$pick" 2>/dev/null || true

echo "Opening…"
open "$pick" || open -a "$pick"
echo "If macOS still blocks: right-click MQ Radio → Open → confirm, or"
echo "System Settings → Privacy & Security → Open Anyway."
echo "Empty Living Log / decks on first launch are normal — Import → Clocks → PLAY."
exit 0

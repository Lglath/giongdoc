#!/usr/bin/env bash
# Build packaging/assets/GiongDoc.icns from a 1024px PNG (macOS only: sips + iconutil).
# Usage: packaging/make_icns.sh [source.png] [output.icns]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$HERE/assets/icon_1024.png}"
OUT="${2:-$HERE/assets/GiongDoc.icns}"

if [[ ! -f "$SRC" ]]; then
  echo "==> Icon PNG not found, generating it with make_icon.py"
  python3 "$HERE/make_icon.py" "$SRC"
fi

for tool in sips iconutil; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found (this script must run on macOS)." >&2; exit 1; }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ICONSET="$TMP/GiongDoc.iconset"
mkdir -p "$ICONSET"

echo "==> Rendering iconset sizes from $SRC"
for size in 16 32 128 256 512; do
  double=$((size * 2))
  sips -z "$size" "$size" "$SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z "$double" "$double" "$SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done

mkdir -p "$(dirname "$OUT")"
iconutil -c icns "$ICONSET" -o "$OUT"
echo "==> Wrote $OUT"

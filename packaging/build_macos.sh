#!/usr/bin/env bash
# =============================================================================
# GiongDoc – end-to-end macOS build: venv -> icon -> ffmpeg -> PyInstaller
#            -> codesign -> DMG -> (optional) notarization.
#
# Usage (from anywhere):   bash packaging/build_macos.sh
# Output:                  dist/GiongDoc.app, dist/GiongDoc-<ver>-<arch>.dmg
#
# Optional environment variables:
#   PYTHON           python interpreter to use (must be >= 3.11)
#   GIONGDOC_VERSION version string (default 1.0.0)
#   FFMPEG_SRC       path to an ffmpeg binary to embed (default: Homebrew's)
#   FFMPEG_URL       URL of a zip/tar containing a *static* macOS ffmpeg; used
#                    only when no local ffmpeg is found
#   SKIP_FFMPEG=1    build without embedding ffmpeg
#   SKIP_DMG=1       stop after building/signing the .app
#   WITH_CUSTOM_VOICE=1  also install + bundle torch/f5-tts (multi-GB app)
#   Notarization (all four required, otherwise skipped; ad-hoc signing used):
#   DEVELOPER_ID     e.g. "Developer ID Application: Nguyen Van Cuong (ABCDE12345)"
#   APPLE_ID         Apple ID e-mail
#   TEAM_ID          10-character team id
#   APP_PASSWORD     app-specific password (appleid.apple.com)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$ROOT/packaging"
cd "$ROOT"

APP_NAME="GiongDoc"
VERSION="${GIONGDOC_VERSION:-1.0.0}"
ARCH="$(uname -m)"              # arm64 (Apple Silicon) or x86_64 (Intel)
VENV="$ROOT/.venv-build"
DIST="$ROOT/dist"
WORK="$ROOT/build/pyinstaller"
APP="$DIST/$APP_NAME.app"
DMG="$DIST/$APP_NAME-$VERSION-$ARCH.dmg"
VENDOR="$PKG/vendor"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
step "1/8 Checking environment"
[[ "$(uname -s)" == "Darwin" ]] || die "This script must run on macOS."
info "macOS $(sw_vers -productVersion), arch $ARCH, version $VERSION"

py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }

if [[ -n "${PYTHON:-}" ]]; then
  py_ok "$PYTHON" || die "PYTHON=$PYTHON is not Python 3.11+."
else
  PYTHON=""
  candidates=(python3.13 python3.12 python3.11 python3)
  if command -v brew >/dev/null 2>&1; then
    for v in 3.13 3.12 3.11; do
      candidates+=("$(brew --prefix)/opt/python@$v/bin/python$v")
    done
  fi
  for c in "${candidates[@]}"; do
    if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then PYTHON="$c"; break; fi
  done
  [[ -n "$PYTHON" ]] || die "Python 3.11+ not found. Install it with: brew install python@3.11"
fi
info "Python: $PYTHON ($("$PYTHON" --version 2>&1))"

# -----------------------------------------------------------------------------
step "2/8 Creating build venv ($VENV) and installing dependencies"
if [[ ! -x "$VENV/bin/python" ]] || ! py_ok "$VENV/bin/python"; then
  rm -rf "$VENV"
  "$PYTHON" -m venv "$VENV"
fi
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade --quiet pip wheel
"$VPY" -m pip install --quiet -r requirements.txt "pyinstaller>=6.6"
if [[ "${WITH_CUSTOM_VOICE:-0}" == "1" ]]; then
  info "WITH_CUSTOM_VOICE=1 -> installing requirements-custom-voice.txt (large download)"
  "$VPY" -m pip install --quiet -r requirements-custom-voice.txt
  export GIONGDOC_BUNDLE_CUSTOM_VOICE=1
fi
info "PyInstaller $("$VPY" -m PyInstaller --version)"

# -----------------------------------------------------------------------------
step "3/8 Building app icon"
if [[ ! -f "$PKG/assets/icon_1024.png" ]]; then
  "$VPY" "$PKG/make_icon.py" "$PKG/assets/icon_1024.png"
fi
bash "$PKG/make_icns.sh" "$PKG/assets/icon_1024.png" "$PKG/assets/GiongDoc.icns"

# -----------------------------------------------------------------------------
step "4/8 Preparing ffmpeg"
mkdir -p "$VENDOR"
rm -f "$VENDOR/ffmpeg"
FFMPEG_FOUND=""
if [[ "${SKIP_FFMPEG:-0}" == "1" ]]; then
  warn "SKIP_FFMPEG=1: the app will rely on a system ffmpeg (or GIONGDOC_FFMPEG)."
else
  src="${FFMPEG_SRC:-}"
  if [[ -z "$src" ]] && command -v brew >/dev/null 2>&1 && [[ -x "$(brew --prefix)/bin/ffmpeg" ]]; then
    src="$(brew --prefix)/bin/ffmpeg"
  fi
  if [[ -z "$src" ]] && command -v ffmpeg >/dev/null 2>&1; then
    src="$(command -v ffmpeg)"
  fi

  if [[ -n "$src" ]]; then
    src="$("$VPY" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$src")"
    info "Copying ffmpeg from $src"
    cp "$src" "$VENDOR/ffmpeg"
  elif [[ -n "${FFMPEG_URL:-}" ]]; then
    info "Downloading static ffmpeg from $FFMPEG_URL"
    tmpd="$(mktemp -d)"
    curl -fsSL "$FFMPEG_URL" -o "$tmpd/ffmpeg.archive"
    case "$FFMPEG_URL" in
      *.zip|*/zip) (cd "$tmpd" && unzip -q ffmpeg.archive) ;;
      *)           (cd "$tmpd" && tar -xf ffmpeg.archive) ;;
    esac
    found="$(find "$tmpd" -type f -name ffmpeg -perm -u+x | head -n 1)"
    [[ -n "$found" ]] || die "No ffmpeg executable inside $FFMPEG_URL"
    cp "$found" "$VENDOR/ffmpeg"
    rm -rf "$tmpd"
  else
    warn "No ffmpeg found. Install it (brew install ffmpeg) or set FFMPEG_SRC / FFMPEG_URL."
    warn "Continuing without embedded ffmpeg: WAV export works, MP3/M4A needs a system ffmpeg."
  fi

  if [[ -f "$VENDOR/ffmpeg" ]]; then
    chmod 755 "$VENDOR/ffmpeg"
    xattr -c "$VENDOR/ffmpeg" 2>/dev/null || true
    archs="$(lipo -archs "$VENDOR/ffmpeg" 2>/dev/null || echo unknown)"
    info "ffmpeg architectures: $archs"
    [[ "$archs" == *"$ARCH"* || "$archs" == unknown ]] || die "ffmpeg is $archs but this build is $ARCH."
    nonsys="$(otool -L "$VENDOR/ffmpeg" | tail -n +2 | awk '{print $1}' | grep -vE '^(/usr/lib/|/System/)' || true)"
    if [[ -n "$nonsys" ]]; then
      info "ffmpeg links $(echo "$nonsys" | wc -l | tr -d ' ') non-system dylibs (Homebrew build);"
      info "PyInstaller will collect them into the bundle and rewrite their load paths."
    else
      info "ffmpeg is static (only system libraries)."
    fi
    FFMPEG_FOUND=1
    export GIONGDOC_FFMPEG_SRC="$VENDOR/ffmpeg"
  fi
fi

# -----------------------------------------------------------------------------
step "5/8 Running PyInstaller"
rm -rf "${APP:?}" "${DIST:?}/${APP_NAME:?}" "${WORK:?}"
GIONGDOC_VERSION="$VERSION" PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$VPY" -m PyInstaller --noconfirm --clean \
    --distpath "$DIST" --workpath "$WORK" \
    "$PKG/GiongDoc.spec"
[[ -d "$APP" ]] || die "PyInstaller did not produce $APP"
rm -rf "${DIST:?}/$APP_NAME"   # intermediate onedir folder, not needed

# Make sure ffmpeg is reachable at Contents/Resources/bin/ffmpeg
if [[ -n "$FFMPEG_FOUND" ]]; then
  RES_FF="$APP/Contents/Resources/bin/ffmpeg"
  if [[ ! -e "$RES_FF" ]]; then
    info "Placing ffmpeg at Contents/Resources/bin/ffmpeg"
    mkdir -p "$(dirname "$RES_FF")"
    cp "$VENDOR/ffmpeg" "$RES_FF"
  fi
  if "$RES_FF" -hide_banner -version >/dev/null 2>&1; then
    info "Embedded ffmpeg runs OK: $("$RES_FF" -hide_banner -version | head -n 1)"
  else
    warn "Embedded ffmpeg failed to run; check 'otool -L \"$RES_FF\"'."
    [[ "${STRICT_FFMPEG:-0}" == "1" ]] && die "STRICT_FFMPEG=1: embedded ffmpeg must run."
  fi
  if otool -L "$RES_FF" | grep -qE '/(opt/homebrew|usr/local)/'; then
    warn "Embedded ffmpeg still references Homebrew paths; it will only run on Macs with Homebrew ffmpeg."
    warn "Use a static ffmpeg (FFMPEG_URL or FFMPEG_SRC) for a fully portable app."
    [[ "${STRICT_FFMPEG:-0}" == "1" ]] && die "STRICT_FFMPEG=1: embedded ffmpeg must not depend on Homebrew."
  fi
fi

# -----------------------------------------------------------------------------
step "6/8 Code signing"
xattr -cr "$APP"
NOTARIZE=0
if [[ -n "${DEVELOPER_ID:-}" && -n "${APPLE_ID:-}" && -n "${TEAM_ID:-}" && -n "${APP_PASSWORD:-}" ]]; then
  NOTARIZE=1
fi
if [[ -n "${DEVELOPER_ID:-}" ]]; then
  info "Signing with Developer ID: $DEVELOPER_ID (hardened runtime)"
  codesign --force --deep --timestamp --options runtime \
    --entitlements "$PKG/entitlements.plist" \
    -s "$DEVELOPER_ID" "$APP"
else
  info "No DEVELOPER_ID set -> ad-hoc signature (app runs locally; Gatekeeper will warn on other Macs)"
  codesign --force --deep -s - "$APP"
fi
codesign --verify --deep --strict --verbose=1 "$APP"

if [[ "${SKIP_DMG:-0}" == "1" ]]; then
  step "Done (SKIP_DMG=1): $APP"
  exit 0
fi

# -----------------------------------------------------------------------------
step "7/8 Creating DMG"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
case "$ARCH" in arm64) ARCH_LABEL="chip M";; *) ARCH_LABEL="Intel";; esac
hdiutil create -volname "$APP_NAME $VERSION ($ARCH_LABEL)" -srcfolder "$STAGE" \
  -ov -format UDZO -fs HFS+ "$DMG" >/dev/null
if [[ -n "${DEVELOPER_ID:-}" ]]; then
  codesign --force --timestamp -s "$DEVELOPER_ID" "$DMG"
fi
info "DMG: $DMG ($(du -h "$DMG" | cut -f1))"

# -----------------------------------------------------------------------------
step "8/8 Notarization"
if [[ "$NOTARIZE" == "1" ]]; then
  info "Submitting to Apple notary service (this can take several minutes)..."
  xcrun notarytool submit "$DMG" \
    --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PASSWORD" \
    --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  spctl --assess --type open --context context:primary-signature -v "$DMG" || true
  info "Notarized and stapled."
else
  info "Skipped (set DEVELOPER_ID, APPLE_ID, TEAM_ID, APP_PASSWORD to notarize)."
fi

step "Build complete"
info "App: $APP"
info "DMG: $DMG"

#!/bin/bash
# Build Tingxie.app — a real macOS app bundle for the dictation daemon, so the
# TCC permissions (Microphone / Accessibility / Input Monitoring) attach to
# the bundle instead of the Homebrew python binary. See setup.py for details.
#
#   ./make-app.sh              build into dist/Tingxie.app
#   VENV=/path/to/venv ./make-app.sh    use a different venv
#
# The models/ dir (230MB) stays OUTSIDE the bundle. The app finds it via
# $TINGXIE_HOME (set in com.tingxie.dictation.plist) or the symlink this
# script drops in ~/Library/Application Support/Tingxie (for Finder launches).
set -euo pipefail
cd "$(dirname "$0")"

# The venv and models live in the main checkout; fall back to it when
# building from a git worktree that doesn't have them.
MAIN_CHECKOUT="$HOME/projects/whisper"
VENV="${VENV:-$PWD/.venv}"
[ -x "$VENV/bin/python" ] || VENV="$MAIN_CHECKOUT/.venv"
PY="$VENV/bin/python"
[ -x "$PY" ] || { echo "error: no venv found (tried \$VENV, ./.venv, $MAIN_CHECKOUT/.venv)"; exit 1; }

MODELS_DIR="$PWD/models"
[ -d "$MODELS_DIR" ] || MODELS_DIR="$MAIN_CHECKOUT/models"

echo "==> venv:   $VENV"
echo "==> models: $MODELS_DIR"

# py2app is build-only (pure python) — installing it into the venv is safe
# for the running app.
"$PY" -c "import py2app" 2>/dev/null || "$VENV/bin/pip" install --quiet py2app

echo "==> building (py2app)…"
rm -rf build dist
"$PY" setup.py py2app >/tmp/tingxie-build.log 2>&1 || {
    echo "build FAILED — last 40 lines of /tmp/tingxie-build.log:"
    tail -40 /tmp/tingxie-build.log
    exit 1
}

# Ad-hoc sign the whole bundle so TCC gets a stable code identity.
echo "==> codesigning (ad-hoc)…"
codesign --force --deep --sign - dist/Tingxie.app 2>/dev/null

# Models symlink for Finder launches (LaunchAgent sets TINGXIE_HOME instead).
APP_SUPPORT="$HOME/Library/Application Support/Tingxie"
mkdir -p "$APP_SUPPORT"
[ -e "$APP_SUPPORT/models" ] || ln -s "$MODELS_DIR" "$APP_SUPPORT/models"

echo "==> done: dist/Tingxie.app ($(du -sh dist/Tingxie.app | cut -f1))"
echo
echo "Next steps (see README 'Tingxie.app' section):"
echo "  ditto dist/Tingxie.app /Applications/Tingxie.app"
echo "  launchctl bootout gui/\$UID/com.whisperflow.dictation   # stop the old one"
echo "  cp com.tingxie.dictation.plist ~/Library/LaunchAgents/"
echo "  launchctl bootstrap gui/\$UID ~/Library/LaunchAgents/com.tingxie.dictation.plist"

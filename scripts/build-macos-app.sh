#!/bin/zsh
# Build TracePlotter.app (Apple Silicon) and a GitHub-ready zip.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${TRACEPLOTTER_PYTHON:-python3.12}"
DIST_DIR="${TRACEPLOTTER_DIST:-$ROOT/dist}"
BUILD_DIR="${TRACEPLOTTER_BUILD:-$ROOT/build}"
SPEC="$ROOT/packaging/macos/traceplotter.spec"

if [[ ! -x .venv/bin/python ]]; then
  command -v "$PYTHON" >/dev/null || {
    print -u2 "Need arm64 Python 3.12+ (set TRACEPLOTTER_PYTHON if needed)."
    exit 1
  }
  "$PYTHON" -m venv .venv
fi

ARCH="$(".venv/bin/python" -c 'import platform; print(platform.machine())')"
if [[ "$ARCH" != "arm64" ]]; then
  print -u2 "Refusing to package under $ARCH Python; use native arm64 Python."
  exit 1
fi

VERSION="$(
  .venv/bin/python - <<'PY'
import tomllib
from pathlib import Path
print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"])
PY
)"
ZIP_NAME="TracePlotter-${VERSION}-macos-arm64.zip"

.venv/bin/python -m pip install -q -U pip
.venv/bin/python -m pip install -q -e '.[test]'
.venv/bin/python -m pip install -q 'pyinstaller>=6.0'

rm -rf "$DIST_DIR/TracePlotter" "$DIST_DIR/TracePlotter.app" "$BUILD_DIR/traceplotter"
.venv/bin/pyinstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  "$SPEC"

APP="$DIST_DIR/TracePlotter.app"
if [[ ! -d "$APP" ]]; then
  print -u2 "Build failed: $APP missing"
  exit 1
fi

# Drop Finder quarantine noise on the built tree before zipping.
xattr -cr "$APP" 2>/dev/null || true

ZIP="$DIST_DIR/$ZIP_NAME"
rm -f "$ZIP"
(
  cd "$DIST_DIR"
  /usr/bin/ditto -c -k --keepParent TracePlotter.app "$ZIP_NAME"
)

print "Built: $APP"
print "Zip:   $ZIP"
print "Size:  $(du -sh "$APP" | awk '{print $1}') / $(du -sh "$ZIP" | awk '{print $1}')"

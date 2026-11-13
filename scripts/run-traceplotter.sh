#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${TRACEPLOTTER_PYTHON:-${LAB_PINGPLOT_PYTHON:-python3.12}}"
if [[ ! -x .venv/bin/python ]]; then
  command -v "$PYTHON" >/dev/null || {
    print -u2 "TracePlotter requires an arm64 Python 3.12+ (set TRACEPLOTTER_PYTHON if needed)."
    exit 1
  }
  "$PYTHON" -m venv .venv
fi

ARCH="$(".venv/bin/python" -c 'import platform; print(platform.machine())')"
if [[ "$ARCH" != "arm64" ]]; then
  print -u2 "Refusing to run under $ARCH Python; install/use native arm64 Python."
  exit 1
fi

if [[ "${TRACEPLOTTER_SKIP_INSTALL:-${LAB_PINGPLOT_SKIP_INSTALL:-0}}" != "1" ]]; then
  .venv/bin/python -m pip install -q -e '.[test]'
fi

exec .venv/bin/python -m traceplotter.app "$@"

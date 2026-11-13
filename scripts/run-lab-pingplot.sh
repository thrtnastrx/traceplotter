#!/bin/zsh
# Compatibility shim — use run-traceplotter.sh
exec "$(cd "$(dirname "$0")" && pwd)/run-traceplotter.sh" "$@"

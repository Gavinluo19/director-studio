#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$STUDIO_ROOT/scripts/start.sh" "$@"

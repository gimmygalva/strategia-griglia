#!/bin/bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec /bin/bash "$PROJECT_ROOT/scripts/build-macos.sh"

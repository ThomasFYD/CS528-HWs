#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export HW5_PROJECT_ID=dazzling-seat-508219-j3
PYTHON="${HW5_PYTHON:-python3}"
if [ "${1:-}" = --plan ]; then exec "$PYTHON" infra.py cleanup-plan; fi
if [ "$#" -ne 0 ]; then echo 'Usage: bash cleanup.sh [--plan]'; exit 2; fi
exec "$PYTHON" infra.py cleanup

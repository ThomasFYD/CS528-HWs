#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# Required by the grader: never infer this from the grader's gcloud config.
export HW5_PROJECT_ID=dazzling-seat-508219-j3
PYTHON="${HW5_PYTHON:-python3}"
if [ "${1:-}" = --plan ]; then exec "$PYTHON" infra.py plan; fi
if [ "$#" -ne 0 ]; then echo 'Usage: bash setup.sh [--plan]'; exit 2; fi
setup_cloud_sql() { "$PYTHON" infra.py sql; }
"$PYTHON" infra.py prepare
setup_cloud_sql
"$PYTHON" infra.py deploy
"$PYTHON" infra.py status
echo 'Startup installation may still be running. Follow README.md for verification.'

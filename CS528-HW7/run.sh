#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-}"
RUN_TAG="${2:-$(date -u +%Y%m%d-%H%M%S)}"
if [[ ! "$RUN_TAG" =~ ^[a-z0-9][-a-z0-9]*[a-z0-9]$ ]]; then
  printf '%s\n' 'Run tag must contain lowercase letters, numbers and hyphens.' >&2
  exit 2
fi
PROJECT=dazzling-seat-508219-j3
BUCKET=gs://cs528-hw7-yf-2026
case "$MODE" in
  local)
    META="results/local-$RUN_TAG/metadata.json"
    .venv/bin/python -u run_hw7.py \
      --runner=apache_beam.runners.portability.fn_api_runner.FnApiRunner \
      --direct_running_mode=multi_threading --direct_num_workers=8 \
      --project="$PROJECT" --output="results/local-$RUN_TAG/output" \
      --metadata="$META"
    ;;
  cloud)
    META="results/cloud-$RUN_TAG/metadata.json"
    .venv/bin/python -u run_hw7.py --runner=DataflowRunner \
      --project="$PROJECT" --region=us-central1 --job_name="cs528-hw7-$RUN_TAG" \
      --service_account_email="cs528-hw7-worker@$PROJECT.iam.gserviceaccount.com" \
      --temp_location="$BUCKET/tmp/$RUN_TAG" --staging_location="$BUCKET/staging/$RUN_TAG" \
      --output="$BUCKET/runs/$RUN_TAG/output" --metadata="$META" \
      --setup_file=./setup.py --num_workers=2 --max_num_workers=2 \
      --autoscaling_algorithm=NONE --machine_type=e2-standard-2 --disk_size_gb=30 \
      --sdk_worker_parallelism=1 --network=default --labels=assignment=cs528-hw7
    ;;
  *) printf '%s\n' 'Usage: bash run.sh local|cloud [unique-run-tag]' >&2; exit 2 ;;
esac
.venv/bin/python show_results.py --metadata="$META"

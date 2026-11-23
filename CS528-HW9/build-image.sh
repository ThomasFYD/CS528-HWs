#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/settings.sh"
gc() { "${GC[@]}" "$@"; }
tag=$(cat Dockerfile requirements.txt web_server.py browser-demo.html | shasum -a 256 | cut -c1-24)
if ! gc artifacts docker images describe "$IMAGE:$tag" >/dev/null 2>&1; then
  gc builds submit . --region="$REGION" --tag="$IMAGE:$tag" --service-account="projects/$PROJECT/serviceAccounts/$BUILDER" \
    --gcs-source-staging-dir="gs://$STAGING/source" --gcs-log-dir="gs://$STAGING/logs" --timeout=12m
fi
digest=$(gc artifacts docker images describe "$IMAGE:$tag" --format='value(image_summary.digest)')
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]
printf '%s@%s\n' "$IMAGE" "$digest" > "$STATE/image"

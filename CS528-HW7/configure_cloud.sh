#!/usr/bin/env bash
set -euo pipefail
PROJECT=dazzling-seat-508219-j3
WORKER=cs528-hw7-worker@${PROJECT}.iam.gserviceaccount.com
BUCKET=gs://cs528-hw7-yf-2026

gcloud services enable dataflow.googleapis.com compute.googleapis.com storage.googleapis.com iam.googleapis.com --project="$PROJECT"
if ! gcloud iam service-accounts describe "$WORKER" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create cs528-hw7-worker --display-name='CS528 HW7 Dataflow worker' --project="$PROJECT"
fi
if ! gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "$BUCKET" --project="$PROJECT" --location=us-central1 \
    --uniform-bucket-level-access --public-access-prevention --soft-delete-duration=0
fi
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$WORKER" \
  --role=roles/dataflow.worker --condition=None --format='value(etag)'
gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$WORKER" \
  --role=roles/storage.objectAdmin --condition=None --format='value(etag)'
gcloud storage buckets add-iam-policy-binding gs://cs528-hw2-yf-2026 --member="serviceAccount:$WORKER" \
  --role=roles/storage.objectViewer --condition=None --format='value(etag)'

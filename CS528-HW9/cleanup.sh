#!/usr/bin/env bash
# Remove the deployment recorded in .state. Rerun after a partial cleanup.
set -euo pipefail
source "$(dirname "$0")/settings.sh"
gc() { "${GC[@]}" "$@"; }
exists() {
  local error
  if error=$(gc "$@" 2>&1 >/dev/null); then return 0; fi
  case "$error" in *NOT_FOUND*|*"was not found"*|*"not found"*|*"does not exist"*|*"404"*) return 1 ;; esac
  printf '%s\n' "$error" >&2; exit 1
}
gc projects describe "$PROJECT" --format='value(projectId)'
if exists container clusters describe "$RUN" --zone="$ZONE"; then
  gc container clusters get-credentials "$RUN" --zone="$ZONE"
  kubectl -n "$RUN" delete service web --ignore-not-found --wait=true --timeout=10m
  gc container clusters delete "$RUN" --zone="$ZONE"
fi
if exists compute instances describe "$VM" --zone="$ZONE"; then gc compute instances delete "$VM" --zone="$ZONE" --delete-disks=boot; fi
if exists compute firewall-rules describe "$RUN-iap"; then gc compute firewall-rules delete "$RUN-iap"; fi
if exists compute networks subnets describe "$SUBNET" --region="$REGION"; then gc compute networks subnets delete "$SUBNET" --region="$REGION"; fi
if exists compute networks describe "$NETWORK"; then gc compute networks delete "$NETWORK"; fi
if exists pubsub subscriptions describe "$SUB"; then gc pubsub subscriptions delete "$SUB"; fi
if exists pubsub topics describe "$TOPIC"; then gc pubsub topics delete "$TOPIC"; fi
if exists artifacts repositories describe "$RUN" --location="$REGION"; then gc artifacts repositories delete "$RUN" --location="$REGION"; fi
if exists storage buckets describe "gs://$STAGING"; then gc storage rm --recursive "gs://$STAGING"; fi
remove_if_bound() {
  local identity=$1 role=$2 member=$3 policy
  shift 3
  policy=$(gc "$@" get-iam-policy "$identity" --format=json)
  if python3 -c 'import json,sys; p=json.load(sys.stdin); sys.exit(not any(b["role"]==sys.argv[1] and sys.argv[2] in b["members"] and "condition" not in b for b in p.get("bindings",[])))' "$role" "$member" <<< "$policy"; then
    gc "$@" remove-iam-policy-binding "$identity" --role="$role" --member="$member" --condition=None >/dev/null
  fi
}
remove_if_bound "$WEB_SA" roles/iam.workloadIdentityUser "$WI_MEMBER" iam service-accounts
remove_if_bound "$PROJECT" roles/container.defaultNodeServiceAccount "serviceAccount:$NODE" projects
for sa in "$NODE" "$BUILDER"; do
  if exists iam service-accounts describe "$sa"; then gc iam service-accounts delete "$sa"; fi
done
printf 'Cleanup completed for %s.\n' "$RUN"

# Shared by the deployment, evidence and cleanup scripts. Bash 3+.
cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT=$(pwd -P)
STATE="$ROOT/.state"
PROJECT=${HW9_PROJECT:-dazzling-seat-508219-j3}
ZONE=${HW9_ZONE:-us-central1-a}
REGION=${ZONE%-*}
BUCKET=${HW9_BUCKET:-cs528-hw2-yf-2026}
WEB_SA=${HW9_WEB_SA:-cs528-hw4-web-sa@$PROJECT.iam.gserviceaccount.com}
REPORTER_SA=${HW9_REPORTER_SA:-cs528-hw4-reporter-sa@$PROJECT.iam.gserviceaccount.com}
CLIENT=${HW9_CLIENT:-$ROOT/../CS528-HW4/client/http-client}
GC=(gcloud --project="$PROJECT" --quiet)
if [[ ! -f "$STATE/run" ]]; then
  [[ ${INITIALIZE:-no} == yes ]] || { echo "No local HW9 deployment state." >&2; exit 1; }
  mkdir -p "$STATE"; chmod 700 "$STATE"
  (set -C; printf 'hw9-%s\n%s\n%s\n%s\n%s\n%s\n' "$(openssl rand -hex 5)" "$PROJECT" "$ZONE" "$BUCKET" "$WEB_SA" "$REPORTER_SA" > "$STATE/run")
fi
RUN=$(sed -n '1p' "$STATE/run")
[[ "$RUN" =~ ^hw9-[a-f0-9]{10}$ && "$(tail -n +2 "$STATE/run")" == "$(printf '%s\n' "$PROJECT" "$ZONE" "$BUCKET" "$WEB_SA" "$REPORTER_SA")" ]] || {
  echo "Project, zone, data bucket or service accounts differ from the original run." >&2; exit 1;
}
NODE="$RUN-node@$PROJECT.iam.gserviceaccount.com"
BUILDER="$RUN-build@$PROJECT.iam.gserviceaccount.com"
NETWORK="$RUN-net"; SUBNET="$RUN-subnet"; VM="$RUN-vm"
TOPIC="$RUN-forbidden"; SUB="$RUN-sub"
STAGING="$PROJECT-$RUN"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$RUN/web"
WI_MEMBER="serviceAccount:$PROJECT.svc.id.goog[$RUN/web]"
export KUBECONFIG="$STATE/kubeconfig"
SSH=(--zone="$ZONE" --tunnel-through-iap --ssh-key-file="$STATE/ssh")
remote() { "${GC[@]}" compute ssh "$VM" "${SSH[@]}" --command="$1"; }
copy_to_vm() { "${GC[@]}" compute scp "${SSH[@]}" "$@" "$VM:~/"; }

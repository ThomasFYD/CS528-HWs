#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/settings.sh"
run_time=$(date -u +%Y%m%dT%H%M%SZ)
start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
out="$ROOT/results/$run_time"; mkdir -p "$ROOT/results"; mkdir "$out"
k() { kubectl -n "$RUN" "$@"; }
ip=$(k get service web -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$ip"
base="http://$ip"
k get deployment,pod,service -o wide > "$out/kubernetes.txt"
k get deployment/web -o json > "$out/deployment.json"
k get service/web -o json > "$out/service.json"
k get pod -l app=web -o json > "$out/pods.json"
"${GC[@]}" container clusters describe "$RUN" --zone="$ZONE" --format='json(name,status,currentMasterVersion,location,currentNodeCount,workloadIdentityConfig,nodeConfig.machineType,nodeConfig.serviceAccount)' > "$out/cluster.json"
"${GC[@]}" compute instances describe "$VM" --zone="$ZONE" --format='json(name,status,zone,machineType,cpuPlatform,serviceAccounts.email)' > "$out/vm.json"
cp "$STATE/image" "$out/image.txt"
url="$base/data/0.html?proof=$run_time"
curl -fsS --max-time 30 "$url" -o "$out/get.html"
curl -fsS --max-time 30 -H 'Content-Type: application/json' -d '{"filename":"data/0.html"}' "$base/" -o "$out/post.html"
"${GC[@]}" storage cp "gs://$BUCKET/data/0.html" "$out/source.html"
(cd "$out"; cmp source.html get.html; cmp source.html post.html; shasum -a 256 source.html get.html post.html > hashes.txt)
request() {
  local label=$1 expected=$2 observed; shift 2
  observed=$(curl --silent --show-error --max-time 30 -D "$out/$label.headers" -o "$out/$label.body" -w '%{http_code}' "$@")
  printf '%-10s %s\n' "$label" "$observed" | tee -a "$out/http-statuses.txt"
  [[ "$observed" == "$expected" ]]
}
request missing 404 "$base/data/hw9-missing-$run_time.html"
for method in PUT DELETE OPTIONS TRACE PATCH; do request "$method" 501 -X "$method" "$url"; done
request HEAD 501 --head "$url"
request CONNECT 501 -X CONNECT --request-target "$ip:80" "$base/"
request forbidden 400 -H 'X-country: Iran' "$url"
remote "set -eu; hostname; uname -m; getconf GNU_LIBC_VERSION; sha256sum ~/http-client; systemctl is-active hw9-reporter" > "$out/client-vm.txt"
remote "set -eu; timeout 15m ~/http-client -d '$ip' -p 80 -b '/$BUCKET' -w data -n 300 -i 11999 -r 528 -t 30 -v > ~/client-$run_time.txt; gzip -f ~/client-$run_time.txt"
"${GC[@]}" compute scp "${SSH[@]}" "$VM:~/client-$run_time.txt.gz" "$out/client.txt.gz"
filter="logName=\"projects/$PROJECT/logs/cs528-hw9-web\" AND severity>=WARNING AND timestamp>=\"$start\""
# Ingestion is asynchronous. Re-query until the exact test requests and reporter event match.
for attempt in {1..12}; do
  "${GC[@]}" logging read "$filter" --limit=1000 --format='json(jsonPayload,severity,timestamp,insertId)' > "$out/cloud-errors.json"
  remote "sudo journalctl -u hw9-reporter --since '$start' --no-pager -o cat" > "$out/reporter.txt"
  if python3 verify_results.py "$out" "$ip"; then exit 0; fi
  sleep 5
done
exit 1

#!/bin/bash
# All VM configuration occurs here, through --metadata-from-file=startup-script.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
BASE=/opt/cs528-hw5
META=http://metadata.google.internal/computeMetadata/v1/instance/attributes
meta() { curl --fail --silent --show-error -H Metadata-Flavor:Google "$META/$1"; }
ROLE="$(meta hw5-role)"
DIGEST="$(meta hw5-source-sha256)"
case "$ROLE" in web|reporter) ;; *) echo 'Invalid HW5 VM role'; exit 1;; esac
[[ "$DIGEST" =~ ^[0-9a-f]{64}$ ]] || exit 1
REFRESH_TOKEN="$(meta hw5-refresh-token 2>/dev/null || true)"
[[ -z "$REFRESH_TOKEN" || "$REFRESH_TOKEN" =~ ^[0-9a-f]{32}$ ]] || exit 1
echo "HW5 $ROLE startup beginning. source=$DIGEST refresh=$REFRESH_TOKEN"
install -d -m 755 "$BASE"
if [ -f "$BASE/.ready-$DIGEST" ]; then
  systemctl start "cs528-hw5-$ROLE.service"
  systemctl is-active --quiet "cs528-hw5-$ROLE.service"
  echo 'HW5 already installed; service started without reinstalling packages.'
  echo "HW5 $ROLE startup completed. source=$DIGEST refresh=$REFRESH_TOKEN"
  exit 0
fi
if [ ! -f "$BASE/.os-packages-ready" ]; then
  apt-get -o Acquire::Retries=3 update
  apt-get -o DPkg::Lock::Timeout=180 install -y python3 python3-venv ca-certificates curl
  touch "$BASE/.os-packages-ready"
fi
if ! id hw5 >/dev/null 2>&1; then
  useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin hw5
fi
# Metadata tokens never appear in a command line or log. Verify the archive hash.
python3 - "$BASE" "$DIGEST" <<'PY'
import hashlib, io, json, pathlib, sys, tarfile, urllib.request, urllib.parse
base, expected = pathlib.Path(sys.argv[1]), sys.argv[2]
root = 'http://metadata.google.internal/computeMetadata/v1/'
def metadata(name):
    req = urllib.request.Request(root + name, headers={'Metadata-Flavor': 'Google'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()
uri = metadata('instance/attributes/hw5-artifact')
bucket, name = uri.removeprefix('gs://').split('/', 1)
token = json.loads(metadata('instance/service-accounts/default/token'))['access_token']
url = 'https://storage.googleapis.com/storage/v1/b/' + bucket + '/o/' + urllib.parse.quote(name, safe='') + '?alt=media'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
with urllib.request.urlopen(req, timeout=120) as r:
    payload = r.read()
if hashlib.sha256(payload).hexdigest() != expected:
    raise SystemExit('Deployment archive checksum mismatch')
with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
    for member in archive.getmembers():
        target = (base / member.name).resolve()
        if not target.is_relative_to(base.resolve()) or not member.isfile():
            raise SystemExit('Unsafe archive member')
    for member in archive.getmembers():
        target = base / member.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.extractfile(member).read())
        target.chmod(0o644)
PY
REQ=requirements.txt
if [ "$ROLE" = reporter ]; then REQ=requirements-reporter.txt; fi
REQ_HASH="$(sha256sum "$BASE/$REQ" | cut -d ' ' -f 1)"
if [ ! -f "$BASE/.deps-$ROLE-$REQ_HASH" ]; then
  python3 -m venv "$BASE/venv"
  "$BASE/venv/bin/python" -m pip install --no-cache-dir -r "$BASE/$REQ"
  "$BASE/venv/bin/python" -m pip freeze > "$BASE/installed-requirements.txt"
  touch "$BASE/.deps-$ROLE-$REQ_HASH"
fi
PROJECT_ID="$(meta hw5-project)"
SUBSCRIPTION_ID="$(meta hw5-subscription)"
[[ "$PROJECT_ID" =~ ^[a-z0-9-]+$ ]] || exit 1
[[ "$SUBSCRIPTION_ID" =~ ^[a-zA-Z0-9_.-]+$ ]] || exit 1
cat > /etc/cs528-hw5.env <<EOF
PROJECT_ID=$PROJECT_ID
SUBSCRIPTION_ID=$SUBSCRIPTION_ID
EOF
MODULE=web_server.py
if [ "$ROLE" = reporter ]; then MODULE=reporter.py; fi
if [ "$ROLE" = web ]; then
  # This is idempotent: existing tables and data are retained.
  "$BASE/venv/bin/python" "$BASE/setup_schema.py"
fi
cat > "/etc/systemd/system/cs528-hw5-$ROLE.service" <<EOF
[Unit]
Description=CS528 HW5 $ROLE
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=hw5
Group=hw5
WorkingDirectory=$BASE
EnvironmentFile=/etc/cs528-hw5.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$BASE/venv/bin/python -u $BASE/$MODULE
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
chmod 644 /etc/cs528-hw5.env
systemctl daemon-reload
systemctl enable "cs528-hw5-$ROLE.service"
systemctl restart "cs528-hw5-$ROLE.service"
systemctl is-active --quiet "cs528-hw5-$ROLE.service"
touch "$BASE/.ready-$DIGEST"
echo "HW5 $ROLE startup completed. source=$DIGEST refresh=$REFRESH_TOKEN"

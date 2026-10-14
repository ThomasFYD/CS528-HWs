"""Build self-contained Compute Engine startup scripts from the submitted source."""

import hashlib
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write_file(path, contents):
    marker = "HW4_" + hashlib.sha256(contents.encode()).hexdigest()
    return f"cat > {shlex.quote(path)} <<'{marker}'\n{contents}\n{marker}\n"


def build_startup(role, project, bucket, topic, subscription):
    if role not in ("web", "reporter", "client"):
        raise ValueError("Unknown VM role")
    # Values go into systemd's EnvironmentFile as literal double-quoted values.
    values = {"PROJECT_ID": project, "BUCKET_NAME": bucket, "TOPIC_ID": topic,
              "SUBSCRIPTION_ID": subscription, "PORT": "8080"}
    if any(not value or any(c in value for c in '\n\r"\\') for value in values.values()):
        raise ValueError("Unsafe or empty configuration value")
    script = """#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
install -d -m 755 /opt/cs528-hw4
"""
    if role == "client":
        return script + """if [ ! -f /opt/cs528-hw4/client-ready ]; then
  apt-get -o Acquire::Retries=3 update
  apt-get -o DPkg::Lock::Timeout=180 install -y python3 curl ca-certificates
  touch /opt/cs528-hw4/client-ready
fi
echo 'HW4 client VM ready; upload the instructor Linux x86-64 client before testing.'
"""
    module = "web_server.py" if role == "web" else "reporter.py"
    dependencies = "requirements.txt" if role == "web" else "requirements-reporter.txt"
    source, requirements = (ROOT / module).read_text(), (ROOT / dependencies).read_text()
    install_hash = hashlib.sha256(requirements.encode()).hexdigest()
    script += f"""if ! id hw4 >/dev/null 2>&1; then
  useradd --system --home-dir /opt/cs528-hw4 --shell /usr/sbin/nologin hw4
fi
if [ ! -f /opt/cs528-hw4/.dependencies-{install_hash} ]; then
  apt-get -o Acquire::Retries=3 update
  apt-get -o DPkg::Lock::Timeout=180 install -y python3 python3-venv ca-certificates
  python3 -m venv /opt/cs528-hw4/venv
"""
    script += write_file("/opt/cs528-hw4/requirements.txt", requirements)
    script += f"""  /opt/cs528-hw4/venv/bin/python -m pip install --no-cache-dir --only-binary=:all: -r /opt/cs528-hw4/requirements.txt
  /opt/cs528-hw4/venv/bin/python -m pip freeze > /opt/cs528-hw4/installed-requirements.txt
  touch /opt/cs528-hw4/.dependencies-{install_hash}
fi
"""
    script += write_file(f"/opt/cs528-hw4/{module}", source)
    script += write_file("/etc/cs528-hw4.env", "\n".join(f'{key}="{value}"' for key, value in values.items()))
    script += write_file(f"/etc/systemd/system/cs528-hw4-{role}.service", f"""[Unit]
Description=CS528 HW4 {role} service
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=hw4
Group=hw4
WorkingDirectory=/opt/cs528-hw4
EnvironmentFile=/etc/cs528-hw4.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/cs528-hw4/venv/bin/python -u /opt/cs528-hw4/{module}
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
""")
    script += f"""chmod 644 /etc/cs528-hw4.env /opt/cs528-hw4/{module}
systemctl daemon-reload
systemctl enable cs528-hw4-{role}.service
systemctl restart cs528-hw4-{role}.service
systemctl --no-pager status cs528-hw4-{role}.service
"""
    if len(script.encode()) >= 256 * 1024:
        raise ValueError("Startup script exceeds the Compute Engine metadata value limit")
    return script

#!/usr/bin/env bash
set -euo pipefail
project=$1; sub=$2
dir=/opt/cs528-hw9
sudo install -d "$dir"
sudo install -m 644 reporter.py requirements-reporter.txt "$dir/"
sudo python3 -m venv "$dir/venv"
sudo "$dir/venv/bin/python" -m pip install --disable-pip-version-check -r "$dir/requirements-reporter.txt"
sudo tee /etc/systemd/system/hw9-reporter.service >/dev/null <<UNIT
[Unit]
Description=CS528 HW9 forbidden-country reporter
After=network-online.target
Wants=network-online.target
[Service]
DynamicUser=true
WorkingDirectory=$dir
Environment=PROJECT_ID=$project
Environment=SUBSCRIPTION_ID=$sub
ExecStart=$dir/venv/bin/python -u $dir/reporter.py
Restart=on-failure
RestartSec=4
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable hw9-reporter
sudo systemctl restart hw9-reporter
sudo systemctl is-active hw9-reporter

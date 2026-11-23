#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=3 update
apt-get -o DPkg::Lock::Timeout=180 install -y python3-venv
touch /var/tmp/hw9-ready

#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
chmod u+x setup.sh cleanup.sh startup.sh verify_local.sh
for script in setup.sh cleanup.sh startup.sh verify_local.sh; do
  bash -n "$script"
done
.venv/bin/python -m compileall -q config.py database.py request_data.py web_server.py hw4_service.py reporter.py infra.py setup_schema.py analysis.py tools tests guard
.venv/bin/python -m unittest discover -s tests -v
bash setup.sh --plan
echo 'Local checks passed. No cloud resources were created by this verification.'

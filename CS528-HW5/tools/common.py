"""Shared experiment utilities. No cloud action occurs on import."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import config
import infra


def endpoint():
    address = infra.describe(["compute", "addresses", "describe", infra.ADDRESS, f"--region={config.REGION}"])
    if not address:
        raise RuntimeError("No HW5 address. Run setup.sh first.")
    infra.owned(address, infra.ADDRESS)
    return address["address"], config.PORT


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")

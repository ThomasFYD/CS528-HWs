#!/usr/bin/env python3
"""Check the HW5 submission layout and executable entry points without cloud access."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
SHELL = ("setup.sh", "cleanup.sh", "startup.sh", "verify_local.sh")
PYTHON = ("check_submission.py", "infra.py", "setup_schema.py",
          "tools/build_report.py", "tools/collect_cloud_evidence.py", "tools/curl_demo.py",
          "tools/export_run.py", "tools/probe_client.py", "tools/replay_curl_evidence.py",
          "tools/run_experiment.py")
REQUIRED = ("README.md", "config.py", "database.py", "request_data.py", "web_server.py",
            "hw4_service.py", "reporter.py", "analysis.py", "queries.sql", "requirements.txt",
            "requirements-reporter.txt", "tools/common.py", "guard/main.py", "guard/requirements.txt",
            "report/CS528_HW5_Report.pdf", *SHELL, *PYTHON)


def main():
    errors = []
    for name in REQUIRED:
        path = ROOT / name
        if not path.is_file(): errors.append(f"Missing required file: {name}")
    for name in (*SHELL, *PYTHON):
        path = ROOT / name
        if not path.is_file(): continue
        content = path.read_bytes()
        expected = b"#!/bin/bash" if name in SHELL else b"#!/usr/bin/env python3"
        if not content.startswith(expected+b"\n"): errors.append(f"Incorrect shebang or line ending: {name}")
        if b"\r\n" in content: errors.append(f"Windows CRLF line endings: {name}")
        if not os.access(path, os.X_OK) or path.stat().st_mode & 0o111 != 0o111:
            errors.append(f"Missing executable permissions: {name} (use chmod 755)")
    if errors:
        print("HW5 submission check failed:\n"+"\n".join(errors), file=sys.stderr)
        return 1
    print(f"HW5 submission layout and {len(SHELL)+len(PYTHON)} executable entry points verified: {ROOT}")
    print("Python CLI tools use the active interpreter; activate .venv before invoking tools directly.")
    print("No cloud commands were run. Commit the executable file modes with the source changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

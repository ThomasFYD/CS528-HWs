#!/usr/bin/env python3
"""Run real curl requests and retain the table contents before/after each."""
import argparse
import json
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timezone

from common import ROOT, endpoint, write_json, infra
from database import create_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Optional explicit endpoint; default is the current allocated IP")
    args = parser.parse_args()
    host, port = endpoint()
    host = args.host or host
    run_id = "demo-" + uuid.uuid4().hex[:16]
    output = ROOT / "report" / "evidence" / run_id
    output.mkdir(parents=True)
    db = None
    infra.pause_guard()
    try:
        infra.sql()
        db = create_database(local=True)
        if db.counts()["requests"] > 200:
            raise RuntimeError("This demo displays full table contents. More than 200 prior rows exist; retain them and discuss an isolated demo database before proceeding.")
        cases = [("success", "data/0.html", "United States", 200),
                 ("missing", "data/hw5-file-that-does-not-exist.html", "United States", 404),
                 ("banned", "data/0.html", "Iran", 400)]
        entries = []
        for name, filename, country, expected in cases:
            before = db.snapshot()
            write_json(output / f"{name}-before.json", before)
            print(f"\n{name.upper()} — FULL TABLES BEFORE", flush=True)
            print(json.dumps({k: before[k] for k in ("requests", "failed_requests")}, indent=2, default=str), flush=True)
            headers_file, body_file = output / f"{name}-headers.txt", output / f"{name}-body.txt"
            command = ["curl", "--silent", "--show-error", "--max-time", "60",
                "--dump-header", str(headers_file), "--output", str(body_file), "--write-out", "%{http_code}",
                "-H", f"X-country: {country}", "-H", "X-client-IP: 192.0.2.25",
                "-H", "X-gender: Female", "-H", "X-age: 26-35", "-H", "X-income: 40k-60k",
                "-H", "X-time: 2026-10-20 13:00:00", f"http://{host}:{port}/__runs/{run_id}/{filename}"]
            print("COMMAND: " + shlex.join(command), flush=True)
            response = subprocess.run(command, capture_output=True, text=True, timeout=70, check=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                counts = db.counts(run_id)
                if counts["requests"] == counts["request_timings"]:
                    break
                time.sleep(0.2)
            after = db.snapshot()
            write_json(output / f"{name}-after.json", after)
            print(headers_file.read_text(), flush=True)
            print(f"{name.upper()} — FULL TABLES AFTER", flush=True)
            print(json.dumps({k: after[k] for k in ("requests", "failed_requests")}, indent=2, default=str), flush=True)
            entry = {"case": name, "command": command, "status": int(response.stdout),
                "expected_status": expected, "new_requests": len(after["requests"]) - len(before["requests"]),
                "new_errors": len(after["failed_requests"]) - len(before["failed_requests"])}
            entries.append(entry)
            write_json(output / "verification.json", {"run_id": run_id, "cases": entries,
                "captured_at": datetime.now(timezone.utc).isoformat()})
            if entry["status"] != expected or entry["new_requests"] != 1 or entry["new_errors"] != int(expected != 200):
                raise RuntimeError("Curl demonstration failed; retained all evidence")
        print("Three curl cases passed. Capture terminal screenshots for the report. Evidence: " + str(output), flush=True)
    finally:
        if db:
            db.close()
        infra.resume_guard()


if __name__ == "__main__":
    main()

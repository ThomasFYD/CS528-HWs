"""Use curl to verify HTTP country filtering, then inspect the GCS event log.

Run on the student's Mac while local_service/subscriber.py remains running.
Uses only Python's standard library plus the installed curl and gcloud commands.
The normal run makes 11 HTTP requests and never pulls or acknowledges Pub/Sub
itself. --recheck reads existing results and the bucket without new HTTP tests.
"""

import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT = "dazzling-seat-508219-j3"
BUCKET = "cs528-hw2-yf-2026"
ACCOUNT = "fangyd@bu.edu"
SERVICE_ACCOUNT = f"cs528-hw3-sa@{PROJECT}.iam.gserviceaccount.com"
URL = "https://cs528-hw3-files-sw2da6eioq-uc.a.run.app"
COUNTRIES = (
    "North Korea", "Iran", "Cuba", "Myanmar", "Iraq", "Libya", "Sudan",
    "Zimbabwe", "Syria",
)


def read_records(raw):
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if any(not isinstance(row, dict) or not row.get("event_id") for row in records):
        raise ValueError("A log record is missing its event_id.")
    return records


def inspect_delivery(before, after, cases):
    previous_ids = {row["event_id"] for row in before}
    new = [row for row in after if row["event_id"] not in previous_ids]
    expected = Counter(
        (case["country"], case["method"], case["path"])
        for case in cases if case["expected_status"] == 400
    )
    actual = Counter((row.get("country"), row.get("method"), row.get("path")) for row in new)
    ids = [row["event_id"] for row in after]
    duplicates = sorted(event_id for event_id, count in Counter(ids).items() if count > 1)
    lost = sorted(previous_ids - set(ids))
    metadata_valid = all(
        row.get("event") == "forbidden_country" and row.get("status") == 400
        and row.get("pubsub_message_id") and row.get("received_at")
        for row in new
    )
    return {
        "new_events_expected": sum(expected.values()),
        "new_events_found": len(new),
        "new_country_counts": dict(Counter(row.get("country") for row in new)),
        "new_event_ids": [row["event_id"] for row in new],
        "duplicate_event_ids": duplicates,
        "lost_previous_event_ids": lost,
        "request_event_pairs_match": actual == expected,
        "passed": actual == expected and not duplicates and not lost and metadata_valid,
    }


def fetch_log(folder, filename):
    result = subprocess.run([
        "gcloud", "storage", "cat", f"gs://{BUCKET}/hw3-logs/forbidden-requests.jsonl",
        f"--account={ACCOUNT}", f"--impersonate-service-account={SERVICE_ACCOUNT}",
        f"--project={PROJECT}", "--quiet",
    ], capture_output=True, timeout=90)
    with (folder / "gcloud-messages.txt").open("ab") as output:
        output.write(result.stderr)
    if result.returncode:
        raise RuntimeError(
            "Cannot read the bucket log. See gcloud-messages.txt in the results folder."
        )
    (folder / filename).write_bytes(result.stdout)
    return read_records(result.stdout)


def run_curl(case, folder):
    name = case["name"]
    body_file = folder / f"{name}-body.txt"
    command = [
        "curl", "-sS", "--max-time", "60",
        "-D", str(folder / f"{name}-headers.txt"),
        "-o", str(body_file), "-w", "%{http_code}",
        "-X", case["method"], "-H", f"X-country: {case['country']}",
    ]
    if case["method"] == "POST":
        command += [
            "-H", "Content-Type: application/json",
            "--data", json.dumps({"filename": "data/0.html"}),
        ]
    command.append(URL + case["path"])
    (folder / f"{name}-curl-command.json").write_text(json.dumps(command, indent=2) + "\n")
    result = subprocess.run(command, capture_output=True, text=True, timeout=70)
    (folder / f"{name}-curl-stderr.txt").write_text(result.stderr)
    body = body_file.read_bytes() if body_file.exists() else b""
    status = result.stdout.strip()
    if case["expected_status"] == 400:
        body_matches = body == f"Permission denied: request from {case['country']}.\n".encode()
    else:
        # Previously verified HW2 data/0.html MD5: 41U1Zt3txmd/WLuF7KDD5g==.
        import base64
        digest = base64.b64encode(hashlib.md5(body).digest()).decode()
        body_matches = digest == "41U1Zt3txmd/WLuF7KDD5g=="
    passed = result.returncode == 0 and status == str(case["expected_status"]) and body_matches
    print(
        f"{case['method']:4} {case['country']:12} -> {status or 'NO STATUS'} "
        f"(expected {case['expected_status']}) {'PASS' if passed else 'FAIL'}",
        flush=True,
    )
    return {
        **case, "actual_status": status, "curl_exit_code": result.returncode,
        "body_matches": body_matches, "passed": passed,
    }


def wait_for_delivery(before, cases, folder, wait_seconds):
    expected = sum(case["expected_status"] == 400 for case in cases)
    deadline = time.monotonic() + wait_seconds
    while True:
        after = fetch_log(folder, "forbidden-after.jsonl")
        delivery = inspect_delivery(before, after, cases)
        if delivery["passed"] or time.monotonic() >= deadline:
            return delivery
        if delivery["duplicate_event_ids"] or delivery["lost_previous_event_ids"]:
            return delivery
        print(f"Stored new events: {delivery['new_events_found']}/{expected}", flush=True)
        time.sleep(3)


def recheck_existing(original_folder, wait_seconds):
    original_folder = original_folder.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = original_folder / f"recheck-{stamp}"
    folder.mkdir(parents=True, exist_ok=False)
    summary = {
        "mode": "recheck", "original_results": str(original_folder),
        "rechecked_at": datetime.now(timezone.utc).isoformat(), "passed": False,
    }
    print(f"Rechecking existing results: {original_folder}", flush=True)
    print("No new HTTP requests will be sent to the function.", flush=True)
    try:
        original = json.loads((original_folder / "summary.json").read_text())
        cases = json.loads((original_folder / "test-cases.json").read_text())
        before = read_records((original_folder / "forbidden-before.jsonl").read_bytes())
        results = original["http_cases"]
        # Match the complete saved request list rather than relying on a lone
        # top-level boolean from a possibly partial or failed original run.
        http_passed = bool(cases) and len(results) == len(cases) and all(
            all(result.get(key) == value for key, value in case.items())
            and result.get("passed") is True and result.get("curl_exit_code") == 0
            and result.get("actual_status") == str(case["expected_status"])
            and result.get("body_matches") is True
            for case, result in zip(cases, results)
        )
        summary.update(run_id=original["run_id"], http_cases=results, http_passed=http_passed)
        print(f"Original HTTP checks passed: {http_passed}", flush=True)
        delivery = wait_for_delivery(before, cases, folder, wait_seconds)
        summary["delivery"] = delivery
        summary["passed"] = http_passed and delivery["passed"]
        if summary["passed"]:
            print(
                f"PASS: original {len(cases)} HTTP checks passed; "
                f"{delivery['new_events_found']} events now persisted; no duplicate event IDs.",
                flush=True,
            )
        else:
            print("FAIL: check the recheck summary and the subscriber terminal.", flush=True)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        summary["error"] = str(exc)
        print(f"FAIL: {exc}", flush=True)
    finally:
        path = folder / "summary.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(f"Summary: {path}", flush=True)
    return 0 if summary["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--results", type=Path, help="New results directory; must not already exist")
    mode.add_argument("--recheck", type=Path, help="Recheck an existing run without sending new HTTP requests")
    parser.add_argument("--wait-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.recheck:
        return recheck_existing(args.recheck, args.wait_seconds)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = args.results or Path(__file__).resolve().parents[1] / "results" / f"country-tests-{run_id}"
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    print(f"Results: {folder}", flush=True)
    summary = {"run_id": run_id, "http_cases": [], "passed": False}
    exit_code = 1
    try:
        # Establish which events existed before this test to avoid counting the
        # student's earlier Iran request as proof of a newly delivered event.
        before = fetch_log(folder, "forbidden-before.jsonl")
        print(f"Existing log records: {len(before)}", flush=True)
        cases = [
            {
                "name": f"{index + 1:02d}-{country.lower().replace(' ', '-')}-get",
                "method": "GET", "path": f"/data/{index}.html",
                "country": country, "expected_status": 400,
            }
            for index, country in enumerate(COUNTRIES)
        ] + [
            {"name": "10-cuba-post", "method": "POST", "path": "/", "country": "Cuba", "expected_status": 400},
            {"name": "11-cabo-verde-get", "method": "GET", "path": "/data/0.html", "country": "Cabo Verde", "expected_status": 200},
        ]
        (folder / "test-cases.json").write_text(json.dumps(cases, indent=2) + "\n")
        for case in cases:
            summary["http_cases"].append(run_curl(case, folder))
        summary["http_passed"] = all(case["passed"] for case in summary["http_cases"])
        print("Waiting for the Mac subscriber to persist 10 new events...", flush=True)
        delivery = wait_for_delivery(before, cases, folder, args.wait_seconds)
        summary["delivery"] = delivery
        summary["passed"] = summary["http_passed"] and delivery["passed"]
        if summary["passed"]:
            print("PASS: all 11 HTTP checks passed; 10 new events persisted; no duplicate event IDs.")
            exit_code = 0
        else:
            print("FAIL: inspect summary.json and the subscriber terminal before repeating requests.")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        summary["error"] = str(exc)
        print(f"FAIL: {exc}", flush=True)
    finally:
        path = folder / "summary.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(f"Summary: {path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

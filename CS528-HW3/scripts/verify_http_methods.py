"""Save curl evidence for GET, POST, missing files and all seven other methods.

Run on the student's Mac. No Pub/Sub messages are pulled or acknowledged here.
CONNECT uses the HTTP/1.1 authority-form request target; HEAD uses curl --head.
Every response is retained, including responses that need further investigation.
"""

import base64
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

URL = "https://cs528-hw3-files-sw2da6eioq-uc.a.run.app"
FILE_MD5 = "41U1Zt3txmd/WLuF7KDD5g=="


def check(case, folder):
    name, method, path, expected = case
    output = folder / f"{name}-output.txt"
    command = [
        "curl", "--http1.1", "-sS", "--max-time", "30",
        "-D", str(folder / f"{name}-headers.txt"),
        "-o", str(output), "-w", "%{http_code}",
        "-H", "X-country: Cabo Verde",
    ]
    if method == "HEAD":
        command += ["--head"]
    else:
        command += ["--request", method]
    if method == "POST":
        command += ["-H", "Content-Type: application/json", "--data", '{"filename":"data/0.html"}']
    if method == "PUT":
        # Explicit empty body makes curl send Content-Length: 0. Without it,
        # the Google frontend rejects this HTTP/1.1 request with 411 first.
        command += ["--data-binary", ""]
    if method == "CONNECT":
        command += ["--request-target", f"{urlsplit(URL).hostname}:443"]
    command += [URL + path]
    (folder / f"{name}-command.json").write_text(json.dumps(command, indent=2) + "\n")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=40)
        status, exit_code, stderr = result.stdout.strip(), result.returncode, result.stderr
    except subprocess.TimeoutExpired:
        status, exit_code, stderr = "", -1, "The curl process exceeded the 40-second process deadline."
    (folder / f"{name}-stderr.txt").write_text(stderr)
    contents_match = None
    if expected == 200:
        data = output.read_bytes() if output.exists() else b""
        contents_match = base64.b64encode(hashlib.md5(data).digest()).decode() == FILE_MD5
    passed = exit_code == 0 and status == str(expected) and contents_match is not False
    print(
        f"{name:16} {method:7} -> {status or 'NO STATUS':3} "
        f"expected {expected}  {'PASS' if passed else 'REVIEW'}",
        flush=True,
    )
    return {
        "name": name, "method": method, "path": path,
        "request_target": f"{urlsplit(URL).hostname}:443" if method == "CONNECT" else path,
        "expected_status": expected, "actual_status": status,
        "curl_exit_code": exit_code, "file_contents_match": contents_match,
        "passed": passed,
    }


def main():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path(__file__).resolve().parents[1] / "results" / f"http-final-{run_id}"
    folder.mkdir(parents=True, exist_ok=False)
    print(f"Results: {folder}", flush=True)
    cases = [
        ("get-existing", "GET", "/data/0.html", 200),
        ("post-existing", "POST", "/", 200),
        ("get-missing", "GET", f"/data/not-a-real-hw3-file-{run_id}.html", 404),
    ] + [
        (method.lower(), method, "/data/0.html", 501)
        for method in ("PUT", "DELETE", "HEAD", "CONNECT", "OPTIONS", "TRACE", "PATCH")
    ]
    tests = [check(case, folder) for case in cases]
    summary = {
        "run_id": run_id, "endpoint": URL, "http_version": "HTTP/1.1",
        "tests": tests, "passed": all(test["passed"] for test in tests),
    }
    path = folder / "summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Summary: {path}")
    if not summary["passed"]:
        print("REVIEW: retain the responses to investigate mismatches; no response was treated as a pass unless it matched.")
        return 1
    print("PASS: all 10 HTTP cases matched the assignment, including both original file contents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

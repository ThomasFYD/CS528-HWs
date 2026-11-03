#!/usr/bin/env python3
"""Display saved real curl evidence for screenshots, without any network access."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]
DEMO = "demo-8131a0d413fb4069"
REQUEST_GROUPS = (
    ("request_id", "request_time"),
    ("run_id", "method", "requested_file"),
    ("country", "client_ip", "peer_ip"),
    ("gender", "age", "income", "is_banned", "http_status"),
    ("client_time", "time_of_day"),
)
REQUEST_FIELDS = {key for group in REQUEST_GROUPS for key in group}
ERROR_FIELDS = {"request_time", "requested_file", "error_code"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def value(value):
    # Preserve NULL, the empty string, booleans, and complete source values.
    return json.dumps(value, ensure_ascii=True)


def tables(snapshot):
    lines = [f"requests: ALL {len(snapshot['requests'])} rows, ALL 15 columns"]
    for index, row in enumerate(snapshot["requests"], 1):
        if set(row) != REQUEST_FIELDS:
            raise ValueError("Unexpected request columns; refusing to hide fields")
        lines.append(f"  Record {index}")
        for group in REQUEST_GROUPS:
            lines.append("  " + " | ".join(f"{key}={value(row[key])}" for key in group))
    lines += ["", f"failed_requests: ALL {len(snapshot['failed_requests'])} rows, ALL 3 columns"]
    for index, row in enumerate(snapshot["failed_requests"], 1):
        if set(row) != ERROR_FIELDS:
            raise ValueError("Unexpected error columns; refusing to hide fields")
        lines.append(f"  Record {index}: " + " | ".join(
            f"{key}={value(row[key])}" for key in ("request_time", "requested_file", "error_code")))
    if not snapshot["failed_requests"]:
        lines.append("  (empty)")
    return "\n".join(lines)


def unchanged_rows(before, after, key):
    old = {row[key]: row for row in before}
    new = {row[key]: row for row in after}
    if len(old) != len(before) or len(new) != len(after):
        raise ValueError("Duplicate primary key in saved evidence")
    if any(new.get(identifier) != row for identifier, row in old.items()):
        raise ValueError("A preexisting row changed between saved snapshots")
    return [row for identifier, row in new.items() if identifier not in old]


def frames(directory):
    verification = read_json(directory / "verification.json")
    if verification["run_id"] != DEMO:
        raise ValueError("Unexpected demo run ID")
    entries = verification["cases"]
    if [item["case"] for item in entries] != ["success", "missing", "banned"]:
        raise ValueError("Expected the three original curl cases")
    output = []
    previous = None
    for item in entries:
        case = item["case"]
        before = read_json(directory / f"{case}-before.json")
        after = read_json(directory / f"{case}-after.json")
        added = unchanged_rows(before["requests"], after["requests"], "request_id")
        errors = unchanged_rows(before["failed_requests"], after["failed_requests"], "request_time")
        expected = {"success": 200, "missing": 404, "banned": 400}[case]
        if len(added) != 1 or added[0]["http_status"] != expected or added[0]["run_id"] != DEMO:
            raise ValueError("Saved request delta failed verification")
        if len(errors) != int(expected != 200):
            raise ValueError("Saved error delta failed verification")
        if errors and (errors[0]["request_time"] != added[0]["request_time"] or
                       errors[0]["requested_file"] != added[0]["requested_file"] or
                       errors[0]["error_code"] != expected):
            raise ValueError("Saved error row does not match the request")
        if item["status"] != expected or item["expected_status"] != expected:
            raise ValueError("Saved curl status failed verification")
        if previous is not None:
            for name in ("requests", "failed_requests"):
                if previous[name] != before[name]:
                    raise ValueError("Saved cases do not form a continuous table history")
        previous = after
        headers = (directory / f"{case}-headers.txt").read_text(encoding="utf-8")
        if int(headers.splitlines()[0].split()[1]) != expected:
            raise ValueError("Response headers disagree with the saved status")
        body = (directory / f"{case}-body.txt").read_bytes()
        base = (f"SAVED REAL EVIDENCE REPLAY - {case.upper()}\n"
                f"Run: {DEMO} | Original capture: {verification['captured_at']}\n"
                "Read-only local display. No curl execution, cloud query or database change.\n")
        output.append((case + "-before", base + "\nFULL TABLES BEFORE\n" + tables(before)))
        command = shlex.join(item["command"])
        command = textwrap.fill(command, width=112, subsequent_indent="  ",
                                break_long_words=False, break_on_hyphens=False)
        response = (base + "\nORIGINAL EXECUTED COMMAND (display only; historical IP was released)\n" +
                    command + "\n\nSAVED RESPONSE HEADERS\n" + headers +
                    f"\nSaved response body: {len(body)} bytes\n"
                    f"Body SHA-256: {hashlib.sha256(body).hexdigest()}\n"
                    f"Verified changes: +{len(added)} request, +{len(errors)} error row(s).")
        if expected != 200:
            response += "\nSaved error body: " + value(body.decode("utf-8"))
        output.append((case + "-response", response))
        output.append((case + "-after", base + "\nFULL TABLES AFTER\n" + tables(after)))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "report" / "evidence" / DEMO)
    parser.add_argument("--all", action="store_true", help="Print all frames without interaction")
    parser.add_argument("--frame", choices=[f"{case}-{phase}" for case in
                        ("success", "missing", "banned") for phase in ("before", "response", "after")])
    args = parser.parse_args()
    pages = frames(args.evidence)  # Validate all six snapshots before showing any page.
    if args.frame:
        pages = [(name, content) for name, content in pages if name == args.frame]
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.all and not args.frame
    if interactive:
        print("Maximize Terminal, then capture each of the 9 labeled pages with Shift-Command-4.")
        print("If a line wraps, reduce the font slightly. Every stored request/error field is displayed.")
        print("Screenshots must be described as a replay of saved real evidence, not a new live run.")
        input("Press Enter to begin, or Ctrl-C to exit: ")
    for number, (name, content) in enumerate(pages, 1):
        if interactive:
            print("\033[2J\033[H", end="")
        print(f"PAGE {number}/{len(pages)} | Suggested screenshot: {name}.png\n{content}", flush=True)
        if interactive:
            answer = input("\nCapture this page, then Enter for next (q to quit): ").strip().lower()
            if answer == "q":
                return
        else:
            print()
    print("Replay complete. Original files were only read; no cloud resources were used.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReplay stopped. Original evidence is unchanged.")

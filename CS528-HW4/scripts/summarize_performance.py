"""Summarize retained measurements without inventing silent-client HTTP counts."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

METRICS = ("cpu_busy_pct", "cpu_iowait_pct", "cpu_steal_pct", "memory_used_mib",
           "memory_used_pct", "rx_mbps", "tx_mbps")


def epoch(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def json_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def window_samples(records, start, end):
    selected = []
    for record in records:
        if record.get("type") != "sample":
            continue
        left, right = epoch(record["interval_start"]), epoch(record["timestamp"])
        overlap = min(end, right) - max(start, left)
        if overlap > 0:
            selected.append({**record, "window_seconds": overlap,
                             "relative_seconds": min(end, right) - start,
                             "window_left": max(start, left), "window_right": min(end, right)})
    return sorted(selected, key=lambda r: r["window_left"])


def resource_summary(samples, start, end):
    if not samples:
        return {"sample_count": 0, "coverage_seconds": 0, "max_gap_seconds": end - start}
    cursor, coverage, max_gap = start, 0.0, 0.0
    for row in samples:
        max_gap = max(max_gap, row["window_left"] - cursor)
        coverage += max(0, row["window_right"] - max(cursor, row["window_left"]))
        cursor = max(cursor, row["window_right"])
    max_gap = max(max_gap, end - cursor)
    weight = sum(row["window_seconds"] for row in samples)
    return {"sample_count": len(samples), "coverage_seconds": coverage,
            "max_gap_seconds": max_gap,
            "max_sample_interval_seconds": max(row["elapsed_seconds"] for row in samples),
            "mean": {key: sum(r[key] * r["window_seconds"] for r in samples) / weight for key in METRICS},
            "peak": {key: max(r[key] for r in samples) for key in METRICS}}


def cloud_counts(records, start, end):
    counts = Counter()
    for record in records:
        if not start <= epoch(record["timestamp"]) < end:
            continue
        payload = record.get("jsonPayload", {})
        if payload.get("event") == "forbidden_country" and payload.get("status") == 400:
            counts["expected_country_denials"] += 1
        else:
            counts["other_warning_or_error_records"] += 1
            counts["status_" + str(payload.get("status", "unspecified"))] += 1
    return dict(counts)


def summarize(folder):
    web = json_lines(folder / "web-resources.jsonl")
    cloud_path = folder / "cloud-errors.json"
    logs = json.loads(cloud_path.read_text()) if cloud_path.exists() else []
    web_journal = json_lines(folder / "web-journal.jsonl")
    meta = next((r for r in web if r.get("type") == "metadata"), {})
    results = {"rounds": [], "notes": [
        "Metrics describe the whole web VM. Network RX/TX include GCS, HTTP, and API traffic.",
        "Peaks are maxima of approximately one-second samples overlapping the measurement window.",
        "CPU is guest logical-CPU busy percent, not the f1-micro CPU entitlement; steal and iowait are separate.",
        "The instructor client's quiet mode provides no HTTP status counts or request throughput.",
        "Cloud logs can arrive late. Re-collect after a delay before final reporting.",
        "Intentional termination at a round deadline can leave an in-flight request unfinished.",
    ], "web_metadata": meta}
    rows = []
    for count in (1, 2, 3, 4):
        directory = folder / "client" / f"c{count}"
        round_path = directory / "round.json"
        if not round_path.exists():
            results["rounds"].append({"clients": count, "measurement_valid": False,
                                       "issues": ["Round did not produce a result"]})
            continue
        run = json.loads(round_path.read_text())
        row = {"clients": count, "run_complete": run.get("complete", False),
               "measured_seconds": run.get("measured_seconds", 0), "issues": []}
        if not run.get("measurement_start") or not run.get("measurement_end"):
            row.update(measurement_valid=False, issues=["No complete measurement window"])
            results["rounds"].append(row)
            continue
        start, end = epoch(run["measurement_start"]), epoch(run["measurement_end"])
        selected = window_samples(web, start, end)
        stats = resource_summary(selected, start, end)
        client_records = json_lines(directory / "client-resources.jsonl")
        client_stats = resource_summary(window_samples(client_records, start, end), start, end)
        row["web"] = stats
        row["client_vm"] = client_stats
        row["cloud_log_counts"] = cloud_counts(logs, start, end)
        received = defaultdict(str)
        for event in json_lines(directory / "events.jsonl"):
            if start <= epoch(event["timestamp"]) < end:
                received[event["client"]] += event["text"]
        row["client_timeout_messages"] = sum(text.count("Timeout received") for text in received.values())
        row["other_client_output"] = [text.replace("Timeout received", "").strip()
                                      for text in received.values()
                                      if text.replace("Timeout received", "").strip()]
        journal_failures = []
        for event in web_journal:
            stamp = int(event.get("__REALTIME_TIMESTAMP", "0")) / 1e6
            message = event.get("MESSAGE", "")
            if start <= stamp < end and any(term in message for term in (
                    "cloud_logging_failed", "Traceback", "BrokenPipeError", "ConnectionResetError")):
                journal_failures.append(message)
        row["server_journal_failure_lines"] = journal_failures
        if not run.get("complete") or run.get("measured_seconds", 0) < 180:
            row["issues"].append("Fewer than 180 seconds with all requested clients alive")
        if stats["coverage_seconds"] < 179.5 or stats["max_gap_seconds"] > 1.5:
            row["issues"].append("Web resource samples do not cover the full window")
        if stats.get("max_sample_interval_seconds", 999) > 3:
            row["issues"].append("Resource sampling stalled for more than three seconds")
        client_meta = next((r for r in client_records if r.get("type") == "metadata"), {})
        if meta.get("clock_synchronized") != "yes" or client_meta.get("clock_synchronized") != "yes":
            row["issues"].append("VM clock synchronization needs verification")
        if not cloud_path.exists() or len(logs) >= 50000 or not (folder / "web-journal.jsonl").exists():
            row["issues"].append("Error evidence missing or Cloud Logging export may be truncated")
        row["measurement_valid"] = not row["issues"]
        # This is evidence of observed errors only; it does not establish a capacity limit.
        row["observed_failures_need_review"] = bool(
            row["client_timeout_messages"] or row["other_client_output"] or journal_failures
            or row["cloud_log_counts"].get("other_warning_or_error_records"))
        results["rounds"].append(row)
        for sample in selected:
            rows.append({"clients": count, "relative_seconds": sample["relative_seconds"],
                         "timestamp": sample["timestamp"], **{k: sample[k] for k in METRICS}})
    (folder / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    with (folder / "web-metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["clients", "relative_seconds", "timestamp", *METRICS])
        writer.writeheader()
        writer.writerows(rows)
    lines = ["clients | seconds | peak CPU % | peak memory MiB | peak RX Mbps | peak TX Mbps | timeouts | valid"]
    for row in results["rounds"]:
        peak = row.get("web", {}).get("peak", {})
        def fmt(key):
            return f"{peak[key]:.2f}" if key in peak else "n/a"
        lines.append(f"{row['clients']} | {row.get('measured_seconds', 0):.1f} | {fmt('cpu_busy_pct')} | "
                     f"{fmt('memory_used_mib')} | {fmt('rx_mbps')} | {fmt('tx_mbps')} | "
                     f"{row.get('client_timeout_messages', 'n/a')} | {row['measurement_valid']}")
        lines.extend("  CHECK: " + issue for issue in row["issues"])
        if row.get("observed_failures_need_review"):
            lines.append("  CHECK: observed errors need review; see summary.json and raw logs")
    text = "\n".join(lines) + "\n"
    (folder / "summary.txt").write_text(text)
    print(text, end="")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    summarize(parser.parse_args().folder)

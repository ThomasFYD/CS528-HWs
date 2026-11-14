"""Summarize recorded observations without treating a first survivor response as LB detection."""
import argparse
from collections import Counter
import json
import statistics
from pathlib import Path


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def distribution(rows, zones):
    good = [r for r in rows if r["ok"] and r["status"] == 200 and r["zone"] in zones]
    counts = {z: sum(r["zone"] == z for r in good) for z in zones}
    return {"attempts": len(rows), "successful_200": len(good), "other": len(rows) - len(good),
            "counts": counts, "percent": {z: 100 * n / len(good) if good else None for z, n in counts.items()},
            "status_counts": dict(Counter(str(r["status"]) for r in rows)),
            "transport_errors": sum(r["error"] is not None for r in rows)}


def trial_summary(rows, health, stop, restart, zone_a, zone_b):
    t0, t1 = stop["after_epoch"], restart["before_epoch"]
    down = [r for r in rows if t0 <= r["started_epoch"] < t1]
    failures = [r for r in down if not r["ok"] or r["zone"] != zone_b]
    last_bad_sequence = max((r["sequence"] for r in failures), default=-1)
    tail = [r for r in down if r["sequence"] > last_bad_sequence and r["ok"] and r["zone"] == zone_b]
    # This empirical series can recover before a sampled health API result changes.
    # If no error was seen, it cannot estimate failed-backend removal from client data.
    client_recovery = tail[0]["finished_epoch"] - t0 if tail and failures else None
    unhealthy = next((h for h in health if t0 <= h.get("sent_epoch", 0) < t1
                      and h.get("states", {}).get("cs528-hw8-web-a") == "UNHEALTHY"), None)
    recovered = next((r for r in rows if r["started_epoch"] >= t1 and r["ok"] and r["zone"] == zone_a), None)
    healthy = next((h for h in health if h.get("sent_epoch", 0) >= t1
                    and h.get("states", {}).get("cs528-hw8-web-a") == "HEALTHY"), None)
    ready = restart.get("ready_epoch", restart["after_epoch"])
    return {
        "trial": stop["phase"].split("-")[1], "stop": stop, "restart": restart,
        "down_window": distribution(down, [zone_a, zone_b]),
        "post_stop_client_failure_count": len(failures),
        "post_stop_transport_error_count": sum(r["error"] is not None for r in down),
        "inflight_at_kill_errors": sum(r["started_epoch"] < t0 and r["finished_epoch"] >= stop["before_epoch"]
                                       and not r["ok"] for r in rows),
        "last_failed_request_start_delay_s": failures[-1]["started_epoch"] - t0 if failures else None,
        "last_failed_request_completion_delay_s": max(r["finished_epoch"] for r in failures) - t0 if failures else None,
        "client_sustained_success_completion_delay_s": client_recovery,
        "client_sustained_success_start_delay_s": tail[0]["started_epoch"] - t0 if tail and failures else None,
        "client_tail_observation_s": tail[-1]["started_epoch"] - tail[0]["started_epoch"] if len(tail) > 1 else 0,
        "api_unhealthy_observed_delay_s": unhealthy["received_epoch"] - t0 if unhealthy else None,
        "api_unhealthy_query_started_delay_s": unhealthy["sent_epoch"] - t0 if unhealthy else None,
        "recovery_first_zone_a_response_delay_s": recovered["finished_epoch"] - t1 if recovered else None,
        "recovery_after_app_ready_delay_s": recovered["finished_epoch"] - ready if recovered else None,
        "app_restart_ready_delay_s": ready - t1,
        "api_healthy_observed_delay_s": healthy["received_epoch"] - t1 if healthy else None,
        "failure_request_sequences": [r["sequence"] for r in failures],
        "client_recovery_note": "First response after the last failed probe, followed by sustained survivor-only success; sampled client observation, not exact health detection." if failures else "No post-stop failures observed; client-only failover detection time is not identifiable.",
    }


def analyze(folder):
    rows = sorted(read_jsonl(folder / "requests.jsonl"), key=lambda r: r["sequence"])
    health = sorted(read_jsonl(folder / "health.jsonl"), key=lambda h: h["received_epoch"])
    events = read_jsonl(folder / "events.jsonl")
    config = json.loads((folder / "config.json").read_text())
    zones = [config["zone_a"], config["zone_b"]]
    sequences = [r["sequence"] for r in rows]
    if sequences != list(range(len(rows))):
        raise ValueError("Missing or duplicate request records")
    trials = []
    for stop in [e for e in events if e["action"] == "stop"]:
        trial = stop["phase"].split("-")[1]
        restart = next(e for e in events if e["action"] == "start" and e["phase"] == f"trial-{trial}-restart")
        trials.append(trial_summary(rows, health, stop, restart, *zones))
    spacing = [b["started_monotonic"] - a["started_monotonic"] for a, b in zip(rows, rows[1:])]
    wall_mono = [(r["started_epoch"] - rows[0]["started_epoch"]) -
                 (r["started_monotonic"] - rows[0]["started_monotonic"]) for r in rows]
    both = [r for r in rows if r["phase"] == "baseline" or r["phase"].endswith("-recovered")]
    result = {"complete": (folder / "COMPLETE").exists(), "run": folder.name,
              "started_at": rows[0]["started_at"], "finished_at": max(r["finished_at"] for r in rows),
              "zones": zones, "total": distribution(rows, zones), "both_healthy_windows": distribution(both, zones),
              "phases": {phase: distribution([r for r in rows if r["phase"] == phase], zones)
                         for phase in dict.fromkeys(r["phase"] for r in rows)},
              "timing": {"request_spacing_min_s": min(spacing), "request_spacing_median_s": statistics.median(spacing),
                         "request_spacing_max_s": max(spacing), "wall_monotonic_max_drift_s": max(map(abs, wall_mono)),
                         "distinct_local_ports": len({r.get("local_port") for r in rows if "local_port" in r}),
                         "health_query_count": len(health), "health_query_errors": sum("error" in h for h in health)},
              "trials": trials,
              "definitions": {"ratio_denominator": "Complete successful HTTP 200 file responses with a recognized zone; failures excluded and counted separately.",
                              "both_healthy": "Baseline plus stable recovered phases; excludes deliberate single-backend and transition phases.",
                              "sampling": "One request launch per second with fresh TCP connections. API polls are separate observations and have command/API latency."}}
    (folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    args = p.parse_args()
    print(json.dumps(analyze(args.folder), indent=2))


if __name__ == "__main__":
    main()

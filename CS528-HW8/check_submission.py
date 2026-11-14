"""Validate the measured evidence and its connection to the submitted server source."""
import argparse
import hashlib
import json
from pathlib import Path
from analyze import analyze
from startup import build_startup


def check(folder):
    summary = analyze(folder)
    config = json.loads((folder / "config.json").read_text())
    deployment = json.loads((folder / "deployment.json").read_text())
    failures = []
    def require(value, message):
        if not value: failures.append(message)
    require(summary["complete"], "Run did not finish")
    require(len(summary["trials"]) == config["trials"], "Missing trials")
    require(summary["both_healthy_windows"]["other"] == 0, "Unexpected failures in stable both-healthy windows")
    require(all(n > 0 for n in summary["both_healthy_windows"]["counts"].values()), "Missing backend in distribution")
    require(.95 <= summary["timing"]["request_spacing_median_s"] <= 1.05, "Median request interval differs from 1 second")
    require(summary["timing"]["request_spacing_max_s"] < 1.5, "Client schedule has a large gap")
    require(summary["timing"]["wall_monotonic_max_drift_s"] < .1, "Client wall clock changed during run")
    require(summary["timing"]["health_query_errors"] == 0, "Health polling errors occurred")
    for trial in summary["trials"]:
        for key in ("api_unhealthy_observed_delay_s", "recovery_first_zone_a_response_delay_s", "api_healthy_observed_delay_s"):
            value = trial[key]
            require(value is not None and 0 <= value < 60, f"Trial {trial['trial']}: {key} unavailable or >=60s")
        value = trial["client_sustained_success_completion_delay_s"]
        require(value is None or 0 <= value < 60, "Client observed failover >=60s")
        require(trial["client_tail_observation_s"] >= 15, "Insufficient sustained survivor observation")
        require(trial["stop"]["ntp_synchronized"] == "yes" and trial["restart"]["ntp_synchronized"] == "yes", "VM clock not synchronized")
    for suffix, zone in (("a", config["zone_a"]), ("b", config["zone_b"])):
        vm = deployment[f"cs528-hw8-web-{suffix}"]
        require(vm["zone"].endswith("/" + zone), "VM in unexpected zone")
        script = build_startup("web", config["project"], config["bucket"], "cs528-hw8-forbidden", "cs528-hw8-forbidden-sub")
        require(vm["labels"]["source"] == hashlib.sha256(script.encode()).hexdigest()[:32], "Submitted server/startup differs from measured VM source")
    hc = deployment["health_check"]
    require(hc["httpHealthCheck"]["port"] == 8080 and hc["httpHealthCheck"]["requestPath"] == "/healthz", "Incorrect health endpoint")
    require(config["zone_a"] != config["zone_b"], "Zones must differ")
    require(all(z.startswith(config["region"] + "-") for z in (config["zone_a"], config["zone_b"])), "Zones must share a region")
    report = {"passed": not failures, "failures": failures, "requests": summary["total"]["attempts"],
              "trials": len(summary["trials"]), "checked": "Live evidence, schedule, outcomes, deployment, and submitted web startup hash"}
    (folder / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    args = p.parse_args()
    result = check(args.folder)
    print(json.dumps(result, indent=2))
    if not result["passed"]: raise SystemExit(1)


if __name__ == "__main__":
    main()

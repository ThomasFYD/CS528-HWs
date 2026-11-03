#!/usr/bin/env python3
"""Save post-run cloud evidence; optionally stop, but never delete, SQL and VMs."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import re

from common import ROOT, config, infra, write_json
from database import gcloud_credentials


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_metric(session, metric, start, end):
    # Official API: https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.timeSeries/list
    params = {
        "filter": (f'metric.type="pubsub.googleapis.com/subscription/{metric}" '
                   f'AND resource.type="pubsub_subscription" '
                   f'AND resource.labels.subscription_id="{config.SUBSCRIPTION_ID}"'),
        "interval.startTime": start, "interval.endTime": end,
        "view": "FULL", "pageSize": 10000,
    }
    pages = []
    for _ in range(20):
        response = session.get(
            f"https://monitoring.googleapis.com/v3/projects/{config.PROJECT_ID}/timeSeries",
            params=params, timeout=(10, 45))
        if response.status_code != 200:
            raise RuntimeError(f"Monitoring query returned HTTP {response.status_code}; "
                               "check Monitoring API access. No credentials were saved.")
        page = response.json()
        pages.append(page)
        token = page.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token
    else:
        raise RuntimeError("Monitoring pagination limit reached; no complete result claimed.")
    return {"metric": metric, "start": start, "end": end, "pages": pages}


def metric_summary(result):
    series = [row for page in result["pages"] for row in page.get("timeSeries", [])]
    points = [point for row in series for point in row.get("points", [])]
    values = [int(point["value"]["int64Value"]) for point in points]
    summary = {"series": len(series), "points": len(points)}
    if result["metric"] == "num_undelivered_messages":
        # Keep each series' most recent sample; do not add gauge samples over time.
        summary["latest_per_series"] = [
            {"labels": row.get("metric", {}).get("labels", {}),
             "point": max(row["points"], key=lambda p: p["interval"]["endTime"])}
            for row in series if row.get("points")]
    else:
        summary["sum_of_delta_samples"] = sum(values) if points else None
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stop", action="store_true", help="Stop owned SQL and VMs after collecting evidence")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("Invalid run ID")
    experiment_path = ROOT / "report/evidence" / args.run_id / "experiment.json"
    experiment = json.loads(experiment_path.read_text())
    summary = json.loads(experiment_path.with_name("summary.json").read_text())
    if not experiment.get("complete") or experiment.get("exit_codes") != [0, 0] or not summary["integrity"]["complete"]:
        raise SystemExit("The selected experiment is not verified complete; review it before stopping resources.")
    snapshot = ROOT / "results" / args.run_id / "database-snapshot.json.gz"
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)
    output = ROOT / "report/evidence" / ("post-load-" + now.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True)
    manifest = {"run_id": args.run_id, "project": config.PROJECT_ID, "captured_at": utc(now),
                "snapshot": str(snapshot), "snapshot_sha256": digest, "stop_requested": args.stop,
                "collected": {}, "errors": {},
                "limitations": [
                    "Metrics are sampled and can be delayed; absent points are not proof of zero activity.",
                    "Subscription metrics show delivery/acknowledgment activity, not individual reporter stdout records.",
                    "The query interval includes a one-minute margin before the experiment and extends to collection time.",
                    "Logs and metrics require review; collection alone does not verify scheduled shutdown.",
                ]}

    def collect(name, callback):
        print("Collecting: " + name, flush=True)
        try:
            value = callback()
            write_json(output / (name + ".json"), value)
            manifest["collected"][name] = len(value) if isinstance(value, list) else "saved"
            return value
        except Exception as exc:
            manifest["errors"][name] = f"{type(exc).__name__}: {exc}"
            print("Evidence query needs review: " + name, flush=True)
            return None
        finally:
            write_json(output / "collection.json", manifest)

    def resource_state(filename):
        path = output / filename
        infra.status(str(path.relative_to(ROOT / "report/evidence")))
        return json.loads(path.read_text())

    (ROOT / "build").mkdir(exist_ok=True)
    with (ROOT / "build/experiment.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A local experiment is running; no cloud action was performed.")
        try:
            collect("resources-before", lambda: resource_state("resources-before.json"))
            since = utc(datetime.fromisoformat(experiment["load_started_at"]) - timedelta(days=2))
            log_filters = {
                "scheduler-executions": f'resource.type="cloud_scheduler_job" AND resource.labels.job_id="{infra.JOB}"',
                "guard-function": f'resource.type="cloud_run_revision" AND resource.labels.service_name="{infra.FUNCTION}"',
                "guard-sql-audit": (
                    f'protoPayload.authenticationInfo.principalEmail="{config.service_account("guard")}" '
                    'AND (protoPayload.serviceName="cloudsql.googleapis.com" OR '
                    'protoPayload.serviceName="sqladmin.googleapis.com")'),
            }
            for name, query in log_filters.items():
                collect(name, lambda query=query: infra.cloud(
                    ["logging", "read", query + f' AND timestamp>="{since}"',
                     "--limit=1000", "--order=asc"], json_output=True))
            collect("subscription-policy", lambda: infra.cloud(
                ["pubsub", "subscriptions", "get-iam-policy", config.SUBSCRIPTION_ID], json_output=True))
            collect("subscription", lambda: infra.cloud(
                ["pubsub", "subscriptions", "describe", config.SUBSCRIPTION_ID], json_output=True))

            import requests
            credentials = gcloud_credentials()
            try:
                credentials.refresh(None)
                with requests.Session() as session:
                    session.headers["Authorization"] = "Bearer " + credentials.token
                    start = utc(datetime.fromisoformat(experiment["load_started_at"]) - timedelta(minutes=1))
                    end = utc(datetime.now(timezone.utc))
                    manifest["pubsub_metrics"] = {}
                    for metric in ("sent_message_count", "ack_message_count", "num_undelivered_messages"):
                        value = collect("pubsub-" + metric, lambda metric=metric: read_metric(session, metric, start, end))
                        if value is not None:
                            manifest["pubsub_metrics"][metric] = metric_summary(value)
            except Exception as exc:
                manifest["errors"]["monitoring-access"] = f"{type(exc).__name__}: {exc}"
        finally:
            if args.stop:
                print("Stopping owned SQL and VMs; retaining database, disks and evidence.", flush=True)
                try:
                    infra.finish()
                    manifest["stop_command_completed"] = True
                except Exception as exc:
                    manifest["stop_command_completed"] = False
                    manifest["errors"]["stop"] = f"{type(exc).__name__}: {exc}"
                after = collect("resources-after", lambda: resource_state("resources-after.json"))
                if after is not None:
                    manifest["stopped_state_verified"] = (
                        (after.get("sql") or {}).get("settings", {}).get("activationPolicy") == "NEVER"
                        and all((after.get("vms", {}).get(role) or {}).get("status") == "TERMINATED"
                                for role in ("web", "reporter"))
                        and (after.get("guard") or {}).get("state") == "ENABLED")
            write_json(output / "collection.json", manifest)
    print(json.dumps(manifest, indent=2), flush=True)
    print("Evidence: " + str(output), flush=True)
    if args.stop and not manifest.get("stopped_state_verified"):
        raise SystemExit("Stop state was not verified; retain this output and inspect resources before leaving them running.")
    print("Collection finished. Review any query errors. Retained disks/IP/SQL storage can still incur charges.")


if __name__ == "__main__":
    main()

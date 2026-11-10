#!/usr/bin/env python3
"""Save cloud job, environment and cleanup evidence after successful execution."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import google.auth
from google.auth.transport.requests import AuthorizedSession


def cloud_json(*args):
    result = subprocess.run(["gcloud", *args, "--format=json"], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output", default="report/evidence")
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text())
    project = "dazzling-seat-508219-j3"
    job_id = metadata["job_id"]
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    url = f"https://dataflow.googleapis.com/v1b3/projects/{project}/locations/us-central1/jobs/{job_id}"
    response = session.get(url, params={"view": "JOB_VIEW_ALL"}, timeout=60)
    response.raise_for_status()
    job = response.json()
    metrics_response = session.get(url + "/metrics", timeout=60)
    metrics_response.raise_for_status()
    instances = cloud_json("compute", "instances", "list", "--project=" + project)
    disks = cloud_json("compute", "disks", "list", "--project=" + project)
    def belongs(resource):
        return (resource.get("labels", {}).get("dataflow_job_id") == job_id
                or resource.get("labels", {}).get("goog-dataflow-job-id") == job_id
                or resource.get("name", "").startswith(job["name"]))
    workers = [x for x in instances if belongs(x)]
    worker_disks = [x for x in disks if belongs(x)]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    save("dataflow-job.json", job)
    save("dataflow-metrics.json", metrics_response.json())
    cleanup = {"checked_at": datetime.now(timezone.utc).isoformat(),
               "job_id": job_id, "job_state": job["currentState"],
               "remaining_worker_instances": workers, "remaining_worker_disks": worker_disks,
               "verified": job["currentState"] == "JOB_STATE_DONE" and not workers and not worker_disks,
               "retained": ["private results bucket and output evidence", "HW7 worker identity", "original HW2 data"]}
    save("cleanup.json", cleanup)
    print(json.dumps(cleanup, indent=2))
    if not cleanup["verified"]:
        raise RuntimeError("Cloud job or automatic compute cleanup is not yet complete")


if __name__ == "__main__":
    main()

"""Reconcile actual VM client output, curl results and both copies of a denial event."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys


def check(directory, ip):
    run = directory.name
    read = lambda name: (directory / name).read_text()
    with gzip.open(directory / "client.txt.gz", "rt", errors="replace") as stream:
        paths = []
        statuses = []
        for line in stream:
            if line.startswith("Requesting  "):
                paths.append(line.split()[1])
            elif re.fullmatch(r"[1-5][0-9]{2} [^\r\n]+\n", line):
                statuses.append(int(line[:3]))
    counts = collections.Counter(statuses)
    if len(paths) != 300 or len(statuses) != 300 or set(counts) - {200, 400} or counts[200] == 0:
        raise ValueError(f"Incomplete or unexpected client output: {len(paths)} requests, {counts}")
    if len(set(paths)) < 200:
        raise ValueError("Fewer than 200 distinct file paths")
    errors = [(r["jsonPayload"], r.get("severity", "DEFAULT")) for r in json.loads(read("cloud-errors.json"))]
    url = "/data/0.html?proof=" + run
    def matched(method, path, code, level):
        return [e for e, s in errors if (e.get("method"), e.get("path"), e.get("status"), s)
                == (method, path, code, level)]
    for method in ("PUT", "DELETE", "HEAD", "OPTIONS", "TRACE", "PATCH", "CONNECT"):
        path = ip + ":80" if method == "CONNECT" else url
        if not matched(method, path, 501, "ERROR"):
            raise ValueError(f"Missing Cloud Logging entry for {method} {path}")
    if not matched("GET", f"/data/hw9-missing-{run}.html", 404, "WARNING"):
        raise ValueError("Missing 404 in Cloud Logging")
    denied = matched("GET", url, 400, "CRITICAL")
    reporters = [json.loads(line.removeprefix("FORBIDDEN ")) for line in read("reporter.txt").splitlines()
                 if line.startswith("FORBIDDEN ")]
    ids = {e["event_id"] for e in denied if e["country"] == "Iran"}
    same = [e for e in reporters if e.get("event_id") in ids and e.get("country") == "Iran"]
    if not same:
        raise ValueError("Reporter stdout has no matching event ID")
    client_rows = [{"path": path, "status": status} for path, status in zip(paths, statuses)]
    expected_denials = collections.Counter(row["path"] for row in client_rows if row["status"] == 400)
    client_ids = {e["event_id"]: e["path"] for e, level in errors if level == "CRITICAL"
                  and e.get("event") == "forbidden_country" and e.get("path") in expected_denials}
    # Join by event_id so Pub/Sub redelivery doesn't inflate the number of denials.
    delivered = {e["event_id"]: e["path"] for e in reporters
                 if e.get("event_id") in client_ids and e.get("path") == client_ids[e["event_id"]]}
    if collections.Counter(client_ids.values()) != expected_denials or delivered != client_ids:
        raise ValueError("Client denials, Cloud Logging, and reporter stdout have not reconciled")
    (directory / "client-responses.json").write_text(json.dumps(client_rows, indent=2) + "\n")
    data = (directory / "source.html").read_bytes()
    if not data or any((directory / f).read_bytes() != data for f in ("get.html", "post.html")):
        raise ValueError("Downloaded bytes differ from the Cloud Storage object")
    result = dict(run=run, external_ip=ip, requests=len(paths), responses=len(statuses),
                  unique_paths=len(set(paths)), status_counts=dict(sorted(counts.items())),
                  source_bytes=len(data), source_sha256=hashlib.sha256(data).hexdigest(),
                  confirmed_error_methods=7, client_denials_delivered=len(delivered), denial_event_id=same[0]["event_id"],
                  pubsub_message_id=same[0]["pubsub_message_id"],
                  reporter_distinct_events=len({e["event_id"] for e in reporters}))
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    check(Path(sys.argv[1]), sys.argv[2])

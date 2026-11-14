"""Verify real file bytes, HTTP cases and zone headers before timing experiments."""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from client import request_once
from manage import ROOT, PREFIX, Manager, add_config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    add_config(p)
    args = p.parse_args()
    manager = Manager(args)
    inventory = manager.inventory()
    host = inventory["forwarding"]["IPAddress"]
    folder = ROOT / "results/functional"
    folder.mkdir(parents=True, exist_ok=True)
    cases = [("GET", "/data/0.html", None, "United States", 200),
             ("GET", f"/{args.bucket}/data/0.html", None, "United States", 200),
             ("POST", "/", json.dumps({"filename": "data/0.html"}), "United States", 200),
             ("GET", "/data/does-not-exist.html", None, "United States", 404),
             ("PUT", "/data/0.html", None, "United States", 501),
             ("GET", "/data/0.html", None, "Iran", 400)]
    results = []
    for name, zone, role in manager.vms:
        if role != "web": continue
        direct_ip = inventory[name]["networkInterfaces"][0]["accessConfigs"][0]["natIP"]
        for method, path, body, country, status in cases:
            record = request_once(direct_ip, 8080, path, method=method, body=body,
                                  headers={"X-country": country, "Content-Type": "application/json"},
                                  expected=status, timeout=20, phase=name, sequence=len(results))
            results.append(record)
            if not record["ok"] or record["zone"] != zone:
                (folder / "responses.json").write_text(json.dumps(results, indent=2))
                raise RuntimeError("Direct backend validation failed: " + json.dumps(record))
    seen = set()
    for i in range(20):
        record = request_once(host, 8080, "/data/0.html", headers={"X-country": "United States"},
                              timeout=5, phase="load-balancer", sequence=len(results))
        results.append(record)
        if not record["ok"]:
            (folder / "responses.json").write_text(json.dumps(results, indent=2))
            raise RuntimeError("Load balancer validation failed")
        seen.add(record["zone"])
        time.sleep(1)
    if seen != {args.zone_a, args.zone_b}:
        raise RuntimeError("Both zones must serve through the load balancer")
    hashes = {r["sha256"] for r in results if r["status"] == 200}
    if len(hashes) != 1:
        raise RuntimeError("Successful GET and POST file bytes differ")
    source = subprocess.run(manager.command(["storage", "cat", f"gs://{args.bucket}/data/0.html"]),
                            capture_output=True, check=True, timeout=60).stdout
    source_hash = hashlib.sha256(source).hexdigest()
    if hashes != {source_hash}:
        raise RuntimeError("Served file bytes differ from the source GCS object")
    (folder / "source-object.json").write_text(json.dumps({"object": f"gs://{args.bucket}/data/0.html",
                                                          "bytes": len(source), "sha256": source_hash}, indent=2))
    (folder / "responses.json").write_text(json.dumps(results, indent=2) + "\n")
    # Reporter evidence must contain the forbidden events before declaring this path verified.
    text = manager.ssh(PREFIX + "-reporter", args.zone_a,
                       "sudo journalctl -u cs528-hw8-reporter.service --no-pager -o cat -n 100")
    (folder / "reporter-journal.txt").write_text(text)
    if "FORBIDDEN" not in text or '"country": "Iran"' not in text:
        raise RuntimeError("Reporter has not yet recorded the forbidden-country events")
    event_ids = set()
    for name, zone, role in manager.vms:
        if role != "web": continue
        journal = manager.ssh(name, zone, "sudo journalctl -u cs528-hw8-web.service --no-pager -o cat -n 100")
        (folder / f"{name}-journal.txt").write_text(journal)
        for line in journal.splitlines():
            try: event = json.loads(line)
            except ValueError: continue
            if event.get("event") == "forbidden_country": event_ids.add(event["event_id"])
        versions = manager.ssh(name, zone, "cat /opt/cs528-hw8/installed-requirements.txt")
        (folder / f"{name}-versions.txt").write_text(versions)
    if len(event_ids) < 2 or any(event_id not in text for event_id in event_ids):
        raise RuntimeError("Reporter events do not match the server denials")
    print(f"Verified {len(results)} HTTP cases; both zones observed; shared file SHA-256: {next(iter(hashes))}")


if __name__ == "__main__":
    main()

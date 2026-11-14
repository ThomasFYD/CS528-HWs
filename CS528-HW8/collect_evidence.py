"""Preserve a verified live run and supporting functional/cloud evidence for submission."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path
from check_submission import check
from manage import Manager, ROOT, add_config


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def hashes(root):
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path.relative_to(root)))
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("--finalize-cleanup", action="store_true", help="Only add completed cleanup verification, without calling GCP")
    add_config(p)
    args = p.parse_args()
    target = ROOT / "report/evidence"
    target.mkdir(parents=True, exist_ok=True)
    if args.finalize_cleanup:
        cleanup = json.loads((ROOT / "results/cleanup.json").read_text())
        if any(v is not None for v in cleanup.values()):
            raise SystemExit("Cleanup is not complete")
        shutil.copy2(ROOT / "results/cleanup.json", target / "cleanup.json")
        hashes(target)
        return
    verified = check(args.folder)
    if not verified["passed"]:
        raise SystemExit(json.dumps(verified))
    output = target / args.folder.name
    output.mkdir(exist_ok=True)
    for name in ("requests.jsonl", "events.jsonl", "health.jsonl", "config.json", "summary.json", "verification.json", "run-status.json", "COMPLETE"):
        shutil.copy2(args.folder / name, output / name)
    # Keep source/configuration evidence, omit any unrelated SSH public-key metadata.
    deployment = json.loads((args.folder / "deployment.json").read_text())
    for vm in deployment.values():
        if isinstance(vm, dict) and "metadata" in vm:
            vm["metadata"]["items"] = [x for x in vm["metadata"].get("items", []) if x["key"] == "startup-script"]
    (output / "deployment.json").write_text(json.dumps(deployment, indent=2) + "\n")
    shutil.copytree(ROOT / "results/functional", target / "functional", dirs_exist_ok=True)
    manager = Manager(args)
    rows = json.loads((target / "functional/responses.json").read_text())
    start, end = min(r["started_epoch"] for r in rows), max(r["finished_epoch"] for r in rows)
    query = (f'logName="projects/{args.project}/logs/cs528-hw8-web" '
             f'AND timestamp>="{stamp(start - 1)}" AND timestamp<="{stamp(end + 1)}"')
    logs = json.loads(manager.run(["logging", "read", query, "--limit=200", "--order=asc", "--format=json"]))
    (target / "functional/cloud-logging.json").write_text(json.dumps(logs, indent=2) + "\n")
    if not {"WARNING", "ERROR", "CRITICAL"}.issubset({entry.get("severity") for entry in logs}):
        raise SystemExit("Missing required Cloud Logging severities")
    (target / "final-health.json").write_text(json.dumps(manager.health(), indent=2) + "\n")
    for name, zone, role in manager.vms:
        command = f"sudo journalctl -u cs528-hw8-{role}.service --no-pager -o cat -n 150"
        (target / f"{name}-final-journal.txt").write_text(manager.ssh(name, zone, command))
    hashes(target)
    print("Verified evidence preserved in " + str(target))


if __name__ == "__main__":
    main()

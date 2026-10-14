"""Read-only evidence export and post-cleanup verification for the HW4 resources."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manage import Manager, PREFIX, parser as manager_parser


def utc():
    return datetime.now(timezone.utc).isoformat()


def targets(manager):
    zone = "--zone=" + manager.args.zone
    region = "--region=" + manager.args.region
    items = []
    for role in ("web", "reporter", "client"):
        name = PREFIX + "-" + role
        items.append((name, ["compute", "instances", "describe", name, zone]))
        items.append((name + "-boot", ["compute", "disks", "describe", name + "-boot", zone]))
    items.extend([
        (manager.address, ["compute", "addresses", "describe", manager.address, region]),
        (PREFIX + "-http", ["compute", "firewall-rules", "describe", PREFIX + "-http"]),
        (PREFIX + "-ssh", ["compute", "firewall-rules", "describe", PREFIX + "-ssh"]),
        (manager.subnet, ["compute", "networks", "subnets", "describe", manager.subnet, region]),
        (manager.network, ["compute", "networks", "describe", manager.network]),
    ])
    return items


def export(manager, parts, destination):
    partial = destination.with_suffix(destination.suffix + ".partial")
    with partial.open("w") as stream:
        subprocess.run(manager.command(parts), stdout=stream, check=True)
    partial.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify-cleanup"))
    args, configuration = parser.parse_known_args()
    manager = Manager(manager_parser().parse_args(["status", *configuration]))
    if manager.args.dry_run:
        parser.error("Evidence export does not accept --dry-run")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = ROOT / "results/final" / (args.action + "-" + stamp + "-" + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    summary = {"action": args.action, "started_at": utc(), "project": manager.args.project,
               "zone": manager.args.zone, "region": manager.args.region, "complete": False,
               "resources": []}
    try:
        for name, command in targets(manager):
            resource = manager.describe(command)
            if args.action == "capture":
                if resource is None:
                    raise RuntimeError("Expected resource missing before cleanup: " + name)
                # Instance responses embed startup scripts; retain all original
                # metadata locally for reproducibility, without executing any of it.
                (folder / (name + ".json")).write_text(json.dumps(resource, indent=2) + "\n")
            summary["resources"].append({"name": name, "present": resource is not None})
            print(name + (": present" if resource else ": absent"), flush=True)
        if args.action == "verify-cleanup":
            remaining = [r["name"] for r in summary["resources"] if r["present"]]
            if remaining:
                raise RuntimeError("Cleanup is incomplete: " + ", ".join(remaining))
        else:
            for role in ("web", "reporter"):
                service = PREFIX + "-" + role + ".service"
                command = ("date -u && "
                           f"systemctl is-enabled {service} && systemctl is-active {service} && "
                           f"sudo systemctl --no-pager --full status {service} && "
                           "sudo cat /opt/cs528-hw4/installed-requirements.txt && "
                           "sudo journalctl -u google-startup-scripts.service --no-pager -o short-iso && "
                           f"sudo journalctl -u {service} --no-pager -o short-iso")
                print("Exporting " + role + " service state, dependencies and journals", flush=True)
                export(manager, ["compute", "ssh", PREFIX + "-" + role,
                                 "--zone=" + manager.args.zone, "--command=" + command],
                       folder / (role + "-deployment.txt"))
            web = json.loads((folder / (PREFIX + "-web.json")).read_text())
            log_filter = (f'logName="projects/{manager.args.project}/logs/cs528-hw4-web" '
                          f'AND resource.labels.instance_id="{web["id"]}" AND severity>=WARNING')
            export(manager, ["logging", "read", log_filter, "--freshness=1d", "--order=desc",
                             "--limit=50000", "--format=json"], folder / "cloud-errors.json")
            if len(json.loads((folder / "cloud-errors.json").read_text())) >= 50000:
                raise RuntimeError("Cloud Logging export reached its limit; retain the remaining entries before cleanup")
        summary["complete"] = True
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        summary["error"] = str(exc)
        print("ERROR: " + str(exc), file=sys.stderr)
    finally:
        summary["finished_at"] = utc()
        summary["files"] = {p.name: {"bytes": p.stat().st_size,
                                   "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                            for p in folder.iterdir() if p.is_file()}
        (folder / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("Evidence directory: " + str(folder), flush=True)
    if summary["complete"]:
        print("All final evidence exports succeeded." if args.action == "capture" else
              "Verified: all 11 HW4 compute/network resources are absent.", flush=True)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

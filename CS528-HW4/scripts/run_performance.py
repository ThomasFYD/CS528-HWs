"""Mac-side orchestration: upload tools, measure four rounds, download evidence."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Experiment:
    def __init__(self, args):
        self.args = args
        self.run_id = args.collect or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                      + "-" + uuid.uuid4().hex[:6])
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.run_id):
            raise ValueError("Invalid run ID")
        self.remote = "hw4-perf/" + self.run_id
        self.local = ROOT / "results/performance" / self.run_id
        self.settings = self.local / "experiment.json"

    def gcloud(self, parts):
        return ["gcloud", *parts, f"--project={self.args.project}",
                f"--account={self.args.account}", "--quiet"]

    def run(self, parts, destination=None):
        command = self.gcloud(parts)
        if destination:
            partial = destination.with_suffix(destination.suffix + ".partial")
            with partial.open("w") as stream:
                subprocess.run(command, stdout=stream, check=True)
            partial.replace(destination)
        else:
            subprocess.run(command, check=True)

    def ssh_parts(self, vm, command):
        return ["compute", "ssh", vm, f"--zone={self.args.zone}",
                "--ssh-flag=-oServerAliveInterval=30", "--ssh-flag=-oServerAliveCountMax=3",
                "--command=" + command]

    def ssh(self, vm, command, destination=None):
        self.run(self.ssh_parts(vm, command), destination)

    def upload(self, vm, paths):
        self.run(["compute", "scp", *(str(p) for p in paths), f"{vm}:{self.remote}/",
                  f"--zone={self.args.zone}"])

    def collect(self):
        info = json.loads(self.settings.read_text())
        if (info["project"], info["zone"], info["account"]) != (
                self.args.project, self.args.zone, self.args.account):
            raise ValueError("Use the original project, zone and account to collect this run")
        errors = []

        def attempt(label, action):
            print("Collecting " + label, flush=True)
            try:
                action()
            except (OSError, subprocess.CalledProcessError) as exc:
                errors.append({"step": label, "error": str(exc)})

        remote = shlex.quote(self.remote)
        attempt("web resource samples", lambda: self.ssh(
            "cs528-hw4-web",
            f"touch {remote}/stop-monitor && sleep 2 && cat {remote}/web-resources.jsonl",
            self.local / "web-resources.jsonl"))
        attempt("client results", lambda: self.run([
            "compute", "scp", "--recurse", f"cs528-hw4-client:{self.remote}/client",
            str(self.local), f"--zone={self.args.zone}"]))
        since = shlex.quote(datetime.fromisoformat(info["started_at"]).astimezone(timezone.utc)
                            .strftime("%Y-%m-%d %H:%M:%S UTC"))
        for role in ("web", "reporter"):
            attempt(role + " journal", lambda role=role: self.ssh(
                "cs528-hw4-" + role,
                f"sudo journalctl -u cs528-hw4-{role}.service --since={since} --no-pager -o json",
                self.local / f"{role}-journal.jsonl"))
        info["collection_time"] = timestamp()
        log_filter = (f'logName="projects/{self.args.project}/logs/cs528-hw4-web" '
                      f'AND timestamp>="{info["started_at"]}" '
                      f'AND timestamp<="{info["collection_time"]}" AND severity>=WARNING')
        attempt("Cloud Logging records", lambda: self.run([
            "logging", "read", log_filter, "--limit=50000", "--order=asc", "--format=json"],
            self.local / "cloud-errors.json"))
        info["collection_errors"] = errors
        self.settings.write_text(json.dumps(info, indent=2) + "\n")
        if errors:
            print("Some evidence could not be collected. Fix the reported issue, then run:\n"
                  f"python3 scripts/run_performance.py --collect {self.run_id}", flush=True)
            return False
        print("Evidence saved to " + str(self.local), flush=True)
        subprocess.run([sys.executable, str(SCRIPTS / "summarize_performance.py"),
                        str(self.local)], check=True)
        return True

    def execute(self):
        if self.args.collect:
            return self.collect()
        self.local.mkdir(parents=True)
        info = {"run_id": self.run_id, "started_at": timestamp(), "project": self.args.project,
                "account": self.args.account, "zone": self.args.zone, "bucket": self.args.bucket,
                "measurement_seconds_per_group": 180, "groups": [1, 2, 3, 4]}
        self.settings.write_text(json.dumps(info, indent=2) + "\n")
        print("Run ID: " + self.run_id, flush=True)
        for role in ("web", "reporter", "client"):
            # Exclude embedded startup scripts; retain hardware, IPs, identity and dates.
            self.run(["compute", "instances", "describe", "cs528-hw4-" + role,
                      f"--zone={self.args.zone}",
                      "--format=json(name,id,creationTimestamp,status,machineType,disks,networkInterfaces,serviceAccounts,labels)"],
                     self.local / f"{role}-vm.json")
        web = json.loads((self.local / "web-vm.json").read_text())
        domain = web["networkInterfaces"][0]["accessConfigs"][0]["natIP"]
        if web.get("status") != "RUNNING":
            raise RuntimeError("Web VM is not running")
        info["domain"] = domain
        self.settings.write_text(json.dumps(info, indent=2) + "\n")
        for role in ("web", "client"):
            vm = "cs528-hw4-" + role
            checks = "test -x ~/http-client" if role == "client" else "systemctl is-active --quiet cs528-hw4-web.service"
            self.ssh(vm, f"{checks} && mkdir -p hw4-perf && mkdir {shlex.quote(self.remote)}")
            self.upload(vm, [SCRIPTS / "monitor_resources.py"] +
                        ([SCRIPTS / "stress_client.py"] if role == "client" else []))
        self.ssh("cs528-hw4-web",
                 f"cd {shlex.quote(self.remote)} && "
                 "(nohup python3 -u monitor_resources.py --output web-resources.jsonl "
                 "--stop-file stop-monitor --seconds 1800 < /dev/null > monitor.log 2>&1 & "
                 "echo $! > monitor.pid) && sleep 2 && test -s web-resources.jsonl && cat monitor.log")
        command = (f"cd {shlex.quote(self.remote)} && "
                   "timeout --signal=TERM --kill-after=10s 1000s python3 -u stress_client.py "
                   f"--domain {shlex.quote(domain)} --bucket {shlex.quote(self.args.bucket)} --output client")
        print("Starting sweep (~15 minutes). Enter your SSH key passphrase if prompted.\n"
              "Keep this terminal open; do not run extra HTTP clients during the sweep.", flush=True)
        try:
            with (self.local / "sweep-console.txt").open("w", buffering=1) as stream:
                with subprocess.Popen(self.gcloud(self.ssh_parts("cs528-hw4-client", command)),
                                      stdout=subprocess.PIPE, text=True, bufsize=1) as process:
                    for line in process.stdout:
                        print(line, end="", flush=True)
                        stream.write(line)
                    info["ssh_exit_code"] = process.wait()
        finally:
            info["sweep_command_finished_at"] = timestamp()
            self.settings.write_text(json.dumps(info, indent=2) + "\n")
            print("Raw run directory: " + str(self.local), flush=True)
        collected = self.collect()
        return info.get("ssh_exit_code") == 0 and collected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=os.getenv("HW4_PROJECT", "dazzling-seat-508219-j3"))
    p.add_argument("--account", default=os.getenv("HW4_ACCOUNT", "fangyd@bu.edu"))
    p.add_argument("--zone", default=os.getenv("HW4_ZONE", "us-central1-a"))
    p.add_argument("--bucket", default=os.getenv("HW4_BUCKET", "cs528-hw2-yf-2026"))
    p.add_argument("--collect", metavar="RUN_ID", help="Re-download an existing run without generating load")
    args = p.parse_args()
    try:
        success = Experiment(args).execute()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

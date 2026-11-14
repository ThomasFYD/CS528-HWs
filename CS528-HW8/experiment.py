"""Bounded live failover/recovery experiment; saves raw client, action and health evidence."""
import argparse
import json
import random
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from client import file_path, print_record, request_once, utc
from manage import Manager, PREFIX, ROOT, add_config


REMOTE_ACTION = r'''
import json, subprocess, sys, time, urllib.request
action = sys.argv[1]
unit = "cs528-hw8-web.service"
def prop(name):
    return subprocess.check_output(["systemctl", "show", unit, "--property="+name, "--value"], text=True).strip()
ntp = subprocess.check_output(["timedatectl", "show", "--property=NTPSynchronized", "--value"], text=True).strip()
if ntp != "yes": raise SystemExit("VM clock is not synchronized")
if prop("Restart") != "no": raise SystemExit("Automatic restart would invalidate the failure experiment")
result = {"action": action, "ntp_synchronized": ntp, "before_epoch": time.time(), "old_pid": prop("MainPID")}
if action == "stop":
    if result["old_pid"] == "0": raise SystemExit("Web service is not running")
    subprocess.run(["systemctl", "kill", "--kill-whom=all", "--signal=SIGKILL", unit], check=True)
    deadline = time.monotonic() + 5
    while prop("MainPID") != "0" and time.monotonic() < deadline: time.sleep(.05)
    if prop("MainPID") != "0": raise SystemExit("Failed to kill the web process")
    result["after_epoch"] = time.time()
else:
    subprocess.run(["systemctl", "start", unit], check=True)
    result["after_epoch"] = time.time()
    deadline = time.monotonic() + 20
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8080/healthz", timeout=1) as response:
                if response.status == 200:
                    result["ready_epoch"] = time.time()
                    break
        except OSError: pass
        time.sleep(.1)
    if "ready_epoch" not in result: raise SystemExit("Restarted service did not become ready")
result["active_state"] = prop("ActiveState")
result["pid"] = prop("MainPID")
print(json.dumps(result))
'''


def health_states(snapshot):
    result = {}
    for group in snapshot:
        for instance in group.get("status", {}).get("healthStatus", []):
            result[instance.get("instance", "").rsplit("/", 1)[-1]] = instance.get("healthState")
    return result


class Experiment:
    def __init__(self, args):
        self.args, self.manager = args, Manager(args)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.folder = args.output or ROOT / "results" / stamp
        self.folder.mkdir(parents=True, exist_ok=False)
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.phase, self.records, self.health_records, self.events = "preflight", [], [], []
        self.failures = []

    def append(self, name, data, collection):
        with self.lock:
            collection.append(data)
            with (self.folder / name).open("a") as stream:
                stream.write(json.dumps(data) + "\n")

    def action(self, action):
        command = "sudo python3 -c " + shlex.quote(REMOTE_ACTION) + " " + shlex.quote(action)
        sent = time.time()
        output = self.manager.ssh(PREFIX + "-web-a", self.args.zone_a, command, timeout=65)
        result = json.loads(output.strip().splitlines()[-1])
        result.update(client_command_sent=sent, client_command_finished=time.time(), phase=self.phase)
        # Detect gross clock disagreement; NTP status is also recorded on the VM.
        if not sent - 1 <= result["before_epoch"] <= result["client_command_finished"] + 1:
            raise RuntimeError("VM and client clocks disagree")
        self.append("events.jsonl", result, self.events)
        print("ACTION " + json.dumps(result), flush=True)
        return result

    def sample(self):
        rng, sequence, start = random.Random(self.args.seed), 0, time.monotonic()
        pending = []
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                while not self.stop.is_set():
                    if self.stop.wait(max(0, start + sequence - time.monotonic())):
                        break
                    for future in pending:
                        if future.done(): future.result()
                    pending = [f for f in pending if not f.done()]
                    if len(pending) >= 8:
                        raise RuntimeError("Client queue full; stop and debug")
                    phase, seq = self.phase, sequence
                    path = file_path(self.args.bucket, "data", rng.randint(0, 11999))
                    def task(phase=phase, seq=seq, path=path):
                        record = request_once(self.host, 8080, path, headers={"X-country": "United States"},
                                              timeout=2, sequence=seq, phase=phase)
                        self.append("requests.jsonl", record, self.records)
                        print_record(record)
                    pending.append(pool.submit(task))
                    sequence += 1
                for future in pending: future.result()
        except Exception as exc:
            self.failures.append(str(exc))
            self.stop.set()

    def poll_health(self):
        while not self.stop.is_set():
            sent = time.time()
            try:
                data = self.manager.health()
                record = {"sent_epoch": sent, "received_epoch": time.time(), "phase": self.phase,
                          "states": health_states(data), "raw": data}
            except Exception as exc:
                record = {"sent_epoch": sent, "received_epoch": time.time(), "phase": self.phase, "error": str(exc)}
            self.append("health.jsonl", record, self.health_records)
            self.stop.wait(2)

    def wait(self, seconds):
        if self.stop.wait(seconds):
            raise RuntimeError("Sampling stopped: " + "; ".join(self.failures))

    def wait_until(self, predicate, deadline, description):
        while time.time() < deadline:
            if predicate(): return
            self.wait(.25)
        self.stop.set()  # HW8 explicitly requires stopping requests within a minute of failed convergence.
        raise RuntimeError(description + " not observed within 55 seconds; client stopped; use curl to debug")

    def live_health(self, state, after):
        with self.lock:
            latest = self.health_records[-1] if self.health_records else {}
        return (latest.get("sent_epoch", 0) >= after and
                latest.get("states", {}).get(PREFIX + "-web-a") == state and
                latest.get("states", {}).get(PREFIX + "-web-b") == "HEALTHY")

    def healthy_tail(self, after, count, zones):
        with self.lock:
            rows = sorted([r for r in self.records if r["started_epoch"] >= after], key=lambda r: r["sequence"])
        if len(rows) < count: return False
        tail = rows[-count:]
        return (all(r["ok"] and r["zone"] in zones for r in tail)
                and set(r["zone"] for r in tail) == set(zones)
                and tail[-1]["started_epoch"] - tail[0]["started_epoch"] >= count - 1.5)

    def run(self):
        inventory = self.manager.inventory()
        (self.folder / "deployment.json").write_text(json.dumps(inventory, indent=2) + "\n")
        self.host = inventory["forwarding"]["IPAddress"]
        config = vars(self.args).copy()
        config["output"] = str(self.folder)
        (self.folder / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        states = health_states(self.manager.health())
        if any(states.get(PREFIX + "-web-" + s) != "HEALTHY" for s in ("a", "b")):
            raise RuntimeError("Both web VMs must be HEALTHY before starting")
        workers = [threading.Thread(target=self.sample), threading.Thread(target=self.poll_health)]
        self.phase = "baseline"
        for thread in workers: thread.start()
        needs_restart = False
        try:
            self.wait(self.args.baseline)
            if not self.healthy_tail(0, min(30, self.args.baseline - 2), [self.args.zone_a, self.args.zone_b]):
                raise RuntimeError("Baseline must contain successful responses from both zones")
            for trial in range(1, self.args.trials + 1):
                self.phase = f"trial-{trial}-stop"
                needs_restart = True
                stopped = self.action("stop")
                t0 = stopped["after_epoch"]
                self.wait_until(lambda: self.live_health("UNHEALTHY", t0)
                                and self.healthy_tail(t0, 15, [self.args.zone_b]),
                                t0 + 55, "Failover")
                self.phase = f"trial-{trial}-survivor"
                self.wait(15)
                self.phase = f"trial-{trial}-restart"
                restarted = self.action("start")
                needs_restart = False
                t1 = restarted["before_epoch"]
                self.wait_until(lambda: self.live_health("HEALTHY", t1)
                                and self.healthy_tail(t1, 15, [self.args.zone_a, self.args.zone_b]),
                                t1 + 55, "Recovery")
                self.phase = f"trial-{trial}-recovered"
                self.wait(self.args.recovered)
            (self.folder / "COMPLETE").write_text(utc() + "\n")
        finally:
            self.stop.set()
            for thread in workers: thread.join(timeout=75)
            if any(thread.is_alive() for thread in workers):
                self.failures.append("Worker did not terminate")
            if needs_restart:
                self.phase = "emergency-restore"
                self.action("start")
            (self.folder / "run-status.json").write_text(json.dumps({"complete": (self.folder / "COMPLETE").exists(),
                                                                   "worker_errors": self.failures}, indent=2) + "\n")
        if self.failures: raise RuntimeError("; ".join(self.failures))
        print("Evidence saved to " + str(self.folder))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    add_config(p)
    p.add_argument("--output", type=Path)
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--baseline", type=int, default=60)
    p.add_argument("--recovered", type=int, default=45)
    p.add_argument("--seed", type=int, default=528)
    args = p.parse_args()
    if args.dry_run or not 1 <= args.trials <= 5 or not 35 <= args.baseline <= 300 or not 20 <= args.recovered <= 120:
        p.error("Live run requires 1-5 trials, baseline 35-300s, recovered 20-120s, and no --dry-run")
    Experiment(args).run()


if __name__ == "__main__":
    main()

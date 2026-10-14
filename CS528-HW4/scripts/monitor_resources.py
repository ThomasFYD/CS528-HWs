"""Read whole-VM Linux /proc counters once per second; no extra packages needed."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import time


def utc():
    return datetime.now(timezone.utc).isoformat()


def metadata():
    try:
        sync = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        sync = "unavailable"
    return {"type": "metadata", "timestamp": utc(), "hostname": socket.gethostname(),
            "kernel": platform.release(), "logical_cpus": os.cpu_count(),
            "clock_synchronized": sync, "sample_interval_seconds": 1,
            "scope": "whole VM; CPU busy excludes idle, iowait and steal; memory=total-available"}


def default_interface(proc=Path("/proc")):
    for line in (proc / "net/route").read_text().splitlines()[1:]:
        fields = line.split()
        if fields[1] == "00000000" and int(fields[3], 16) & 1:
            return fields[0]
    raise RuntimeError("No default network interface found")


def counters(proc, interface):
    # guest/guest_nice are already included in user/nice: use only the first 8.
    cpu = list(map(int, (proc / "stat").read_text().splitlines()[0].split()[1:9]))
    memory = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, value, *_ = line.split()
        memory[key.rstrip(":")] = int(value) * 1024
    for line in (proc / "net/dev").read_text().splitlines()[2:]:
        name, values = line.split(":", 1)
        if name.strip() == interface:
            fields = values.split()
            return {"cpu": cpu, "memory_total_bytes": memory["MemTotal"],
                    "memory_used_bytes": memory["MemTotal"] - memory["MemAvailable"],
                    "rx_bytes": int(fields[0]), "tx_bytes": int(fields[8])}
    raise RuntimeError("Network interface disappeared: " + interface)


def rates(before, after, seconds):
    delta = [b - a for a, b in zip(before["cpu"], after["cpu"])]
    total = sum(delta)
    if seconds <= 0 or total <= 0 or any(n < 0 for n in delta):
        raise RuntimeError("Invalid CPU counter interval")
    rx = after["rx_bytes"] - before["rx_bytes"]
    tx = after["tx_bytes"] - before["tx_bytes"]
    if rx < 0 or tx < 0:
        raise RuntimeError("Network counters reset during measurement")
    return {"cpu_busy_pct": 100 * (total - delta[3] - delta[4] - delta[7]) / total,
            "cpu_iowait_pct": 100 * delta[4] / total,
            "cpu_steal_pct": 100 * delta[7] / total,
            "memory_used_mib": after["memory_used_bytes"] / 2**20,
            "memory_used_pct": 100 * after["memory_used_bytes"] / after["memory_total_bytes"],
            "memory_total_mib": after["memory_total_bytes"] / 2**20,
            "rx_mbps": rx * 8 / seconds / 1e6,
            "tx_mbps": tx * 8 / seconds / 1e6}


class Sampler:
    def __init__(self, proc=Path("/proc")):
        self.proc = proc
        self.interface = default_interface(proc)
        self.previous = counters(proc, self.interface)
        self.previous_mono = time.monotonic()
        self.previous_wall = utc()

    def sample(self):
        current = counters(self.proc, self.interface)
        now, wall = time.monotonic(), utc()
        elapsed = now - self.previous_mono
        record = {"type": "sample", "timestamp": wall,
                  "interval_start": self.previous_wall, "elapsed_seconds": elapsed,
                  "interface": self.interface, **rates(self.previous, current, elapsed)}
        self.previous, self.previous_mono, self.previous_wall = current, now, wall
        return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--stop-file", type=Path, required=True)
    p.add_argument("--seconds", type=int, default=1800)
    args = p.parse_args()
    if not 1 <= args.seconds <= 3600:
        p.error("Monitor lifetime must be between 1 and 3600 seconds")
    sampler = Sampler()
    deadline = time.monotonic() + args.seconds
    with args.output.open("x", buffering=1) as stream:
        stream.write(json.dumps(metadata()) + "\n")
        while time.monotonic() < deadline and not args.stop_file.exists():
            time.sleep(1)
            stream.write(json.dumps(sampler.sample()) + "\n")
        stream.write(json.dumps({"type": "finished", "timestamp": utc(),
                                 "reason": "stop_file" if args.stop_file.exists() else "lifetime_limit"}) + "\n")


if __name__ == "__main__":
    main()

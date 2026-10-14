"""Run 1, 2, 3, 4 instructor clients, each for a full three-minute window."""

import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import selectors
import shlex
import signal
import subprocess
import time

from monitor_resources import Sampler, metadata, utc


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def stop_clients(clients):
    # Each child has its own new session. Signal only groups created by this run.
    for client in clients:
        try:
            os.killpg(client["process"].pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    for client in clients:
        try:
            client["process"].wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for client in clients:
        try:
            os.killpg(client["process"].pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        client["process"].wait(timeout=5)


def client_command(binary, domain, bucket, number, timeout):
    return [str(binary), "-d", domain, "-p", "8080", "-b", "/" + bucket,
            "-w", "data", "-n", "1000000000", "-i", "11999",
            "-r", str(number - 1), "-t", str(timeout)]


def run_round(count, commands, output, seconds=180, warmup=15, sample_factory=Sampler):
    if not 1 <= count <= 4 or len(commands) != count:
        raise ValueError("Exactly 1 through 4 clients are allowed")
    output.mkdir()
    summary = {"clients": count, "requested_seconds": seconds, "warmup_seconds": warmup,
               "started_at": utc(), "complete": False, "commands": [shlex.join(c) for c in commands],
               "events": [], "note": "Quiet mode has no HTTP status/throughput counts; stop at deadline is intentional."}
    clients = []
    selector = selectors.DefaultSelector()
    events = (output / "events.jsonl").open("x", buffering=1)
    measurement_start = None
    sampler = sample_factory()
    metrics = (output / "client-resources.jsonl").open("x", buffering=1)
    metrics.write(json.dumps(metadata()) + "\n")

    def read_available(wait=0):
        for key, _ in selector.select(wait):
            client = key.data
            try:
                data = os.read(key.fd, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                data = b""
            if not data:
                selector.unregister(key.fd)
                continue
            client["log"].write(data)
            client["log"].flush()
            record = {"timestamp": utc(), "client": client["number"],
                      "phase": "measurement" if measurement_start is not None else "warmup",
                      "text": data.decode(errors="replace")}
            events.write(json.dumps(record) + "\n")
            print(f"Client {client['number']}: {record['text'].strip()[:300]}", flush=True)

    try:
        for number, command in enumerate(commands, 1):
            master, slave = pty.openpty()
            try:
                # A PTY makes the bundled Python line-buffer stdout, so a timeout
                # message survives even when the client is stopped at the deadline.
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=slave, stderr=slave, start_new_session=True)
            except BaseException:
                os.close(master)
                raise
            finally:
                os.close(slave)
            client = {"number": number, "process": process, "fd": master,
                      "log": (output / f"client-{number}.log").open("xb")}
            clients.append(client)
            selector.register(master, selectors.EVENT_READ, client)
        warmup_end = time.monotonic() + warmup
        deadline = warmup_end + seconds
        next_sample = time.monotonic() + 1
        next_progress = warmup_end
        while True:
            read_available(0.1)
            now = time.monotonic()
            if now >= next_sample:
                metrics.write(json.dumps(sampler.sample()) + "\n")
                next_sample = now + 1
            for client in clients:
                code = client["process"].poll()
                if code is not None:
                    read_available()
                    summary["events"].append({"event": "early_exit", "timestamp": utc(),
                                              "client": client["number"], "exit_code": code})
                    raise RuntimeError(f"Client {client['number']} exited early ({code}); inspect its log")
            if measurement_start is None and now >= warmup_end:
                measurement_start = now
                deadline = now + seconds
                summary["measurement_start"] = utc()
                save_json(output / "round.json", summary)
            if measurement_start is not None and now >= deadline:
                summary["measurement_end"] = utc()
                summary["measured_seconds"] = now - measurement_start
                summary["complete"] = True
                break
            if measurement_start is not None and now >= next_progress:
                print(f"{count} client(s): {now - measurement_start:.0f}/{seconds} seconds", flush=True)
                next_progress = now + 30
    except BaseException as exc:
        summary["failure"] = str(exc)
        if measurement_start is not None:
            summary["measurement_end"] = utc()
            summary["measured_seconds"] = time.monotonic() - measurement_start
        raise
    finally:
        summary["load_stop_requested_at"] = utc()
        try:
            stop_clients(clients)
            read_available()
        finally:
            summary["stopped_at"] = utc()
            summary["process_exit_codes_after_stop"] = [c["process"].poll() for c in clients]
            save_json(output / "round.json", summary)
            selector.close()
            for client in clients:
                os.close(client["fd"])
                client["log"].close()
            events.close()
            metrics.close()
    return summary


def existing_clients():
    found = []
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                if (proc / "comm").read_text().strip() == "http-client":
                    found.append(int(proc.name))
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
    return found


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--domain", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--binary", type=Path, default=Path.home() / "http-client")
    p.add_argument("--timeout", type=int, default=30)
    args = p.parse_args()
    if not 1 <= args.timeout <= 60:
        p.error("Request timeout must be 1 through 60 seconds")
    args.binary = args.binary.expanduser().resolve(strict=True)
    if not os.access(args.binary, os.X_OK):
        p.error("Instructor client must be executable")

    def interrupted(signum, _frame):
        raise RuntimeError(f"Interrupted by signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    with (Path.home() / ".cs528-hw4-stress.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another HW4 stress sweep is already running")
        if existing_clients():
            raise RuntimeError("An http-client process is already running; finish it before this sweep")
        args.output.mkdir()
        info = {**metadata(), "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "domain": args.domain, "bucket": args.bucket, "timeout_seconds": args.timeout,
                "rounds": [], "complete": False, "started_at": utc()}
        try:
            for count in (1, 2, 3, 4):
                print(f"Starting {count} client(s): 15 s warmup, then 180 s measurement", flush=True)
                commands = [client_command(args.binary, args.domain, args.bucket, n, args.timeout)
                            for n in range(1, count + 1)]
                result = run_round(count, commands, args.output / f"c{count}")
                info["rounds"].append(result)
                save_json(args.output / "sweep.json", info)
                if count < 4:
                    # The server's GCS/publish operations are bounded. Leave time
                    # for the last in-flight request to finish before the next group.
                    time.sleep(30)
            info["complete"] = True
        finally:
            info["finished_at"] = utc()
            save_json(args.output / "sweep.json", info)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Two simultaneous instructor clients, same seed, independently counted requests."""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback
import uuid
from datetime import datetime, timezone

from common import ROOT, endpoint, write_json, infra, config
from database import create_database
from analysis import summarize


def stop_process(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.wait()
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, default=ROOT / "client" / "http-client-mac")
    parser.add_argument("--requests", type=int, default=50000, help="Per client; use 100 for smoke test")
    parser.add_argument("--seed", type=int, default=528)
    parser.add_argument("--max-index", type=int, default=11999)
    parser.add_argument("--max-hours", type=float, default=6)
    args = parser.parse_args()
    if args.requests <= 0 or args.max_hours <= 0 or args.max_index < 0:
        parser.error("requests/max-hours must be positive; max-index must be nonnegative")
    client = args.client.expanduser().resolve()
    if not client.is_file() or not os.access(client, os.X_OK):
        raise SystemExit("Instructor client missing or not executable; supply the updated macOS binary")
    client_sha256 = hashlib.sha256(client.read_bytes()).hexdigest()
    if client_sha256 != config.CLIENT_SHA256:
        raise SystemExit("Client differs from the verified updated macOS binary. Re-probe it before updating CLIENT_SHA256.")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    lock = (build / "experiment.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another HW5 experiment holds the local lock")
    host, port = endpoint()
    run_id = datetime.now(timezone.utc).strftime("load-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    raw_dir = ROOT / "results" / run_id
    evidence_dir = ROOT / "report" / "evidence" / run_id
    raw_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)
    command = [str(client), "-d", host, "-p", str(port), "-b", "none",
        "-w", f"__runs/{run_id}/data", "-n", str(args.requests), "-i", str(args.max_index),
        "-r", str(args.seed), "-t", "30"]
    metadata = {"run_id": run_id, "expected_requests": args.requests * 2,
        "client_sha256": client_sha256, "commands": [command, command],
        "seed": args.seed, "started_at": datetime.now(timezone.utc).isoformat(), "complete": False}
    write_json(evidence_dir / "experiment.json", metadata)
    processes, files, db = [], [], None
    guard_paused = False
    start = time.monotonic()
    failure = None

    def phase(name):
        metadata["phase"] = name
        write_json(evidence_dir / "experiment.json", metadata)
        print("Phase: " + name, flush=True)

    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"Signal {signum}")

    old_sigterm = signal.signal(signal.SIGTERM, interrupt)
    try:
        phase("pausing_sql_guard")
        infra.pause_guard()
        guard_paused = True
        phase("ensuring_sql_running")
        infra.sql()  # Restart if the guard stopped SQL between work sessions.
        phase("opening_local_database")
        db = create_database(local=True)
        phase("verifying_database_schema")
        db.counts(run_id)  # Verify the schema and connection before launching clients.
        phase("running_clients")
        load_start = time.monotonic()
        metadata["load_started_at"] = datetime.now(timezone.utc).isoformat()
        write_json(evidence_dir / "experiment.json", metadata)
        # Launch both before waiting for either. Their PRNG seed is identical.
        for index in (1, 2):
            handle = (evidence_dir / f"client-{index}.log").open("wb")
            files.append(handle)
            processes.append(subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True))
        deadline, next_update = load_start + args.max_hours * 3600, 0
        while any(process.poll() is None for process in processes):
            now = time.monotonic()
            if now > deadline:
                raise TimeoutError("Client run exceeded its explicit time limit")
            if any(process.poll() not in (None, 0) for process in processes):
                raise RuntimeError("An instructor client exited unsuccessfully")
            if now >= next_update:
                print(f"Run {run_id}: elapsed {now - load_start:.0f}s; client exits {[p.poll() for p in processes]}", flush=True)
                next_update = now + 60
            time.sleep(1)
        metadata["load_finished_at"] = datetime.now(timezone.utc).isoformat()
        metadata["load_elapsed_seconds"] = time.monotonic() - load_start
        for handle in files:
            handle.flush()
        # Final responses can precede the timing transaction by a few milliseconds.
        phase("waiting_for_timings")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            counts = db.counts(run_id)
            if counts["requests"] == counts["request_timings"]:
                break
            time.sleep(1)
        phase("exporting_database")
        snapshot = db.snapshot(run_id)
        with gzip.open(raw_dir / "database-snapshot.json.gz", "wt") as handle:
            json.dump(snapshot, handle, default=str)
        phase("summarizing_results")
        summary = summarize(snapshot, expected=args.requests * 2)
        write_json(evidence_dir / "summary.json", summary)
        metadata["complete"] = summary["integrity"]["complete"] and all(p.returncode == 0 for p in processes)
        print(json.dumps(summary, indent=2), flush=True)
        if not metadata["complete"]:
            raise RuntimeError("Experiment integrity checks failed; inspect retained evidence before using results")
    except BaseException as exc:
        failure = exc
        metadata["failure"] = f"{type(exc).__name__}: {exc}"
        metadata["failure_phase"] = metadata.get("phase", "unknown")
        # Frame locations aid diagnosis without saving locals or credential data.
        metadata["failure_frames"] = [
            {"file": frame.filename, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)]
    finally:
        for process in processes:
            try:
                stop_process(process)
            except Exception as exc:
                metadata.setdefault("cleanup_errors", []).append(str(exc))
        for handle in files:
            handle.close()
        if db:
            try:
                db.close()
            except Exception as exc:
                metadata.setdefault("cleanup_errors", []).append(str(exc))
        metadata.update(finished_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - start,
                        exit_codes=[process.returncode for process in processes])
        if guard_paused:
            try:
                infra.resume_guard()
                metadata["guard_resumed"] = True
            except Exception as exc:
                metadata["guard_resumed"] = False
                metadata["guard_error"] = str(exc)
                if failure is None:
                    failure = exc
                    metadata["failure"] = f"{type(exc).__name__}: {exc}"
                    metadata["failure_phase"] = "resuming_sql_guard"
        metadata["phase"] = "failed" if failure else "complete"
        write_json(evidence_dir / "experiment.json", metadata)
        signal.signal(signal.SIGTERM, old_sigterm)
        lock.close()
    print("Evidence: " + str(evidence_dir), flush=True)
    if failure:
        message = f"Experiment failed during {metadata.get('failure_phase', 'unknown')}: {failure}"
        if metadata.get("guard_resumed") is False:
            message += "\nResume the hourly SQL guard: python3 infra.py resume-guard"
        elif metadata.get("guard_resumed") is True:
            message += "\nThe hourly SQL guard was restored."
        raise SystemExit(message)
    print("Experiment passed. Export/review evidence, then run cleanup.sh to avoid continued charges.", flush=True)


if __name__ == "__main__":
    main()

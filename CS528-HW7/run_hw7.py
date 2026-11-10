#!/usr/bin/env python3
"""Run one measured batch; writes durable metadata before waiting for completion."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import time

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.runners.runner import PipelineState

from hw7.pipeline import build_pipeline


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def source_hash():
    digest = hashlib.sha256()
    base = Path(__file__).resolve().parent
    for path in sorted([base / "run_hw7.py", base / "setup.py", *base.glob("hw7/*.py")]):
        digest.update(str(path.relative_to(base)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def write_metadata(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="gs://cs528-hw2-yf-2026/data/*.html")
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args, beam_args = parser.parse_known_args()
    options = PipelineOptions(beam_args)
    runner = options.get_all_options().get("runner") or "DirectRunner"
    meta_path = Path(args.metadata)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    if meta_path.exists():
        raise FileExistsError(f"Choose a new metadata path: {meta_path}")
    if not args.output.startswith("gs://"):
        output_path = Path(args.output)
        if output_path.exists() and any(output_path.iterdir()):
            raise FileExistsError(f"Choose a new empty output directory: {output_path}")
        output_path.mkdir(parents=True, exist_ok=True)
    metadata = {"runner": runner, "input": args.input, "output": args.output,
                "beam_version": beam.__version__, "python_version": platform.python_version(),
                "platform": platform.platform(), "machine": platform.machine(),
                "logical_cpus": os.cpu_count(), "beam_args": beam_args,
                "source_sha256": source_hash(), "started_at": utc_now(),
                "state": "BUILDING", "timing_definition":
                "perf_counter before pipeline construction through wait_until_finish; includes GCS input, output writes and runner startup, excludes environment installation and post-run verification"}
    write_metadata(meta_path, metadata)
    started = time.perf_counter()
    result = None
    try:
        pipeline = beam.Pipeline(options=options)
        build_pipeline(pipeline, args.input, args.output)
        result = pipeline.run()
        metadata["run_returned_seconds"] = time.perf_counter() - started
        metadata["state"] = str(result.state)
        if hasattr(result, "job_id"):
            metadata["job_id"] = result.job_id()
        write_metadata(meta_path, metadata)
        state = result.wait_until_finish(
            duration=args.timeout_seconds * 1000 if runner == "DataflowRunner" else None)
        metadata["elapsed_seconds"] = time.perf_counter() - started
        metadata["finished_at"] = utc_now()
        metadata["state"] = str(state)
        if state != PipelineState.DONE:
            if not PipelineState.is_terminal(result.state):
                result.cancel()
                metadata["cancel_requested"] = True
            raise RuntimeError(f"Pipeline did not complete successfully: {state}")
        write_metadata(meta_path, metadata)
        print(json.dumps(metadata, indent=2), flush=True)
    except BaseException as error:
        metadata["error"] = f"{type(error).__name__}: {error}"
        metadata.setdefault("elapsed_seconds", time.perf_counter() - started)
        metadata.setdefault("finished_at", utc_now())
        if result is not None and not PipelineState.is_terminal(result.state):
            try:
                result.cancel()
                metadata["cancel_requested"] = True
            except Exception as cancel_error:
                metadata["cancel_error"] = str(cancel_error)
        write_metadata(meta_path, metadata)
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()

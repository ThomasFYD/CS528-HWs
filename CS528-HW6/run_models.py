#!/usr/bin/env python3
"""Run the two models from Cloud SQL, or explicitly audit a local HW5 snapshot."""
import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import config as C
from database import audit_source, connect, hashes, migrate
from models import train_models


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def run(args):
    started = time.monotonic()
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    if args.snapshot:
        with gzip.open(args.snapshot, "rt") as stream:
            snapshot = json.load(stream)
        audit = audit_source(snapshot)
        audit.update(source_hashes=hashes(snapshot), mode="local snapshot audit; SQL migration not executed")
        rows = snapshot["requests"]
        mode = "LOCAL_SNAPSHOT"
    else:
        engine, connector = connect()
        try:
            rows, audit = migrate(engine)
        finally:
            engine.dispose(); connector.close()
        mode = "CLOUD_SQL_ON_VM"
    write_json(output/"migration.json", audit)
    metrics = train_models(rows, output)
    metrics.update(mode=mode, run_id=C.RUN_ID,
        completed_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started,
        host=platform.node(), python=platform.python_version(),
        versions={p:version(p) for p in ("scikit-learn","numpy","pandas","scipy","SQLAlchemy","PyMySQL")},
        source_sha256=os.environ.get("HW6_SOURCE_SHA256"),
        output_uri=f"gs://{C.BUCKET}/cs528-hw6/runs/{args.cloud_run}/" if args.cloud_run else None)
    write_json(output/"metrics.json", metrics)
    country, income = metrics["country"], metrics["income"]
    summary = (f"CS528 HW6 - Yide Fang\nExecution: {mode}\nSource run: {C.RUN_ID}\n"
        f"Seed: {C.SEED}\nInput requests: {len(rows)}\n"
        f"Country model: {country['model']}\nCountry train/test: {country['train_rows']}/{country['test_rows']} requests\n"
        f"Country accuracy: {country['accuracy']:.4%} ({country['correct']}/{country['test_rows']}); goal >=99%\n"
        f"Country train/test shared IPs: {country['shared_ips']}\n"
        f"Income model: {income['model']}\nIncome selection train/validation/test: 60000/20000/20000\n"
        f"Income final train: {income['final_train_rows']}\n"
        f"Income validation scores: {json.dumps(income['validation_scores'],sort_keys=True)}\n"
        f"Income test accuracy: {income['accuracy']:.4%} ({income['correct']}/{income['test_rows']}); aim >=35%\n"
        f"Income majority baseline: {income['majority_baseline_accuracy']:.4%}\n"
        f"Income goal met: {income['target_met']}\n"
        f"Output bucket: {metrics['output_uri'] or 'Local verification only'}\n")
    if not income["target_met"]:
        summary += "Income accuracy is below the 35% aim. Report this result; do not change the test set or seed to chase the target.\n"
    (output/"summary.txt").write_text(summary)
    # Completion marker includes checksums of every submitted data/result file.
    files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
    manifest = {"status":"success", "mode":mode, "files":files,
                "source_sha256":metrics["source_sha256"], "cloud_run":args.cloud_run}
    if args.cloud_run:
        from google.cloud import storage
        bucket = storage.Client(project=C.PROJECT).bucket(C.BUCKET)
        prefix = f"cs528-hw6/runs/{args.cloud_run}/"
        for name in sorted(files):
            bucket.blob(prefix+name).upload_from_filename(str(output/name),if_generation_match=0)
        bucket.blob(prefix+"done.json").upload_from_string(json.dumps(manifest),content_type="application/json",if_generation_match=0)
    write_json(output/"done.json",manifest)
    print(summary,flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot",type=Path,help="Offline only: use the HW5 gzip JSON backup")
    parser.add_argument("--cloud-run",help="Upload verified VM outputs to this unique run prefix")
    parser.add_argument("--output",type=Path,required=True,help="New output directory; existing results are never overwritten")
    args = parser.parse_args()
    if args.snapshot and args.cloud_run: parser.error("Offline output cannot be labeled/uploaded as a cloud run")
    if args.cloud_run and not re.fullmatch(r"[a-z0-9-]{1,48}",args.cloud_run): parser.error("Invalid run identifier")
    run(args)


if __name__ == "__main__": main()

#!/usr/bin/env python3
"""Reproduce the frozen income follow-up; does not change the submitted model."""
import os
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory for local predictions and metrics")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new directory.")

    import pandas as pd
    from catboost import CatBoostClassifier
    sys.path.insert(0, str(ROOT))
    from models import evaluate, features, income_split

    evidence = ROOT / "report/evidence"
    record = json.loads((evidence / "income-optimization.json").read_text())
    selection_path = evidence / "income-selection-frozen.json"
    selection_bytes = selection_path.read_bytes()
    selection = json.loads(selection_bytes)
    original = record["final_evaluation"]
    if hashlib.sha256(selection_bytes).hexdigest() != original["selection_sha256"]:
        parser.error("Frozen selection checksum mismatch.")
    if hashlib.sha256(args.snapshot.read_bytes()).hexdigest() != original["source_snapshot_sha256"]:
        parser.error("This experiment requires the original formal HW5 snapshot.")
    with gzip.open(args.snapshot, "rt") as stream:
        rows = json.load(stream)["requests"]
    train, validation, test = income_split(rows)
    membership = "\n".join(row["request_id"] for row in test).encode()
    if hashlib.sha256(membership).hexdigest() != record["test_membership_sha256"]:
        parser.error("Test partition differs from the original experiment.")

    model = CatBoostClassifier(**selection["parameters"])
    model.fit(features(train + validation), [row["income"] for row in train + validation])
    predictions = model.predict(features(test)).ravel().tolist()
    metrics = evaluate([row["income"] for row in test], predictions)
    metrics.update(mode="LOCAL_SNAPSHOT_FOLLOWUP_REPRODUCTION",
        model="catboost_demographics_4", target_met=metrics["accuracy"] >= .35,
        final_train_rows=len(train) + len(validation),
        selection_sha256=original["selection_sha256"],
        source_snapshot_sha256=original["source_snapshot_sha256"],
        versions={name: importlib.metadata.version(name)
                  for name in ["catboost", "numpy", "pandas", "scikit-learn"]})
    args.output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame([{"request_id": row["request_id"], "actual_income": row["income"],
                   "predicted_income": pred, "correct": row["income"] == pred}
                  for row, pred in zip(test, predictions)]).to_csv(
                      args.output / "income_predictions.csv", index=False)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"Local follow-up accuracy: {metrics['accuracy']:.3%}; "
          f"35% target met: {metrics['target_met']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Re-export a preserved experiment from SQL without re-running the clients."""
import argparse
import gzip
import json
import re
from common import ROOT, write_json
from database import create_database
from analysis import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--expected", type=int, default=100000)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("Invalid run ID")
    db = create_database(local=True)
    try:
        snapshot = db.snapshot(args.run_id)
    finally:
        db.close()
    raw = ROOT / "results" / args.run_id
    raw.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw / "database-snapshot.json.gz", "wt") as stream:
        json.dump(snapshot, stream, default=str)
    summary = summarize(snapshot, args.expected)
    write_json(ROOT / "report" / "evidence" / args.run_id / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Print the three verified rankings after the timed pipeline has completed."""
import argparse
import json
from pathlib import Path
from verify_results import validate

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--metadata", required=True)
args = parser.parse_args()
metadata = json.loads(Path(args.metadata).read_text())
results = validate(metadata)
print(f"Runner: {metadata['runner']}")
print(f"Runtime: {metadata['elapsed_seconds']:.3f} seconds")
for kind in ("incoming", "outgoing", "trigrams"):
    print(f"\nTop 5 {kind}:")
    for rank, row in enumerate(results["top5"][kind], 1):
        print(f"{rank}. {row['item']}: {row['count']:,}")
print("\nTotals:")
print(json.dumps(results["totals"], indent=2))

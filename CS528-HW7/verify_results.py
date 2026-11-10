#!/usr/bin/env python3
"""Validate full outputs and compare runners; only downloads the small result files."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


OUTPUT_FILES = ["files.jsonl", "totals.jsonl"] + [
    f"{kind}-{suffix}" for kind in ("incoming", "outgoing", "trigrams")
    for suffix in ("counts.jsonl", "top5.json")]


def canonical_hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_outputs(prefix):
    if prefix.startswith("gs://"):
        from google.cloud import storage
        bucket_name, folder = prefix[5:].split("/", 1)
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        data = {name: bucket.blob(folder.rstrip("/") + "/" + name).download_as_text() for name in OUTPUT_FILES}
        client.close()
    else:
        data = {name: (Path(prefix) / name).read_text() for name in OUTPUT_FILES}
    return {name: [json.loads(line) for line in text.splitlines() if line] for name, text in data.items()}


def validate(metadata, expected_files=None):
    if metadata["state"] != "DONE":
        raise ValueError("Only successfully completed jobs can be verified")
    outputs = load_outputs(metadata["output"])
    audit = sorted(outputs["files.jsonl"], key=lambda row: row["file"])
    names = [row["file"] for row in audit]
    assert len(names) == len(set(names)), "Duplicate files"
    if expected_files is not None:
        assert len(names) == expected_files, (len(names), expected_files)
    totals = dict(outputs["totals.jsonl"])
    assert totals["files"] == len(names)
    for key in ("bytes", "words", "trigrams", "outgoing", "ignored_links"):
        assert totals[key] == sum(row[key] for row in audit), key
    assert all(row["trigrams"] == max(row["words"] - 2, 0) for row in audit)
    counts, tops, hashes, ties = {}, {}, {}, {}
    for kind in ("incoming", "outgoing", "trigrams"):
        pairs = outputs[f"{kind}-counts.jsonl"]
        counts[kind] = dict(pairs)
        assert len(pairs) == len(counts[kind]), f"Duplicate {kind} keys"
        assert all(isinstance(v, int) and v >= 0 for v in counts[kind].values())
        expected_top = [{"item": k, "count": v} for k, v in sorted(pairs, key=lambda kv: (-kv[1], kv[0]))[:5]]
        assert outputs[f"{kind}-top5.json"] == [expected_top], kind
        tops[kind] = expected_top
        cutoff = expected_top[-1]["count"] if expected_top else None
        ties[kind] = {"cutoff_count": cutoff, "items_at_cutoff": sum(v == cutoff for v in counts[kind].values())}
        hashes[kind] = canonical_hash(counts[kind])
    assert set(counts["incoming"]) == set(names)
    assert set(counts["outgoing"]) == set(names)
    assert counts["outgoing"] == {row["file"]: row["outgoing"] for row in audit}
    assert sum(counts["incoming"].values()) == sum(counts["outgoing"].values()) == totals["outgoing"]
    assert sum(counts["trigrams"].values()) == totals["trigrams"]
    return {"totals": totals, "top5": tops, "cutoff_ties": ties,
            "distinct_trigrams": len(counts["trigrams"]), "count_sha256": hashes,
            "file_audit_sha256": canonical_hash(audit),
            "input_sha256": canonical_hash([[row["file"], row["bytes"], row["sha256"]] for row in audit]),
            "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", required=True)
    parser.add_argument("--cloud")
    parser.add_argument("--expected-files", type=int, default=12000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    local = json.loads(Path(args.local).read_text())
    summary = {"local": local, "results": validate(local, args.expected_files)}
    if args.cloud:
        cloud = json.loads(Path(args.cloud).read_text())
        cloud_verified = validate(cloud, args.expected_files)
        assert local["input"] == cloud["input"]
        assert local["source_sha256"] == cloud["source_sha256"]
        assert local["beam_version"] == cloud["beam_version"]
        assert summary["results"] == cloud_verified, "Runner outputs or input contents differ"
        summary["cloud"] = cloud
        summary["runners_match"] = True
        summary["cloud_over_local_ratio"] = cloud["elapsed_seconds"] / local["elapsed_seconds"]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

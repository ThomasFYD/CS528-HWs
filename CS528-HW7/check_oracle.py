#!/usr/bin/env python3
"""Independent oracle for the exact HW2 generator; never used in measured jobs."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import re

from verify_results import load_outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--generator", default="../CS528-HW2/generate-content.py")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text())
    actual = load_outputs(metadata["output"])
    specification = importlib.util.spec_from_file_location("hw2_generator", args.generator)
    generator = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(generator)
    text = io.StringIO()
    generator.add_text(text)
    generator.add_link(text, 0)
    # The instructor template is fixed ASCII, so an independent tag-removal
    # expression and word expression suffice for this particular oracle.
    words = re.findall(r"[a-z]+", re.sub(r"<[^>]*>", " ", text.getvalue()).lower())
    inside = Counter(" ".join(words[j:j + 3]) for j in range(len(words) - 2))
    boundary = Counter([" ".join(words[-2:] + words[:1]), " ".join(words[-1:] + words[:2])])
    rng = random.Random(0)
    incoming = Counter({f"{i}.html": 0 for i in range(12000)})
    outgoing, trigram_counts = {}, Counter()
    expected_hashes = {}
    total_words = 0
    for i in range(12000):
        count = rng.randrange(1, 325) - 1
        outgoing[f"{i}.html"] = count
        body = io.StringIO()
        generator.add_headers(body)
        for _ in range(count):
            target = rng.randrange(0, 12000)
            incoming[f"{target}.html"] += 1
            generator.add_text(body)
            generator.add_link(body, target)
        generator.add_footers(body)
        expected_hashes[f"{i}.html"] = hashlib.sha256(body.getvalue().encode()).hexdigest()
        for key, value in inside.items():
            trigram_counts[key] += value * count
        for key, value in boundary.items():
            trigram_counts[key] += value * max(0, count - 1)
        total_words += len(words) * count
    trigram_counts = {k: v for k, v in trigram_counts.items() if v}
    assert dict(actual["incoming-counts.jsonl"]) == incoming
    assert dict(actual["outgoing-counts.jsonl"]) == outgoing
    assert dict(actual["trigrams-counts.jsonl"]) == trigram_counts
    assert {r["file"]: r["sha256"] for r in actual["files.jsonl"]} == expected_hashes
    assert dict(actual["totals.jsonl"])["words"] == total_words
    evidence = {"verified": True, "all_12000_file_hashes_match_generator": True,
                "all_incoming_counts_match": True, "all_outgoing_counts_match": True,
                "all_trigram_counts_match": True, "generator_seed": 0,
                "generator_arguments": "-n 12000 -m 325", "template_words": len(words),
                "links": sum(outgoing.values()), "words": total_words,
                "trigrams": sum(trigram_counts.values()),
                "generator_sha256": hashlib.sha256(Path(args.generator).read_bytes()).hexdigest(),
                "method": "Independently replay random draws and exact HTML bytes; compute trigrams algebraically from fixed template and two boundary triples."}
    Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()

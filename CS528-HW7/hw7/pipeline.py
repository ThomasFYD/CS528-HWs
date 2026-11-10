"""Beam transforms. Whole-file parsing preserves line-spanning trigrams."""
import json
import posixpath
from urllib.parse import urlsplit

import apache_beam as beam
from apache_beam.io import fileio
from apache_beam.metrics import Metrics

from hw7.parsing import parse_document


def json_line(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def rank_key(pair):
    return (-pair[1], pair[0])


def format_top(pairs):
    return [{"item": key, "count": value} for key, value in sorted(pairs, key=rank_key)]


class ParseDocument(beam.DoFn):
    def __init__(self, input_root):
        self.input_root = input_root
        self.files = Metrics.counter("hw7", "files_parsed")

    def process(self, readable, valid_names):
        result = parse_document(readable.metadata.path, readable.read(), self.input_root, valid_names)
        self.files.inc()
        yield result


def emit_totals(audit):
    yield ("files", 1)
    for key in ("bytes", "words", "trigrams", "outgoing", "ignored_links"):
        yield (key, audit[key])
    yield ("nonempty_word_files", int(audit["words"] > 0))


def save(pcoll, label, prefix, filename):
    return (pcoll
            | f"{label}/JSON" >> beam.Map(json_line)
            | f"{label}/Write" >> beam.io.WriteToText(
                prefix.rstrip("/") + "/" + filename,
                num_shards=1, shard_name_template=""))


def build_pipeline(p, input_pattern, output_prefix):
    input_root = input_pattern.rsplit("/", 1)[0]
    files = p | "List HTML objects" >> fileio.MatchFiles(
        input_pattern, empty_match_treatment=fileio.EmptyMatchTreatment.DISALLOW)
    names = files | "File membership" >> beam.Map(
        lambda metadata: (posixpath.basename(urlsplit(metadata.path).path), True))
    parsed = (files
              | "Distribute files" >> beam.Reshuffle()
              | "Open files" >> fileio.ReadMatches()
              | "Parse HTML and combine within file" >> beam.ParDo(
                  ParseDocument(input_root), beam.pvalue.AsDict(names)))
    audit = parsed | "Audit records" >> beam.Map(lambda row: row["audit"])
    outgoing = audit | "Outgoing counts" >> beam.Map(lambda row: (row["file"], row["outgoing"]))
    zero_incoming = names | "Include zero indegree files" >> beam.Map(lambda kv: (kv[0], 0))
    edges = parsed | "Incoming contributions" >> beam.FlatMap(lambda row: row["links"])
    incoming = ((zero_incoming, edges)
                | "All incoming contributions" >> beam.Flatten()
                | "Sum incoming counts" >> beam.CombinePerKey(sum))
    trigrams = (parsed
                | "Trigram contributions" >> beam.FlatMap(lambda row: row["trigrams"])
                | "Sum trigram counts" >> beam.CombinePerKey(sum))
    totals = (audit
              | "Document totals" >> beam.FlatMap(emit_totals)
              | "Sum totals" >> beam.CombinePerKey(sum))
    save(audit, "Audit", output_prefix, "files.jsonl")
    save(totals, "Totals", output_prefix, "totals.jsonl")
    for label, counts in (("incoming", incoming), ("outgoing", outgoing), ("trigrams", trigrams)):
        save(counts, label + " counts", output_prefix, label + "-counts.jsonl")
        top = (counts
               | label + " top 5" >> beam.combiners.Top.Smallest(5, key=rank_key)
               | label + " ranked rows" >> beam.Map(format_top))
        save(top, label + " ranking", output_prefix, label + "-top5.json")
    return {"incoming": incoming, "outgoing": outgoing, "trigrams": trigrams, "audit": audit}

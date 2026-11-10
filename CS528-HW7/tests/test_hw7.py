from collections import Counter
import json
from pathlib import Path

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
import pytest

from hw7.parsing import parse_document, target_name
from hw7.pipeline import build_pipeline


def parse(text, names=("a.html", "b.html", "c.html")):
    return parse_document("gs://bucket/data/a.html", text.encode(), "gs://bucket/data", dict.fromkeys(names))


def test_link_multiplicity_self_links_and_unknown_targets():
    row = parse('<a HREF="b.html">One</a><a href="b.html#part">two</a>'
                '<a href="#self">three</a><a href="missing.html">four</a>'
                '<a href="https://elsewhere.test/b.html">five</a>')
    assert dict(row["links"]) == {"b.html": 2, "a.html": 1}
    assert row["audit"]["ignored_links"] == 2


@pytest.mark.parametrize("href,expected", [
    ("./b.html?x=1#y", "b.html"),
    ("../other/b.html", None),
    ("gs://bucket/data/b.html", "b.html"),
    ("https://storage.googleapis.com/bucket/data/b.html", "b.html"),
    ("https://storage.googleapis.com/other/data/b.html", None),
    ("javascript:alert(1)", None),
])
def test_link_resolution(href, expected):
    assert target_name(href, "gs://bucket/data/a.html", "gs://bucket/data") == expected


def test_visible_text_entities_inline_tags_and_line_boundaries():
    row = parse('<head><title>ignore this title</title></head><body>'
                '<script>ignore this script</script><style>ignore this style</style>'
                '<p>HELLO, w<b>or</b>ld!\nAgain &amp; again.</p>'
                '<p>Don’t stop.</p><!-- ignore comment --></body>')
    assert row["audit"]["words"] == 6
    assert dict(row["trigrams"]) == {
        "hello world again": 1, "world again again": 1,
        "again again don't": 1, "again don't stop": 1,
    }


def test_empty_and_short_documents():
    for text, words in [("<html><body></body></html>", 0), ("One two", 2)]:
        row = parse(text)
        assert row["audit"]["words"] == words
        assert row["audit"]["outgoing"] == 0
        assert row["trigrams"] == []


def test_overlapping_trigrams():
    assert dict(parse("a a a a")["trigrams"]) == {"a a a": 2}


def test_complete_beam_pipeline_known_answers(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    fixtures = {
        "a.html": '<p>RED blue\ngreen red</p><a href="b.html"></a><a href="b.html"></a>',
        "b.html": '<p>red blue green</p><a href="a.html"></a>',
        "c.html": '<p>red blue</p>',
        "d.html": '<body></body>',
        "e.html": '<body></body>',
        "f.html": '<body></body>',
    }
    for name, content in fixtures.items():
        (inputs / name).write_text(content)
    output = tmp_path / "output"
    with beam.Pipeline(options=PipelineOptions([
        "--runner=apache_beam.runners.portability.fn_api_runner.FnApiRunner", "--direct_num_workers=1", "--direct_running_mode=in_memory"])) as p:
        build_pipeline(p, str(inputs / "*.html"), str(output))
    def read(name):
        return [json.loads(line) for line in (output / name).read_text().splitlines()]
    assert dict(read("incoming-counts.jsonl")) == {
        "a.html": 1, "b.html": 2, "c.html": 0, "d.html": 0, "e.html": 0, "f.html": 0}
    assert dict(read("outgoing-counts.jsonl")) == {
        "a.html": 2, "b.html": 1, "c.html": 0, "d.html": 0, "e.html": 0, "f.html": 0}
    assert dict(read("trigrams-counts.jsonl")) == {"red blue green": 2, "blue green red": 1}
    assert read("incoming-top5.json") == [[
        {"item": "b.html", "count": 2}, {"item": "a.html", "count": 1},
        {"item": "c.html", "count": 0}, {"item": "d.html", "count": 0},
        {"item": "e.html", "count": 0}]]
    assert dict(read("totals.jsonl"))["trigrams"] == 3
    assert len(read("files.jsonl")) == 6


def test_missing_input_fails(tmp_path):
    with pytest.raises(Exception, match="Empty match"):
        with beam.Pipeline(options=PipelineOptions(["--runner=apache_beam.runners.portability.fn_api_runner.FnApiRunner"])) as p:
            build_pipeline(p, str(tmp_path / "*.html"), str(tmp_path / "out"))

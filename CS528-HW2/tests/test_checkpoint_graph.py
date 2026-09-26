from types import SimpleNamespace

import pytest

from src import checkpoint_graph


@pytest.fixture
def dataset():
    bucket = SimpleNamespace(name="test-bucket")

    blobs = [
        SimpleNamespace(
            name=f"data/{name}.html",
            bucket=bucket,
            generation=1,
        )
        for name in ("a", "b", "c", "d")
    ]

    pages = {
        "data/a.html": (
            '<a href="b.html">B</a>'
            '<a href="b.html">B again</a>'
        ),
        "data/b.html": '<a href="c.html">C</a>',
        "data/c.html": '<a href="a.html">A</a>',
        "data/d.html": "<html>No links</html>",
    }

    return blobs, pages


def test_resume_preserves_links_and_skips_saved_files(
    tmp_path, monkeypatch, dataset
):
    blobs, pages = dataset
    checkpoint = tmp_path / "checkpoint.pkl"

    def interrupted_download(blob):
        if blob.name == "data/d.html":
            raise RuntimeError("Simulated interruption")
        return pages[blob.name]

    monkeypatch.setattr(
        checkpoint_graph,
        "download_html",
        interrupted_download,
    )

    # Save after two files, then simulate a failure on the fourth.
    with pytest.raises(RuntimeError, match="Simulated interruption"):
        checkpoint_graph.build_graph(
            blobs,
            checkpoint_path=checkpoint,
            save_every=2,
        )

    assert checkpoint.exists()

    downloaded_after_resume = []

    def successful_download(blob):
        downloaded_after_resume.append(blob.name)
        return pages[blob.name]

    monkeypatch.setattr(
        checkpoint_graph,
        "download_html",
        successful_download,
    )

    outgoing, incoming = checkpoint_graph.build_graph(
        blobs,
        resume=True,
        checkpoint_path=checkpoint,
        save_every=2,
    )

    # A and B were saved; C was not yet saved and must be read again.
    assert downloaded_after_resume == [
        "data/c.html",
        "data/d.html",
    ]

    assert outgoing == {
        "a.html": ["b.html", "b.html"],
        "b.html": ["c.html"],
        "c.html": ["a.html"],
        "d.html": [],
    }

    assert incoming == {
        "a.html": ["c.html"],
        "b.html": ["a.html", "a.html"],
        "c.html": ["b.html"],
        "d.html": [],
    }


def test_resume_rejects_changed_dataset(
    tmp_path, monkeypatch, dataset
):
    blobs, pages = dataset
    checkpoint = tmp_path / "checkpoint.pkl"

    monkeypatch.setattr(
        checkpoint_graph,
        "download_html",
        lambda blob: pages[blob.name],
    )

    checkpoint_graph.build_graph(
        blobs,
        checkpoint_path=checkpoint,
        save_every=2,
    )

    # Simulate an object being replaced in the bucket.
    blobs[0].generation = 2

    with pytest.raises(ValueError, match="current dataset"):
        checkpoint_graph.build_graph(
            blobs,
            resume=True,
            checkpoint_path=checkpoint,
        )
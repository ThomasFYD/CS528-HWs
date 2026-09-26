import hashlib
import json
import os
import pickle
from pathlib import Path, PurePosixPath
from time import perf_counter

from src.graph import download_html, parse_links


def save_checkpoint(path, signature, outgoing):
    """Write a temporary file, then replace the checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    state = {
        "version": 1,
        "signature": signature,
        "outgoing": outgoing,
    }

    with temporary_path.open("wb") as stream:
        pickle.dump(state, stream, protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())

    temporary_path.replace(path)


def build_graph(
    blobs,
    resume=False,
    checkpoint_path="results/graph_checkpoint.pkl",
    save_every=25,
):
    if save_every < 1:
        raise ValueError("save_every must be positive")

    blobs = sorted(blobs, key=lambda blob: blob.name)
    nodes = [PurePosixPath(blob.name).name for blob in blobs]

    if len(set(nodes)) != len(nodes):
        raise ValueError("Duplicate page filenames in the dataset")

    # Detect changes to the bucket, object names, or object versions.
    manifest = []

    for blob in blobs:
        if blob.generation is None:
            raise ValueError(
                f"Missing object generation for {blob.name}"
            )

        manifest.append(
            (blob.bucket.name, blob.name, str(blob.generation))
        )

    signature = hashlib.sha256(
        json.dumps(manifest).encode("utf-8")
    ).hexdigest()

    path = Path(checkpoint_path)
    outgoing = {}

    if resume and path.exists():
        # Only load checkpoints created by your own program.
        with path.open("rb") as stream:
            state = pickle.load(stream)

        if (
            state.get("version") != 1
            or state.get("signature") != signature
        ):
            raise ValueError(
                "Checkpoint does not match the current dataset. "
                "Do not resume using this checkpoint."
            )

        outgoing = state["outgoing"]

        if list(outgoing) != nodes[:len(outgoing)]:
            raise ValueError("Checkpoint contains invalid progress")

        print(
            f"Resuming from {len(outgoing)}/{len(blobs)} files",
            flush=True,
        )

    elif resume:
        print(
            "No checkpoint found. Starting from the beginning.",
            flush=True,
        )
    else:
        print("Starting a fresh graph build.", flush=True)

    node_set = set(nodes)
    total = len(blobs)
    completed = len(outgoing)
    start = perf_counter()

    for index in range(completed, total):
        blob = blobs[index]
        source = nodes[index]

        if index == completed or index % save_every == 0:
            print(
                f"Downloading {index + 1}/{total}: {blob.name}",
                flush=True,
            )

        html_text = download_html(blob)

        outgoing[source] = [
            target
            for target in parse_links(html_text)
            if target in node_set
        ]

        finished = index + 1

        if finished % save_every == 0 or finished == total:
            save_checkpoint(path, signature, outgoing)

            print(
                f"Checkpoint saved: {finished}/{total} "
                f"({100 * finished / total:.1f}%), "
                f"this session: {perf_counter() - start:.1f}s",
                flush=True,
            )

    # Reconstruct incoming edges once, including restored pages.
    incoming = {node: [] for node in nodes}

    for source, targets in outgoing.items():
        for target in targets:
            incoming[target].append(source)

    return outgoing, incoming
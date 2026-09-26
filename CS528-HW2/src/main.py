import argparse
import pickle
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY

from src.checkpoint_graph import build_graph
from src.closeness import calculate_closeness
from src.degree_stats import (
    calculate_degree_statistics,
    print_degree_statistics,
)
from src.pagerank import calculate_pagerank


BUCKET_NAME = "cs528-hw2-yf-2026"
PREFIX = "data/"
EXPECTED_FILE_COUNT = 12000
CACHE_PATH = Path("results/graph_cache.pkl")
STORAGE_RETRY = DEFAULT_RETRY.with_timeout(600.0)


def read_graph_from_bucket(resume=False):
    client = storage.Client.create_anonymous_client()

    try:
        print(f"Reading bucket: {BUCKET_NAME}")
        print(f"Prefix: {PREFIX}")

        blobs = []

        for blob in client.list_blobs(
            BUCKET_NAME,
            prefix=PREFIX,
            page_size=1000,
            timeout=(10, 120),
            retry=STORAGE_RETRY,
        ):
            if blob.name.endswith(".html"):
                blobs.append(blob)

                if len(blobs) % 1000 == 0:
                    print(
                        f"Listed {len(blobs)} HTML files",
                        flush=True,
                    )

        print(f"HTML files found: {len(blobs)}")

        if len(blobs) != EXPECTED_FILE_COUNT:
            raise RuntimeError(
                f"Expected {EXPECTED_FILE_COUNT} HTML files, "
                f"found {len(blobs)}"
            )

        return build_graph(blobs, resume=resume)

    finally:
        client.close()


def save_graph_cache(outgoing, incoming):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CACHE_PATH.open("wb") as cache_file:
        pickle.dump(
            (outgoing, incoming),
            cache_file,
            protocol=pickle.HIGHEST_PROTOCOL,
        )

    print(f"Graph cache saved to: {CACHE_PATH}")


def load_graph_cache():
    with CACHE_PATH.open("rb") as cache_file:
        return pickle.load(cache_file)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Analyze the CS528 web graph"
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--use-cache",
        action="store_true",
        help="Load the completed graph cache for development",
    )

    mode.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume from a matching checkpoint; "
            "start fresh if none exists"
        ),
    )

    return parser.parse_args()


def main():
    args = parse_arguments()
    total_start = perf_counter()

    print(
        f"Run started (UTC): "
        f"{datetime.now(timezone.utc).isoformat()}"
    )

    if args.use_cache:
        print("Mode: completed development cache")
    elif args.resume:
        print("Mode: checkpoint recovery")
        print(
            "Timing covers this invocation only, "
            "not any previous sessions."
        )
    else:
        print("Mode: fresh GCS read")

    graph_start = perf_counter()

    if args.use_cache:
        if not CACHE_PATH.exists():
            raise FileNotFoundError(
                f"Cache not found: {CACHE_PATH}"
            )

        outgoing, incoming = load_graph_cache()
        graph_time = perf_counter() - graph_start

        print(f"Cache loading time: {graph_time:.2f} seconds")

    else:
        outgoing, incoming = read_graph_from_bucket(
            resume=args.resume
        )
        graph_time = perf_counter() - graph_start

        label = (
            "Graph preparation time (this invocation)"
            if args.resume
            else "Graph construction time"
        )

        print(f"{label}: {graph_time:.2f} seconds")
        save_graph_cache(outgoing, incoming)

    print(f"\nNodes: {len(outgoing)}")
    print(
        f"Links: "
        f"{sum(len(targets) for targets in outgoing.values())}"
    )

    statistics_start = perf_counter()

    outgoing_results = calculate_degree_statistics(outgoing)
    incoming_results = calculate_degree_statistics(incoming)

    print_degree_statistics(
        "Outgoing-link statistics", outgoing_results
    )
    print_degree_statistics(
        "Incoming-link statistics", incoming_results
    )

    statistics_time = perf_counter() - statistics_start
    print(f"\nStatistics time: {statistics_time:.2f} seconds")

    pagerank_start = perf_counter()

    ranks, iterations, final_change = calculate_pagerank(
        outgoing
    )

    top_five = sorted(
        ranks.items(),
        key=lambda item: (-item[1], item[0]),
    )[:5]

    pagerank_time = perf_counter() - pagerank_start

    print("\nPageRank results")
    print(f"Iterations: {iterations}")
    print(f"Final total change: {final_change:.10f}")
    print(f"Sum of PageRank scores: {sum(ranks.values()):.10f}")
    print("Top 5 pages:")

    for position, (page, score) in enumerate(top_five, start=1):
        print(f"  {position}. {page}: {score:.10f}")

    print(f"PageRank time: {pagerank_time:.2f} seconds")

    closeness_start = perf_counter()

    best_node, best_score, _ = calculate_closeness(
        outgoing,
        progress_interval=500,
    )

    closeness_time = perf_counter() - closeness_start

    print("\nCloseness centrality results")
    print(f"Best node: {best_node}")
    print(f"Score: {best_score:.10f}")
    print(f"Closeness time: {closeness_time:.2f} seconds")

    total_time = perf_counter() - total_start
    print(f"\nTotal time (this invocation): {total_time:.2f} seconds")


if __name__ == "__main__":
    main()
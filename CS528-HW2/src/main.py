import argparse
import pickle
from pathlib import Path
from time import perf_counter

from google.cloud import storage

from src.closeness import calculate_closeness
from src.degree_stats import (
    calculate_degree_statistics,
    print_degree_statistics,
)
from src.graph import build_graph
from src.pagerank import calculate_pagerank
from google.cloud.storage.retry import DEFAULT_RETRY


BUCKET_NAME = "cs528-hw2-yf-2026"
PREFIX = "data/"
EXPECTED_FILE_COUNT = 12000
CACHE_PATH = Path("results/graph_cache.pkl")
STORAGE_RETRY = DEFAULT_RETRY.with_timeout(600.0)


def read_graph_from_bucket():
    client = storage.Client.create_anonymous_client()

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
                    f"Listed {len(blobs)} HTML files"
                )

    print(f"HTML files found: {len(blobs)}")

    if len(blobs) != EXPECTED_FILE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_FILE_COUNT} HTML files, "
            f"found {len(blobs)}"
        )

    return build_graph(blobs)


def save_graph_cache(outgoing, incoming):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CACHE_PATH.open("wb") as cache_file:
        pickle.dump((outgoing, incoming), cache_file)

    print(f"Graph cache saved to: {CACHE_PATH}")


def load_graph_cache():
    with CACHE_PATH.open("rb") as cache_file:
        return pickle.load(cache_file)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Analyze the CS528 web graph"
    )

    parser.add_argument(
        "--use-cache",
        action="store_true",
        help=(
            "Load the previously saved graph instead of "
            "reading files from Google Cloud Storage"
        ),
    )

    return parser.parse_args()


def main():
    args = parse_arguments()
    total_start = perf_counter()

    if args.use_cache:
        if not CACHE_PATH.exists():
            raise FileNotFoundError(
                f"Cache not found: {CACHE_PATH}. "
                "Run without --use-cache first."
            )

        graph_start = perf_counter()

        print(f"Loading graph cache: {CACHE_PATH}")
        outgoing, incoming = load_graph_cache()

        graph_time = perf_counter() - graph_start
        print(f"Cache loading time: {graph_time:.2f} seconds")

    else:
        graph_start = perf_counter()

        outgoing, incoming = read_graph_from_bucket()

        graph_time = perf_counter() - graph_start
        print(f"Graph construction time: {graph_time:.2f} seconds")

        save_graph_cache(outgoing, incoming)

    node_count = len(outgoing)
    edge_count = sum(
        len(targets)
        for targets in outgoing.values()
    )

    print(f"\nNodes: {node_count}")
    print(f"Links: {edge_count}")

    statistics_start = perf_counter()

    outgoing_results = calculate_degree_statistics(outgoing)
    incoming_results = calculate_degree_statistics(incoming)

    print_degree_statistics(
        "Outgoing-link statistics",
        outgoing_results,
    )

    print_degree_statistics(
        "Incoming-link statistics",
        incoming_results,
    )

    statistics_time = perf_counter() - statistics_start

    pagerank_start = perf_counter()

    ranks, iterations, final_change = calculate_pagerank(
        outgoing
    )

    top_five = sorted(
        ranks.items(),
        key=lambda item: (-item[1], item[0]),
    )[:5]

    pagerank_time = perf_counter() - pagerank_start

    closeness_start = perf_counter()

    best_closeness_node, best_closeness_score, _ = (
        calculate_closeness(
            outgoing,
            progress_interval=500,
        )
    )

    closeness_time = perf_counter() - closeness_start
    total_time = perf_counter() - total_start

    print(f"\nStatistics time: {statistics_time:.2f} seconds")

    print("\nPageRank results")
    print(f"Iterations: {iterations}")
    print(f"Final total change: {final_change:.10f}")
    print(
        "Sum of PageRank scores: "
        f"{sum(ranks.values()):.10f}"
    )
    print("Top 5 pages:")

    for position, (page, score) in enumerate(
        top_five,
        start=1,
    ):
        print(f"  {position}. {page}: {score:.10f}")

    print(f"PageRank time: {pagerank_time:.2f} seconds")

    print("\nCloseness centrality results")
    print(f"Best node: {best_closeness_node}")
    print(f"Score: {best_closeness_score:.10f}")
    print(f"Closeness time: {closeness_time:.2f} seconds")

    print(f"\nTotal time: {total_time:.2f} seconds")


if __name__ == "__main__":
    main()
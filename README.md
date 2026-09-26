# CS528 Homework 2: Web Graph Analysis

This project reads 12,000 generated HTML files from a public Google Cloud Storage bucket, constructs a directed web graph, and computes degree statistics, PageRank, and closeness centrality without using graph-processing libraries.

## Google Cloud Resources

- Project name: `CS-528-YF`
- Project ID: `dazzling-seat-508219-j3`
- Bucket: `cs528-hw2-yf-2026`
- Bucket location: `us-central1`
- Storage class: `Standard`
- Object prefix: `data/`
- Public access: `allUsers` has the `Storage Object Viewer` role

The dataset can be accessed without Google Cloud credentials.

Example public object:

```text
https://storage.googleapis.com/cs528-hw2-yf-2026/data/0.html
```

## Requirements

- Python 3.12 or later
- Internet access
- Approximately 100 MB of available memory
- No graph libraries are required or used

## Installation

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## Running the Program

Run the complete analysis directly against Google Cloud Storage:

```bash
python -u -m src.main
```

This command:

1. Lists the HTML objects under `data/`.
2. Reads all 12,000 files from the public bucket.
3. Parses the hyperlinks.
4. Constructs outgoing and incoming adjacency lists.
5. Calculates incoming-link and outgoing-link statistics.
6. Calculates PageRank and prints the top five pages.
7. Calculates the node with the highest closeness centrality.
8. Saves a local development cache in `results/graph_cache.pkl`.

The program is single-threaded.

### Development Cache

After completing one full bucket run, use the local cache for development:

```bash
python -u -m src.main --use-cache
```

The `--use-cache` option skips Cloud Storage downloads. It must not be used when collecting the official local, Cloud Shell, or VM timing results.

## Running the Tests

Run all independent correctness tests:

```bash
python -m pytest -v
```

The tests use small deterministic graphs and do not depend on the randomly generated 12,000-file dataset.

## Dataset Generation

Generate the original dataset with:

```bash
python generate-content.py -n 12000 -m 325
```

The supplied generator uses `random.seed(0)`, making the generated dataset reproducible.

Because of the exclusive upper bounds in `random.randrange()` and `range()`, passing `-m 325` produces between 0 and 323 hyperlinks per file.

## Algorithm Details

### Graph Representation

The program uses Python dictionaries containing adjacency lists:

- `outgoing[node]` contains the pages linked from the node.
- `incoming[node]` contains the pages that link to the node.

Repeated hyperlinks are preserved for degree statistics and PageRank. Closeness centrality treats repeated links as a single graph connection because repeated edges do not change shortest-path distances.

### Degree Statistics

The program calculates the following values for incoming and outgoing links:

- Average
- Median
- Minimum
- Maximum
- Quintiles at 0%, 20%, 40%, 60%, 80%, and 100%

Percentiles use linear interpolation at position:

```text
(n - 1) * percentile
```

### PageRank

PageRank starts every node at `1/N` and uses a damping factor of `0.85`:

```text
PR(A) = 0.15/N + 0.85 * sum(PR(T) / C(T))
```

PageRank from dangling nodes is distributed equally among all nodes. Iteration stops when the sum of the absolute PageRank changes is at most `0.005`.

### Closeness Centrality

Closeness uses directed shortest-path distances. For a node that can reach every other node:

```text
CC(v) = (N - 1) / sum(distance(v, u))
```

For disconnected graphs, the score is normalized by the fraction of reachable nodes. The implementation uses custom integer bitsets to accelerate exact single-threaded breadth-first search.

## Current Results

```text
Nodes: 12000
Links: 1946934
```

PageRank top five:

```text
1. 5207.html: 0.0001955251
2. 7443.html: 0.0001828610
3. 7400.html: 0.0001796367
4. 950.html:  0.0001744095
5. 369.html:  0.0001733209
```

Best closeness-centrality node:

```text
Node: 10376.html
Score: 0.5046473483
```

## Project Structure

```text
CS528-HW2/
├── generate-content.py
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── closeness.py
│   ├── degree_stats.py
│   ├── graph.py
│   ├── main.py
│   └── pagerank.py
├── tests/
│   ├── test_closeness.py
│   └── test_pagerank.py
└── results/
```
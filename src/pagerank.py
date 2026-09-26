def calculate_pagerank(
    outgoing,
    damping=0.85,
    tolerance=0.005,
    max_iterations=1000,
):
    node_count = len(outgoing)

    if node_count == 0:
        raise ValueError("Cannot calculate PageRank for an empty graph")

    ranks = {
        node: 1.0 / node_count
        for node in outgoing
    }

    for iteration in range(1, max_iterations + 1):
        dangling_mass = sum(
            ranks[node]
            for node, targets in outgoing.items()
            if len(targets) == 0
        )

        base_rank = (1.0 - damping) / node_count
        dangling_share = damping * dangling_mass / node_count

        new_ranks = {
            node: base_rank + dangling_share
            for node in outgoing
        }

        for source, targets in outgoing.items():
            if not targets:
                continue

            contribution = (
                damping * ranks[source] / len(targets)
            )

            for target in targets:
                new_ranks[target] += contribution

        total_change = sum(
            abs(new_ranks[node] - ranks[node])
            for node in outgoing
        )

        ranks = new_ranks

        if total_change <= tolerance:
            return ranks, iteration, total_change

    raise RuntimeError(
        f"PageRank did not converge within {max_iterations} iterations"
    )
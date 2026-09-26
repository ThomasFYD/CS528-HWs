def bit_indices(mask):
    while mask:
        lowest_bit = mask & -mask
        yield lowest_bit.bit_length() - 1
        mask ^= lowest_bit


def build_bit_masks(outgoing, nodes, node_to_index):
    node_count = len(nodes)

    outgoing_masks = [0] * node_count
    incoming_masks = [0] * node_count

    for source, targets in outgoing.items():
        source_index = node_to_index[source]
        source_bit = 1 << source_index

        unique_target_indices = {
            node_to_index[target]
            for target in targets
            if target in node_to_index
        }

        outgoing_mask = 0

        for target_index in unique_target_indices:
            outgoing_mask |= 1 << target_index
            incoming_masks[target_index] |= source_bit

        outgoing_masks[source_index] = outgoing_mask

    return outgoing_masks, incoming_masks


def next_frontier(
    frontier,
    remaining,
    outgoing_masks,
    incoming_masks,
):
    if frontier.bit_count() <= remaining.bit_count():
        reachable = 0

        for node_index in bit_indices(frontier):
            reachable |= outgoing_masks[node_index]

        return reachable & remaining

    reachable = 0

    for node_index in bit_indices(remaining):
        if incoming_masks[node_index] & frontier:
            reachable |= 1 << node_index

    return reachable


def calculate_closeness(outgoing, progress_interval=None):
    if not outgoing:
        raise ValueError(
            "Cannot calculate closeness for an empty graph"
        )

    nodes = sorted(outgoing)
    node_count = len(nodes)

    if node_count == 1:
        only_node = nodes[0]
        return only_node, 0.0, {only_node: 0.0}

    node_to_index = {
        node: index
        for index, node in enumerate(nodes)
    }

    outgoing_masks, incoming_masks = build_bit_masks(
        outgoing,
        nodes,
        node_to_index,
    )

    all_nodes_mask = (1 << node_count) - 1
    scores = {}

    best_node = None
    best_score = -1.0

    for source_index, source in enumerate(nodes):
        source_bit = 1 << source_index
        remaining = all_nodes_mask ^ source_bit
        frontier = source_bit

        distance = 0
        reachable_count = 0
        distance_sum = 0

        while frontier and remaining:
            distance += 1

            frontier = next_frontier(
                frontier,
                remaining,
                outgoing_masks,
                incoming_masks,
            )

            if not frontier:
                break

            level_count = frontier.bit_count()
            reachable_count += level_count
            distance_sum += distance * level_count

            remaining &= ~frontier

        if reachable_count == 0:
            score = 0.0
        else:
            reachable_fraction = (
                reachable_count / (node_count - 1)
            )

            score = (
                reachable_count / distance_sum
            ) * reachable_fraction

        scores[source] = score

        if (
            score > best_score
            or (
                score == best_score
                and (
                    best_node is None
                    or source < best_node
                )
            )
        ):
            best_node = source
            best_score = score

        completed = source_index + 1

        if (
            progress_interval
            and (
                completed % progress_interval == 0
                or completed == node_count
            )
        ):
            print(
                "Closeness processed "
                f"{completed}/{node_count} nodes"
            )

    return best_node, best_score, scores
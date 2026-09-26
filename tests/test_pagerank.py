import pytest

from src.pagerank import calculate_pagerank


def test_pagerank_known_graph():
    outgoing = {
        "A": ["B", "C"],
        "B": ["C"],
        "C": ["A"],
    }

    ranks, iterations, total_change = calculate_pagerank(
        outgoing,
        tolerance=1e-12,
    )

    assert ranks["A"] == pytest.approx(
        0.3877897117, abs=1e-9
    )
    assert ranks["B"] == pytest.approx(
        0.2148106275, abs=1e-9
    )
    assert ranks["C"] == pytest.approx(
        0.3973996608, abs=1e-9
    )

    assert sum(ranks.values()) == pytest.approx(1.0)
    assert total_change <= 1e-12
    assert iterations > 0


def test_pagerank_handles_dangling_node():
    outgoing = {
        "A": ["B"],
        "B": [],
    }

    ranks, _, _ = calculate_pagerank(
        outgoing,
        tolerance=1e-12,
    )

    assert sum(ranks.values()) == pytest.approx(1.0)
    assert ranks["B"] > ranks["A"]
    assert all(rank >= 0.0 for rank in ranks.values())
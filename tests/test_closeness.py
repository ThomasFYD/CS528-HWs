import pytest

from src.closeness import calculate_closeness


def test_closeness_finds_center_of_star():
    outgoing = {
        "A": ["B", "C", "D", "E"],
        "B": ["A"],
        "C": ["A"],
        "D": ["A"],
        "E": ["A"],
    }

    best_node, best_score, scores = calculate_closeness(
        outgoing
    )

    assert best_node == "A"
    assert best_score == pytest.approx(1.0)

    assert scores["B"] == pytest.approx(4.0 / 7.0)
    assert scores["C"] == pytest.approx(4.0 / 7.0)
    assert scores["D"] == pytest.approx(4.0 / 7.0)
    assert scores["E"] == pytest.approx(4.0 / 7.0)


def test_closeness_handles_disconnected_graph():
    outgoing = {
        "A": ["B"],
        "B": ["C"],
        "C": [],
        "D": [],
    }

    best_node, best_score, scores = calculate_closeness(
        outgoing
    )

    assert best_node == "A"
    assert best_score == pytest.approx(4.0 / 9.0)
    assert scores["B"] == pytest.approx(1.0 / 3.0)
    assert scores["C"] == pytest.approx(0.0)
    assert scores["D"] == pytest.approx(0.0)
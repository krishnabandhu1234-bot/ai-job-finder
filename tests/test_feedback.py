"""Tests for the section-16 feedback-learning heuristic."""

from __future__ import annotations

from app.ai.feedback import compute_title_affinity, learned_title_bonus, never_show_similar_titles


def test_rejected_title_lowers_affinity():
    affinity = compute_title_affinity([("poor", "Engineering Manager")])
    assert affinity["engineering"] < 0
    assert affinity["manager"] < 0


def test_accepted_title_raises_affinity():
    affinity = compute_title_affinity([("excellent", "Principal Simulation Architect")])
    assert affinity["principal"] > 0
    assert affinity["simulation"] > 0


def test_mixed_history_reflected_in_bonus():
    """Section 16's exact example: repeatedly reject Engineering Manager,
    repeatedly accept Principal Simulation Architect."""
    history = [
        ("poor", "Engineering Manager"),
        ("not_interested", "Engineering Manager"),
        ("excellent", "Principal Simulation Architect"),
        ("good", "Principal Simulation Architect"),
    ]
    affinity = compute_title_affinity(history)
    assert learned_title_bonus("Engineering Manager", affinity) < 0
    assert learned_title_bonus("Principal Simulation Architect", affinity) > 0


def test_no_feedback_history_gives_zero_bonus():
    assert learned_title_bonus("Any Job Title", {}) == 0.0


def test_bonus_is_capped():
    affinity = compute_title_affinity([("excellent", "Architect")] * 50)
    assert learned_title_bonus("Architect", affinity) <= 15.0


def test_unrelated_title_gets_no_bonus():
    affinity = compute_title_affinity([("excellent", "Principal Simulation Architect")])
    assert learned_title_bonus("Retail Store Clerk", affinity) == 0.0


def test_never_show_similar_tracks_tokens():
    tokens = never_show_similar_titles([("never_show_similar", "Sales Development Representative")])
    assert "sales" in tokens
    assert "representative" in tokens

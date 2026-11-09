# tests/test_recommender.py
"""
Unit tests for api/recommender.py — empty corpus and vector derivation.
"""
import pytest


def test_get_recommendations_empty_corpus(app):
    """With an empty Track table, get_recommendations returns ([], False)."""
    from api.recommender import get_recommendations

    with app.app_context():
        results, cache_hit = get_recommendations(
            seed_vector=[0.5, 0.5, 0.5, 0.5, 0.2, 0.1], n=5
        )
    assert results == []
    assert cache_hit is False


def test_vector_from_top_tracks_empty(app):
    """Empty top-tracks payload should return a 6-element default vector."""
    from api.recommender import vector_from_top_tracks

    with app.app_context():
        vec = vector_from_top_tracks({})
    assert len(vec) == 6
    assert all(isinstance(v, float) for v in vec)


def test_vector_from_top_tracks_with_items(app):
    """Payload with popularity values returns a 6-D float vector."""
    from api.recommender import vector_from_top_tracks

    payload = {
        "items": [
            {"id": "SEED_HH001", "popularity": 80},
            {"id": "SEED_HH002", "popularity": 60},
        ]
    }
    with app.app_context():
        vec = vector_from_top_tracks(payload)
    assert len(vec) == 6
    assert all(isinstance(v, float) for v in vec)

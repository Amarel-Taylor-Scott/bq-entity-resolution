"""Tests for geo-spatial comparison functions."""

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


def test_geo_within_km_registered():
    """geo_within_km is registered in the comparison registry."""
    assert "geo_within_km" in COMPARISON_FUNCTIONS


def test_geo_within_km_generates_st_distance():
    """geo_within_km generates ST_DISTANCE with km threshold."""
    result = COMPARISON_FUNCTIONS["geo_within_km"](
        "lat", "lat", max_km=5.0, left_lon="lon", right_lon="lon"
    )
    assert "ST_DISTANCE" in result
    assert "ST_GEOGPOINT" in result
    assert "5.0" in result
    assert "1000.0" in result  # meters to km conversion


def test_geo_within_km_null_checks():
    """geo_within_km includes null checks for all four columns."""
    result = COMPARISON_FUNCTIONS["geo_within_km"](
        "lat", "lat", left_lon="lon", right_lon="lon"
    )
    assert "l.lat IS NOT NULL" in result
    assert "r.lat IS NOT NULL" in result
    assert "l.lon IS NOT NULL" in result
    assert "r.lon IS NOT NULL" in result


def test_geo_distance_score_registered():
    """geo_distance_score is registered in the comparison registry."""
    assert "geo_distance_score" in COMPARISON_FUNCTIONS


def test_geo_distance_score_generates_proximity():
    """geo_distance_score generates a 0-1 proximity score."""
    result = COMPARISON_FUNCTIONS["geo_distance_score"](
        "lat", "lat", max_km=25.0, left_lon="lon", right_lon="lon"
    )
    assert "ST_DISTANCE" in result
    assert "GREATEST(0.0" in result
    assert "25.0" in result
    assert "ELSE 0.0 END" in result

"""Tests for geo-spatial feature functions."""

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


def test_geo_hash_registered():
    """geo_hash is registered in the feature registry."""
    assert "geo_hash" in FEATURE_FUNCTIONS


def test_geo_hash_uses_st_geohash():
    """geo_hash generates ST_GEOHASH(ST_GEOGPOINT(...)) SQL."""
    result = FEATURE_FUNCTIONS["geo_hash"](["lat_col", "lon_col"])
    assert "ST_GEOHASH" in result
    assert "ST_GEOGPOINT" in result
    assert "lat_col" in result
    assert "lon_col" in result


def test_geo_hash_custom_precision():
    """geo_hash respects the precision parameter."""
    result = FEATURE_FUNCTIONS["geo_hash"](["lat", "lon"], precision=4)
    assert "4" in result


def test_lat_lon_bucket_registered():
    """lat_lon_bucket is registered in the feature registry."""
    assert "lat_lon_bucket" in FEATURE_FUNCTIONS


def test_lat_lon_bucket_generates_grid_key():
    """lat_lon_bucket generates a grid cell concatenation key."""
    result = FEATURE_FUNCTIONS["lat_lon_bucket"](["lat", "lon"], grid_size_km=10)
    assert "FLOOR" in result
    assert "CONCAT" in result
    assert "lat" in result
    assert "lon" in result


def test_haversine_distance_uses_st_distance():
    """haversine_distance generates ST_DISTANCE SQL."""
    result = FEATURE_FUNCTIONS["haversine_distance"](
        ["lat1", "lon1", "lat2", "lon2"]
    )
    assert "ST_DISTANCE" in result
    assert "ST_GEOGPOINT" in result
    assert "1000.0" in result  # converts meters to km
    assert "lat1" in result
    assert "lon2" in result

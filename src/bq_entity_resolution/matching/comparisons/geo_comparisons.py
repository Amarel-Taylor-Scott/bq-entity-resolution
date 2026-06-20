"""
Geo-spatial comparison functions.

Distance and proximity comparisons for geographic coordinates.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import register
from bq_entity_resolution.sql.utils import validate_identifier

# ---------------------------------------------------------------------------
# Geo-spatial comparisons
# ---------------------------------------------------------------------------
# PERF: ST_DISTANCE computes geodesic distance (great-circle) per pair.
# This involves trigonometric functions — expensive at scale. Always use
# geo_hash or lat_lon_bucket blocking to pre-filter candidates to nearby
# records before computing exact distance. The geo blocking keys can be
# wrapped in FARM_FINGERPRINT for INT64 equi-join blocking.


@register("geo_within_km")
def geo_within_km(
    left: str,
    right: str,
    max_km: float = 10.0,
    left_lon: str = "",
    right_lon: str = "",
    **_: Any,
) -> str:
    """Boolean: two lat/lon points are within max_km kilometers.

    left/right are latitude columns; left_lon/right_lon are longitude columns.
    Uses BigQuery ST_DISTANCE for geodesic accuracy.
    """
    if left_lon:
        validate_identifier(left_lon, context="geo_within_km left_lon column")
    if right_lon:
        validate_identifier(right_lon, context="geo_within_km right_lon column")
    return (
        f"(ST_DISTANCE("
        f"ST_GEOGPOINT(l.{left_lon}, l.{left}), "
        f"ST_GEOGPOINT(r.{right_lon}, r.{right})"
        f") / 1000.0 <= {max_km} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND l.{left_lon} IS NOT NULL AND r.{right_lon} IS NOT NULL)"
    )


@register("geo_distance_score")
def geo_distance_score(
    left: str,
    right: str,
    max_km: float = 50.0,
    left_lon: str = "",
    right_lon: str = "",
    **_: Any,
) -> str:
    """Proximity score 0.0-1.0 based on distance between two lat/lon points.

    Score = 1 - (distance_km / max_km), clamped to [0, 1].
    left/right are latitude columns; left_lon/right_lon are longitude columns.
    """
    if left_lon:
        validate_identifier(left_lon, context="geo_distance_score left_lon column")
    if right_lon:
        validate_identifier(right_lon, context="geo_distance_score right_lon column")
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND l.{left_lon} IS NOT NULL AND r.{right_lon} IS NOT NULL "
        f"THEN GREATEST(0.0, 1.0 - ST_DISTANCE("
        f"ST_GEOGPOINT(l.{left_lon}, l.{left}), "
        f"ST_GEOGPOINT(r.{right_lon}, r.{right})"
        f") / 1000.0 / {max_km}) "
        f"ELSE 0.0 END"
    )

"""Geo-spatial feature functions."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("geo_hash")
def geo_hash(inputs: list[str], precision: int = 6, **_: Any) -> str:
    """Geohash from latitude and longitude columns.

    Uses BigQuery ST_GEOHASH(ST_GEOGPOINT(lon, lat), precision).
    Inputs: [lat, lon].
    """
    lat, lon = inputs[0], inputs[1]
    return (
        f"CASE WHEN {lat} IS NOT NULL AND {lon} IS NOT NULL "
        f"THEN ST_GEOHASH(ST_GEOGPOINT({lon}, {lat}), {precision}) "
        f"ELSE NULL END"
    )


@register("lat_lon_bucket")
def lat_lon_bucket(inputs: list[str], grid_size_km: int = 10, **_: Any) -> str:
    """Grid cell blocking key from lat/lon coordinates.

    Divides the globe into grid cells of approximately grid_size_km.
    1 degree latitude ~ 111 km. Returns a string key like '40_-74'.
    Inputs: [lat, lon].
    """
    lat, lon = inputs[0], inputs[1]
    # Approximate degrees per grid cell
    deg = round(grid_size_km / 111.0, 4)
    return (
        f"CASE WHEN {lat} IS NOT NULL AND {lon} IS NOT NULL "
        f"THEN CONCAT(CAST(CAST(FLOOR({lat} / {deg}) AS INT64) AS STRING), "
        f"'_', CAST(CAST(FLOOR({lon} / {deg}) AS INT64) AS STRING)) "
        f"ELSE NULL END"
    )


@register("haversine_distance")
def haversine_distance(inputs: list[str], **_: Any) -> str:
    """Distance in kilometers between two lat/lon points.

    Uses BigQuery ST_DISTANCE for accurate geodesic distance.
    Inputs: [lat1, lon1, lat2, lon2].
    """
    lat1, lon1, lat2, lon2 = inputs[0], inputs[1], inputs[2], inputs[3]
    return (
        f"CASE WHEN {lat1} IS NOT NULL AND {lon1} IS NOT NULL "
        f"AND {lat2} IS NOT NULL AND {lon2} IS NOT NULL "
        f"THEN ST_DISTANCE(ST_GEOGPOINT({lon1}, {lat1}), "
        f"ST_GEOGPOINT({lon2}, {lat2})) / 1000.0 "
        f"ELSE NULL END"
    )

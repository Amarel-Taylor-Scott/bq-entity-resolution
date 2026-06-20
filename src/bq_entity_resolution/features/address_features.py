"""Address feature functions."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("address_standardize")
def address_standardize(inputs: list[str], **_: Any) -> str:
    """Standardize address: uppercase, abbreviate common street types, collapse whitespace.

    Covers 30+ common street type abbreviations per USPS Publication 28.

    OUTPUT TYPE: STRING (variable length)
    PERF WARNING: This is the most compute-expensive feature function.
    It chains 40+ nested REGEXP_REPLACE calls which BQ evaluates per row.
    ALWAYS pre-compute as a stored feature column, NEVER use inline in
    comparison SQL. For address blocking, prefer:
      FARM_FINGERPRINT(address_standardize(col))  — INT64, fast equi-join
    or extract_street_number (short 1-5 char STRING, very cheap).
    """
    col = inputs[0]
    # Build nested REGEXP_REPLACE chain for street type standardization
    replacements = [
        ("STREET", "ST"), ("AVENUE", "AVE"), ("BOULEVARD", "BLVD"),
        ("DRIVE", "DR"), ("LANE", "LN"), ("ROAD", "RD"),
        ("HIGHWAY", "HWY"), ("PARKWAY", "PKWY"), ("PLACE", "PL"),
        ("CIRCLE", "CIR"), ("COURT", "CT"), ("TERRACE", "TER"),
        ("TRAIL", "TRL"), ("WAY", "WAY"), ("SQUARE", "SQ"),
        ("EXPRESSWAY", "EXPY"), ("FREEWAY", "FWY"), ("TURNPIKE", "TPKE"),
        ("PIKE", "PIKE"), ("ALLEY", "ALY"), ("CROSSING", "XING"),
        ("CRESCENT", "CRES"), ("HEIGHTS", "HTS"), ("JUNCTION", "JCT"),
        ("LOOP", "LOOP"), ("RIDGE", "RDG"), ("VALLEY", "VLY"),
        ("POINT", "PT"), ("GROVE", "GRV"), ("GARDENS", "GDNS"),
        # Common direction abbreviations
        ("NORTH", "N"), ("SOUTH", "S"), ("EAST", "E"), ("WEST", "W"),
        ("NORTHEAST", "NE"), ("NORTHWEST", "NW"),
        ("SOUTHEAST", "SE"), ("SOUTHWEST", "SW"),
        # Unit designators
        ("APARTMENT", "APT"), ("SUITE", "STE"), ("BUILDING", "BLDG"),
        ("FLOOR", "FL"), ("DEPARTMENT", "DEPT"),
    ]
    # Start with UPPER
    expr = f"UPPER({col})"
    for full, abbr in replacements:
        expr = f"REGEXP_REPLACE({expr}, r'\\\\b{full}\\\\b', '{abbr}')"
    # Collapse whitespace and trim
    return f"TRIM(REGEXP_REPLACE({expr}, r'\\\\s+', ' '))"


@register("extract_street_number")
def extract_street_number(inputs: list[str], **_: Any) -> str:
    """Extract leading street number from address."""
    col = inputs[0]
    return f"REGEXP_EXTRACT({col}, r'^(\\\\d+)')"


@register("extract_street_name")
def extract_street_name(inputs: list[str], **_: Any) -> str:
    """Extract street name (after number, before type suffix)."""
    col = inputs[0]
    return f"TRIM(REGEXP_EXTRACT(UPPER({col}), r'^\\\\d+\\\\s+(.+?)\\\\s*$'))"


@register("extract_unit_number")
def extract_unit_number(inputs: list[str], **_: Any) -> str:
    """Extract apartment/suite/unit number."""
    col = inputs[0]
    return (
        f"REGEXP_EXTRACT(UPPER({col}), "
        f"r'(?:APT|SUITE|STE|UNIT|#|NO)\\\\.?\\\\s*(\\\\w+)')"
    )

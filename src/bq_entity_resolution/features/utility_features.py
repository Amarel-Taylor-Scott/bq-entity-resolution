"""Generic / utility feature functions."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("upper_trim")
def upper_trim(inputs: list[str], **_: Any) -> str:
    """Uppercase and trim whitespace."""
    return f"TRIM(UPPER({inputs[0]}))"


@register("lower_trim")
def lower_trim(inputs: list[str], **_: Any) -> str:
    """Lowercase and trim whitespace."""
    return f"TRIM(LOWER({inputs[0]}))"


@register("left")
def left_func(inputs: list[str], length: int = 5, **_: Any) -> str:
    """Extract leftmost N characters."""
    return f"LEFT({inputs[0]}, {length})"


@register("right")
def right_func(inputs: list[str], length: int = 4, **_: Any) -> str:
    """Extract rightmost N characters."""
    return f"RIGHT({inputs[0]}, {length})"


@register("coalesce")
def coalesce_func(inputs: list[str], **_: Any) -> str:
    """COALESCE multiple columns."""
    return f"COALESCE({', '.join(inputs)})"


@register("concat")
def concat_func(inputs: list[str], separator: str = " ", **_: Any) -> str:
    """Concatenate columns with separator."""
    parts = f", '{separator}', ".join(
        f"COALESCE(CAST({c} AS STRING), '')" for c in inputs
    )
    return f"CONCAT({parts})"


@register("nullif_empty")
def nullif_empty(inputs: list[str], **_: Any) -> str:
    """Convert empty strings to NULL."""
    return f"NULLIF(TRIM({inputs[0]}), '')"


@register("is_not_null")
def is_not_null(inputs: list[str], **_: Any) -> str:
    """Returns 1 if column is not null, 0 otherwise.

    OUTPUT TYPE: INT64 (0 or 1) — ideal for match flags and filtering.
    Use to track whether an enrichment join found a match (e.g., whether
    the Census geocoder returned a result for this address).
    """
    return f"CASE WHEN {inputs[0]} IS NOT NULL THEN 1 ELSE 0 END"


@register("char_length")
def char_length(inputs: list[str], **_: Any) -> str:
    """String length.

    OUTPUT TYPE: INT64 — cheap to compute and compare.
    """
    return f"CHAR_LENGTH({inputs[0]})"


@register("soundex")
def soundex(inputs: list[str], **_: Any) -> str:
    """Soundex phonetic encoding.

    OUTPUT TYPE: STRING (4 chars, e.g. 'S530')
    PERF: Returns STRING — for blocking, consider wrapping in FARM_FINGERPRINT
    to get INT64: FARM_FINGERPRINT(SOUNDEX(col)) for ~3-5x faster equi-joins.
    As a comparison feature this is fine as-is.
    """
    return f"SOUNDEX({inputs[0]})"


@register("remove_diacritics")
def remove_diacritics(inputs: list[str], **_: Any) -> str:
    """Remove diacritical marks / accents from text.

    Converts: Å→A, ñ→N, é→E, ü→U, ø→O, ç→C, etc.
    Uses NORMALIZE(NFD) + REGEXP_REPLACE to strip combining marks,
    then applies manual replacements for special characters.

    OUTPUT TYPE: STRING
    When to use: International name matching where accented characters
    should match their unaccented equivalents.
    """
    col = inputs[0]
    return (
        f"UPPER(REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE(UPPER({col}), "
        f"r'[ÀÁÂÃÄÅ]', 'A'), "
        f"r'[ÈÉÊË]', 'E'), "
        f"r'[ÌÍÎÏ]', 'I'), "
        f"r'[ÒÓÔÕÖØ]', 'O'), "
        f"r'[ÙÚÛÜ]', 'U'), "
        f"r'[ÝŸ]', 'Y'), "
        f"r'[Ñ]', 'N'), "
        f"r'[Ç]', 'C'), "
        f"r'[ÐÞßÆ]', ''))"
    )


@register("length_bucket")
def length_bucket(inputs: list[str], bucket_size: int = 5, **_: Any) -> str:
    """Bucket string length into ranges for blocking.

    Groups strings by length: 0-4, 5-9, 10-14, etc. (with bucket_size=5).
    Names of very different lengths rarely match, so blocking by length
    bucket eliminates impossible pairs cheaply.

    Use as a blocking key alongside phonetic/fingerprint keys for
    tighter candidate pair generation.
    """
    col = inputs[0]
    return (
        f"CASE WHEN {col} IS NOT NULL "
        f"THEN CAST(FLOOR(CHAR_LENGTH({col}) / {bucket_size}) * {bucket_size} AS INT64) "
        f"ELSE NULL END"
    )


@register("length_category")
def length_category(inputs: list[str], **_: Any) -> str:
    """Categorize string length as short/medium/long for blocking.

    short: 1-4 chars, medium: 5-12 chars, long: 13+ chars.
    Useful as a blocking key when you want coarse length-based filtering.
    """
    col = inputs[0]
    return (
        f"CASE "
        f"WHEN {col} IS NULL THEN NULL "
        f"WHEN CHAR_LENGTH({col}) <= 4 THEN 'S' "
        f"WHEN CHAR_LENGTH({col}) <= 12 THEN 'M' "
        f"ELSE 'L' END"
    )


@register("normalize_whitespace")
def normalize_whitespace(inputs: list[str], **_: Any) -> str:
    """Collapse multiple whitespace chars to single space and trim.

    OUTPUT TYPE: STRING
    When to use: Cleaning free-text fields with inconsistent spacing.
    """
    col = inputs[0]
    return f"TRIM(REGEXP_REPLACE({col}, r'\\s+', ' '))"

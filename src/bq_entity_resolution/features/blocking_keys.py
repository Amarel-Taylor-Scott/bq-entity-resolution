"""Blocking key feature functions (INT64 output, optimal for equi-joins)."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("farm_fingerprint")
def farm_fingerprint(inputs: list[str], **_: Any) -> str:
    """FARM_FINGERPRINT of a single column.

    OUTPUT TYPE: INT64 — the fastest possible blocking key type.
    Use for any column where exact-match blocking is desired.
    Example: FARM_FINGERPRINT(policy_number) enables INT64 equi-join
    instead of STRING comparison on variable-length policy numbers.
    """
    return f"FARM_FINGERPRINT({inputs[0]})"


@register("farm_fingerprint_concat")
def farm_fingerprint_concat(inputs: list[str], **_: Any) -> str:
    """FARM_FINGERPRINT of concatenated columns.

    OUTPUT TYPE: INT64 — composite blocking key as a single INT64.
    PERF: Combines multiple columns into one INT64 blocking key,
    enabling a single equi-join condition instead of multiple ANDs.
    Example: fp(CONCAT(last_name, '||', dob)) is faster than
    l.last_name = r.last_name AND l.dob = r.dob because BQ
    evaluates one INT64 comparison instead of two STRING comparisons.
    """
    parts = ", '||', ".join(
        f"COALESCE(CAST({c} AS STRING), '')" for c in inputs
    )
    return f"FARM_FINGERPRINT(CONCAT({parts}))"


@register("identity")
def identity_func(inputs: list[str], **_: Any) -> str:
    """Pass through column unchanged.

    OUTPUT TYPE: same as input column type.
    PERF: If the input column is already INT64 or DATE, this is efficient.
    If it's STRING, consider farm_fingerprint for blocking use cases.
    """
    return inputs[0]


@register("sorted_name_tokens")
def sorted_name_tokens(inputs: list[str], **_: Any) -> str:
    """Sort words in a name alphabetically to handle transpositions.

    'Smith John' and 'John Smith' both become 'JOHN SMITH'.
    """
    col = inputs[0]
    return (
        f"(SELECT STRING_AGG(word, ' ' ORDER BY word) "
        f"FROM UNNEST(SPLIT(TRIM(UPPER({col})), ' ')) AS word "
        f"WHERE word != '')"
    )


@register("sorted_name_fingerprint")
def sorted_name_fingerprint(inputs: list[str], **_: Any) -> str:
    """FARM_FINGERPRINT of sorted name tokens — catches transpositions.

    OUTPUT TYPE: INT64 — ideal blocking key for name transpositions.
    PERF: 'Smith John' and 'John Smith' both sort to 'JOHN SMITH',
    then FARM_FINGERPRINT produces the same INT64. This enables
    transposition-resistant blocking with fast INT64 equi-joins.
    """
    sorted_expr = sorted_name_tokens(inputs)
    return f"FARM_FINGERPRINT({sorted_expr})"


@register("name_fingerprint")
def name_fingerprint(inputs: list[str], **_: Any) -> str:
    """FARM_FINGERPRINT of alpha-only characters (removes spaces, punctuation).

    OUTPUT TYPE: INT64 — ideal blocking key.
    PERF: This is the recommended name blocking function. Strips all
    non-alpha characters then hashes to INT64. Equi-joins on INT64 are
    ~3-5x faster than on the equivalent cleaned STRING. Catches minor
    punctuation/whitespace variations that would cause STRING mismatch.
    """
    col = inputs[0]
    return f"FARM_FINGERPRINT(REGEXP_REPLACE(UPPER({col}), r'[^A-Z]', ''))"

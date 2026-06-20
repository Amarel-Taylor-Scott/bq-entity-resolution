"""
Null-aware and hard-negative comparison functions.

Utility comparisons for null handling and pair disqualification.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import register

# ---------------------------------------------------------------------------
# Hard negative helpers
# ---------------------------------------------------------------------------


@register("different")
def different(left: str, right: str, **_: Any) -> str:
    """Returns TRUE when values differ (both non-null). For hard negatives."""
    return (
        f"(l.{left} != r.{right} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("null_either")
def null_either(left: str, right: str, **_: Any) -> str:
    """Returns TRUE when either value is null."""
    return f"(l.{left} IS NULL OR r.{right} IS NULL)"


@register("length_mismatch")
def length_mismatch(
    left: str, right: str, max_diff: int = 5, **_: Any
) -> str:
    """Returns TRUE when string lengths differ by more than threshold."""
    return (
        f"(ABS(CHAR_LENGTH(l.{left}) - CHAR_LENGTH(r.{right})) > {max_diff} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )

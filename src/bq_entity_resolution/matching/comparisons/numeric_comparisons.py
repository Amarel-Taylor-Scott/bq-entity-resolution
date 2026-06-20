"""
Numeric comparison functions.

Comparisons for numeric/continuous values (absolute difference, tolerance,
percentage difference, ratio comparison).
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import register

# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------
# PERF: These are the cheapest comparisons after exact-match on INT64.
# Numeric columns are stored as fixed-width INT64/FLOAT64. ABS(a - b)
# is a single arithmetic operation — no string allocation or byte scanning.


@register("numeric_within")
def numeric_within(left: str, right: str, tolerance: float = 0, **_: Any) -> str:
    """Numeric values within absolute tolerance.

    COST: 1 -- arithmetic on fixed-width numeric types. Very fast.

    When to use: Dollar amounts, ages, counts where absolute difference matters.
    Example: numeric_within("premium", "premium", tolerance=50) — premiums within $50.
    """
    return (
        f"(ABS(CAST(l.{left} AS FLOAT64) - CAST(r.{right} AS FLOAT64)) <= {tolerance} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("numeric_ratio")
def numeric_ratio(left: str, right: str, min_ratio: float = 0.9, **_: Any) -> str:
    """Numeric values within ratio tolerance (smaller/larger >= min_ratio).

    COST: 2 -- two divisions + comparison. Fast on FLOAT64.

    When to use: Financial amounts where proportional closeness matters.
    Example: numeric_ratio("claim_amount", "claim_amount", min_ratio=0.95)
    — amounts within 5% of each other regardless of magnitude.
    """
    return (
        f"(SAFE_DIVIDE("
        f"LEAST(ABS(CAST(l.{left} AS FLOAT64)), ABS(CAST(r.{right} AS FLOAT64))),"
        f"GREATEST(ABS(CAST(l.{left} AS FLOAT64)), ABS(CAST(r.{right} AS FLOAT64)))"
        f") >= {min_ratio} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND CAST(l.{left} AS FLOAT64) != 0 AND CAST(r.{right} AS FLOAT64) != 0)"
    )


@register("numeric_ratio_score")
def numeric_ratio_score(left: str, right: str, **_: Any) -> str:
    """Numeric ratio as continuous score (0.0 to 1.0).

    Returns smaller/larger, or 0.0 if either is null/zero.

    When to use: Probabilistic scoring on financial fields where proportional
    similarity should contribute to the match score continuously.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND CAST(l.{left} AS FLOAT64) != 0 AND CAST(r.{right} AS FLOAT64) != 0 "
        f"THEN SAFE_DIVIDE("
        f"LEAST(ABS(CAST(l.{left} AS FLOAT64)), ABS(CAST(r.{right} AS FLOAT64))),"
        f"GREATEST(ABS(CAST(l.{left} AS FLOAT64)), ABS(CAST(r.{right} AS FLOAT64))))"
        f" ELSE 0.0 END"
    )


@register("numeric_percent_diff")
def numeric_percent_diff(
    left: str, right: str, tolerance: float = 5.0, **_: Any
) -> str:
    """Numeric values within percentage tolerance.

    COST: 2 -- arithmetic on FLOAT64. Fast.

    When to use: Financial amounts, premiums, claim values where you want
    percentage-based tolerance (e.g., within 5% of each other).
    Example: numeric_percent_diff("premium", "premium", tolerance=10.0)
    """
    pct = tolerance / 100.0
    return (
        f"(SAFE_DIVIDE("
        f"ABS(CAST(l.{left} AS FLOAT64) - CAST(r.{right} AS FLOAT64)),"
        f"GREATEST(ABS(CAST(l.{left} AS FLOAT64)), ABS(CAST(r.{right} AS FLOAT64)))"
        f") <= {pct} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND (CAST(l.{left} AS FLOAT64) != 0 OR CAST(r.{right} AS FLOAT64) != 0))"
    )

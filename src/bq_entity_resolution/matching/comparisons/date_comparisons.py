"""
Date comparison functions.

Comparisons for date and temporal values: point dates, date ranges,
age differences, and temporal overlap detection.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import register
from bq_entity_resolution.sql.utils import validate_identifier

# ---------------------------------------------------------------------------
# Date comparisons
# ---------------------------------------------------------------------------
# PERF: Date columns are stored as INT32 internally in BigQuery.
# DATE_DIFF is a single arithmetic operation — very fast.


@register("date_within_days")
def date_within_days(left: str, right: str, days: int = 0, **_: Any) -> str:
    """Date values within N days.

    COST: 1 -- DATE_DIFF on INT32 internals. Very fast.

    When to use: DOB matching with tolerance, transaction date proximity.
    Example: date_within_days("dob", "dob", days=30) — DOBs within 1 month.
    """
    return (
        f"(ABS(DATE_DIFF(l.{left}, r.{right}, DAY)) <= {days} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("date_within_months")
def date_within_months(left: str, right: str, months: int = 0, **_: Any) -> str:
    """Date values within N months.

    COST: 1 -- DATE_DIFF on INT32. Very fast.

    When to use: Approximate date matching where month-level tolerance
    is appropriate (e.g., policy inception dates, hire dates).
    """
    return (
        f"(ABS(DATE_DIFF(l.{left}, r.{right}, MONTH)) <= {months} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("date_within_years")
def date_within_years(left: str, right: str, years: int = 0, **_: Any) -> str:
    """Date values within N years.

    COST: 1 -- DATE_DIFF on INT32. Very fast.

    When to use: Age-based matching, decade-level grouping.
    """
    return (
        f"(ABS(DATE_DIFF(l.{left}, r.{right}, YEAR)) <= {years} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("age_difference")
def age_difference(left: str, right: str, max_diff: int = 2, **_: Any) -> str:
    """Ages derived from DOB columns differ by at most N years.

    COST: 2 -- two DATE_DIFF calls + subtraction.

    When to use: Matching people who should be approximately the same age.
    More robust than exact DOB matching when DOB may have entry errors.
    Example: age_difference("dob", "dob", max_diff=3) — ages within 3 years.
    """
    return (
        f"(ABS(DATE_DIFF(CURRENT_DATE(), l.{left}, YEAR) "
        f"- DATE_DIFF(CURRENT_DATE(), r.{right}, YEAR)) <= {max_diff} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("date_overlap")
def date_overlap(
    left: str,
    right: str,
    left_end: str = "",
    right_end: str = "",
    **_: Any,
) -> str:
    """Temporal range overlap: two date ranges intersect.

    Checks: left_start <= right_end AND left_end >= right_start

    COST: 2 -- four date comparisons (all INT32). Fast.

    When to use: Policy period overlap, employment date overlap, coverage
    date intersection. Critical for insurance entity resolution where the
    same entity may have overlapping or adjacent policy periods.

    Params:
        left/right: Start date columns.
        left_end: End date column for left side (defaults to left + '_end').
        right_end: End date column for right side (defaults to right + '_end').

    Example: date_overlap("policy_start", "policy_start",
                          left_end="policy_end", right_end="policy_end")
    """
    if left_end:
        validate_identifier(left_end, context="date_overlap left_end column")
    if right_end:
        validate_identifier(right_end, context="date_overlap right_end column")
    l_end = left_end or f"{left}_end"
    r_end = right_end or f"{right}_end"
    return (
        f"(l.{left} <= r.{r_end} AND l.{l_end} >= r.{right} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND l.{l_end} IS NOT NULL AND r.{r_end} IS NOT NULL)"
    )


@register("date_overlap_score")
def date_overlap_score(
    left: str,
    right: str,
    left_end: str = "",
    right_end: str = "",
    **_: Any,
) -> str:
    """Temporal overlap ratio as a score (0.0 to 1.0).

    Returns overlap_days / min_period_days. Score of 1.0 means one period
    is entirely contained within the other.

    COST: 3 -- date arithmetic + GREATEST/LEAST + division.

    When to use: Probabilistic scoring where degree of temporal overlap
    should contribute to match confidence (e.g., overlapping coverage periods).
    """
    if left_end:
        validate_identifier(left_end, context="date_overlap_score left_end column")
    if right_end:
        validate_identifier(right_end, context="date_overlap_score right_end column")
    l_end = left_end or f"{left}_end"
    r_end = right_end or f"{right}_end"
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND l.{l_end} IS NOT NULL AND r.{r_end} IS NOT NULL "
        f"AND l.{left} <= r.{r_end} AND l.{l_end} >= r.{right} "
        f"THEN SAFE_DIVIDE("
        f"DATE_DIFF(LEAST(l.{l_end}, r.{r_end}), GREATEST(l.{left}, r.{right}), DAY) + 1,"
        f"LEAST(DATE_DIFF(l.{l_end}, l.{left}, DAY) + 1, "
        f"DATE_DIFF(r.{r_end}, r.{right}, DAY) + 1)) "
        f"ELSE 0.0 END"
    )

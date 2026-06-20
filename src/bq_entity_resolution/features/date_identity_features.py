"""Date and identity (DOB/SSN) feature functions."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("year_of_date")
def year_of_date(inputs: list[str], **_: Any) -> str:
    """Extract year from a date/timestamp column."""
    return f"EXTRACT(YEAR FROM {inputs[0]})"


@register("date_to_string")
def date_to_string(inputs: list[str], fmt: str = "%Y%m%d", **_: Any) -> str:
    """Format a date as a string for blocking/comparison."""
    return f"FORMAT_DATE('{fmt}', {inputs[0]})"


@register("dob_year")
def dob_year(inputs: list[str], **_: Any) -> str:
    """Extract year of birth from a DATE column for blocking."""
    col = inputs[0]
    return f"EXTRACT(YEAR FROM {col})"


@register("age_from_dob")
def age_from_dob(inputs: list[str], **_: Any) -> str:
    """Compute current age in years from a DATE column."""
    col = inputs[0]
    return f"DATE_DIFF(CURRENT_DATE(), {col}, YEAR)"


@register("dob_mmdd")
def dob_mmdd(inputs: list[str], **_: Any) -> str:
    """Extract month+day from a DATE column as MMDD string for blocking."""
    col = inputs[0]
    return f"FORMAT_DATE('%m%d', {col})"


@register("ssn_last_four")
def ssn_last_four(inputs: list[str], **_: Any) -> str:
    """Extract last 4 digits of an SSN (strips dashes/spaces first)."""
    col = inputs[0]
    return f"RIGHT(REGEXP_REPLACE({col}, r'[^0-9]', ''), 4)"


@register("ssn_clean")
def ssn_clean(inputs: list[str], **_: Any) -> str:
    """Strip non-digit characters from an SSN (e.g. '123-45-6789' -> '123456789')."""
    col = inputs[0]
    return f"REGEXP_REPLACE({col}, r'[^0-9]', '')"

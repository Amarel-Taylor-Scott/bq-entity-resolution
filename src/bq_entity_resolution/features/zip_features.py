"""Zip / postal code feature functions."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("zip5")
def zip5(inputs: list[str], **_: Any) -> str:
    """Extract first 5 digits of a zip/postal code."""
    col = inputs[0]
    return f"LEFT(REGEXP_REPLACE({col}, r'[^0-9]', ''), 5)"


@register("zip3")
def zip3(inputs: list[str], **_: Any) -> str:
    """Extract first 3 digits of a zip code (SCF area)."""
    col = inputs[0]
    return f"LEFT(REGEXP_REPLACE({col}, r'[^0-9]', ''), 3)"

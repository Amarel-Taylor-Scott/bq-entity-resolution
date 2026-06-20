"""
Hard negative rule SQL expression builders.

Hard negatives disqualify or penalize candidate pairs that should never match
despite passing blocking filters (e.g., different first names for individuals,
different EINs for companies).
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.config.schema import HardNegativeDef
from bq_entity_resolution.exceptions import SQLGenerationError
from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS, _validated_call


def build_hard_negative_expr(hn: HardNegativeDef) -> dict[str, Any]:
    """
    Build a hard negative SQL expression dict from config.

    Returns:
        {
            "sql_condition": "...",  # SQL boolean expression
            "action": "disqualify" | "penalize",
            "penalty": float (only relevant for "penalize")
        }
    """
    if hn.sql:
        # Raw SQL override
        return {
            "sql_condition": hn.sql,
            "action": hn.action,
            "penalty": hn.penalty,
        }

    right = hn.right or hn.left
    func = COMPARISON_FUNCTIONS.get(hn.method)
    if func is None:
        raise SQLGenerationError(
            f"Unknown hard negative method '{hn.method}'. "
            f"Available: {sorted(COMPARISON_FUNCTIONS.keys())}"
        )

    sql_condition = _validated_call(func, hn.left, right)

    return {
        "sql_condition": sql_condition,
        "action": hn.action,
        "penalty": hn.penalty,
    }

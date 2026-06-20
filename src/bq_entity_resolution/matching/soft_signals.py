"""
Soft signal SQL expression builders.

Soft signals adjust the match score up or down based on supporting evidence
(e.g., matching phone area code, same email domain).
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.config.schema import SoftSignalDef
from bq_entity_resolution.exceptions import SQLGenerationError
from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS, _validated_call


def build_soft_signal_expr(ss: SoftSignalDef) -> dict[str, Any]:
    """
    Build a soft signal SQL expression dict from config.

    Returns:
        {
            "sql_condition": "...",  # SQL boolean expression
            "bonus": float (positive = boost, negative = penalty)
        }
    """
    if ss.sql:
        return {
            "sql_condition": ss.sql,
            "bonus": ss.bonus,
        }

    right = ss.right or ss.left
    func = COMPARISON_FUNCTIONS.get(ss.method)
    if func is None:
        raise SQLGenerationError(
            f"Unknown soft signal method '{ss.method}'. "
            f"Available: {sorted(COMPARISON_FUNCTIONS.keys())}"
        )

    sql_condition = _validated_call(func, ss.left, right)

    return {
        "sql_condition": sql_condition,
        "bonus": ss.bonus,
    }

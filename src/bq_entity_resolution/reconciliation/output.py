"""
Gold output table helpers.

Canonical record selection strategies and output formatting.
"""

from __future__ import annotations

from bq_entity_resolution.sql.utils import sql_escape


def completeness_score_expr(columns: list[str], alias: str = "") -> str:
    """
    Generate a SQL expression that scores record completeness.

    Score = count of non-null columns. Higher = more complete.
    """
    prefix = f"{alias}." if alias else ""
    parts = [
        f"CASE WHEN {prefix}{col} IS NOT NULL THEN 1 ELSE 0 END"
        for col in columns
    ]
    return " + ".join(parts) if parts else "0"


def canonical_selection_order(
    method: str,
    scoring_columns: list[str] | None = None,
    source_priority: list[str] | None = None,
) -> str:
    """
    Generate ORDER BY clause for canonical selection.

    Returns SQL ORDER BY expression (without the ORDER BY keyword).
    """
    if method == "completeness":
        if scoring_columns:
            score = completeness_score_expr(scoring_columns)
            return f"({score}) DESC, entity_uid ASC"
        return "entity_uid ASC"

    if method == "recency":
        return "_source_updated_at DESC, entity_uid ASC"

    if method == "source_priority" and source_priority:
        case_parts = ", ".join(
            f"WHEN source_name = '{sql_escape(src)}' THEN {i}"
            for i, src in enumerate(source_priority)
        )
        return f"CASE {case_parts} ELSE 999 END ASC, entity_uid ASC"

    return "entity_uid ASC"

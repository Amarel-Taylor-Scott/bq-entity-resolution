"""Helper functions for scoring signals, filters, and banding.

Builds SQL fragments for:
- Term-frequency LEFT JOINs
- Hard negative disqualification filters
- Hard positive boost expressions
- Auto-match flag expressions
- Score band classification
- Band elevation from hard positives
"""

from __future__ import annotations

from bq_entity_resolution.columns import (
    MATCH_TOTAL_SCORE,
    TERM_FREQUENCY_COLUMN,
    TERM_FREQUENCY_VALUE,
)
from bq_entity_resolution.sql.builders.comparison.models import (
    ComparisonDef,
    HardNegative,
    HardPositive,
    ScoreBand,
)


def _build_tf_joins(comparisons: list[ComparisonDef], tf_table: str | None) -> list[str]:
    """Build LEFT JOINs for term-frequency enabled comparisons."""
    if not tf_table:
        return []

    lines: list[str] = []
    for comp in comparisons:
        if comp.tf_enabled:
            alias = f"tf_{comp.name}"
            lines.append(f"  LEFT JOIN `{tf_table}` {alias}")
            lines.append(f"    ON {alias}.{TERM_FREQUENCY_COLUMN} = '{comp.tf_column}'")
            lines.append(
                f"    AND {alias}.{TERM_FREQUENCY_VALUE} = CAST(l.{comp.tf_column} AS STRING)"
            )
    return lines


def _build_disqualify_filters(hard_negatives: list[HardNegative]) -> list[str]:
    """Build WHERE clause filters for disqualification hard negatives."""
    lines: list[str] = []
    for hn in hard_negatives:
        if hn.action == "disqualify":
            lines.append(f"  AND NOT ({hn.sql_condition})")
    return lines


def _build_hard_positive_boosts(hard_positives: list[HardPositive]) -> list[str]:
    """Build CASE WHEN expressions for hard positive boost actions."""
    lines: list[str] = []
    for hp in hard_positives:
        if hp.action == "boost":
            lines.append(
                f"      + CASE WHEN {hp.sql_condition} "
                f"THEN {hp.boost} ELSE 0.0 END"
            )
    return lines


def _build_auto_match_flag(hard_positives: list[HardPositive]) -> str | None:
    """Build SQL expression for auto_match flag if any hard positives use it."""
    auto_match_conds = [
        hp.sql_condition for hp in hard_positives if hp.action == "auto_match"
    ]
    if not auto_match_conds:
        return None
    combined = " OR ".join(f"({c})" for c in auto_match_conds)
    return f"CASE WHEN {combined} THEN TRUE ELSE FALSE END"


def _build_score_banding_expr(score_bands: list[ScoreBand]) -> str | None:
    """Build CASE WHEN expression for score band classification."""
    if not score_bands:
        return None
    # Sort bands by min_score descending so highest band matches first
    sorted_bands = sorted(score_bands, key=lambda b: b.min_score, reverse=True)
    parts = ["CASE"]
    for band in sorted_bands:
        parts.append(
            f"    WHEN {MATCH_TOTAL_SCORE} >= {band.min_score} "
            f"AND {MATCH_TOTAL_SCORE} < {band.max_score} "
            f"THEN '{band.name}'"
        )
    parts.append("    ELSE 'UNCLASSIFIED'")
    parts.append("  END")
    return "\n".join(parts)


def _build_band_elevation_expr(
    base_band_expr: str, hard_positives: list[HardPositive]
) -> str:
    """Wrap band expression with hard positive elevations."""
    elevate_hps = [hp for hp in hard_positives if hp.action == "elevate_band"]
    if not elevate_hps:
        return base_band_expr
    # Innermost CASE: highest priority elevation first
    result = base_band_expr
    for hp in reversed(elevate_hps):
        result = (
            f"CASE WHEN {hp.sql_condition} "
            f"THEN '{hp.target_band}' ELSE {result} END"
        )
    return result


__all__ = [
    "_build_tf_joins",
    "_build_disqualify_filters",
    "_build_hard_positive_boosts",
    "_build_auto_match_flag",
    "_build_score_banding_expr",
    "_build_band_elevation_expr",
]

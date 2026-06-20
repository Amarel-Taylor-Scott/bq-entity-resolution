"""SQL builder for field-level golden record assembly.

When canonical_selection.method = 'field_merge', each field in the golden
record is independently selected from the best source using per-field
strategies.

Available per-field strategies:
    most_complete   Pick from the record with the most non-null fields overall.
    most_recent     Pick from the most recently updated record.
    source_priority Pick from the highest-priority source.
    most_common     Pick the most frequently occurring non-null value in the
                    cluster (majority vote).
    weighted_vote   Pick the value with the highest recency-weighted vote.
                    Each record's vote is weighted by exponential time decay:
                    weight = EXP(-decay_rate * age_in_days). More recent
                    records have stronger votes.

This produces a single synthesized golden record per cluster where
first_name may come from source A and phone from source B, filling in
nulls and resolving conflicts using per-field logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    CLUSTER_ID,
    COMPLETENESS_SCORE,
    ENTITY_UID,
    SOURCE_NAME,
    SOURCE_RANK,
    SOURCE_UPDATED_AT,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_identifier


@dataclass(frozen=True)
class FieldStrategy:
    """Per-field merge strategy.

    Strategies:
        most_complete:    Value from the record with the most non-null fields.
        most_recent:      Value from the most recently updated record.
        source_priority:  Value from the highest-priority source.
        most_common:      Most frequently occurring non-null value (majority vote).
        weighted_vote:    Value with the highest recency-weighted vote count.
                          Uses exponential time decay controlled by decay_rate.
    """

    column: str
    strategy: str = "most_complete"
    source_priority: list[str] = field(default_factory=list)
    decay_rate: float = 0.01  # For weighted_vote: daily decay rate


@dataclass(frozen=True)
class GoldenRecordParams:
    """Parameters for golden record assembly."""

    source_columns: list[str]
    field_strategies: list[FieldStrategy] = field(default_factory=list)
    default_strategy: str = "most_complete"
    source_priority: list[str] = field(default_factory=list)
    scoring_columns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for col in self.source_columns:
            validate_identifier(col, "golden record source column")
        for col in self.scoring_columns:
            validate_identifier(col, "golden record scoring column")
        for fs in self.field_strategies:
            validate_identifier(fs.column, "field strategy column")


def _get_strategy(column: str, params: GoldenRecordParams) -> FieldStrategy:
    """Get the merge strategy for a specific column."""
    for fs in params.field_strategies:
        if fs.column == column:
            return fs
    return FieldStrategy(
        column=column,
        strategy=params.default_strategy,
        source_priority=params.source_priority,
    )


def _uses_vote_strategy(params: GoldenRecordParams) -> bool:
    """Check if any field uses most_common or weighted_vote strategy."""
    for col in params.source_columns:
        strategy = _get_strategy(col, params)
        if strategy.strategy in ("most_common", "weighted_vote"):
            return True
    return False


def _build_order_by(strategy: FieldStrategy) -> str:
    """Build the ORDER BY clause for a field's FIRST_VALUE window."""
    if strategy.strategy == "most_recent":
        return f"{SOURCE_UPDATED_AT} DESC, {ENTITY_UID} ASC"
    elif strategy.strategy == "source_priority" and strategy.source_priority:
        cases = []
        for i, src in enumerate(strategy.source_priority):
            cases.append(f"WHEN '{sql_escape(src)}' THEN {i}")
        case_expr = " ".join(cases)
        return (
            f"CASE {SOURCE_NAME} {case_expr} ELSE 999 END ASC, "
            f"{SOURCE_UPDATED_AT} DESC, {ENTITY_UID} ASC"
        )
    else:
        # most_complete (default): pick from the record with the most non-null fields
        return f"{COMPLETENESS_SCORE} DESC, {SOURCE_UPDATED_AT} DESC, {ENTITY_UID} ASC"


def _build_vote_cte(col: str, strategy: FieldStrategy) -> str:
    """Build a CTE that computes vote-based field selection.

    For most_common: plain count of each value.
    For weighted_vote: recency-weighted count using exponential decay.
    """
    cte_name = f"vote_{col}"

    if strategy.strategy == "weighted_vote":
        # Exponential time decay: weight = EXP(-decay_rate * days_since_update)
        weight_expr = (
            f"EXP(-{strategy.decay_rate} * "
            f"TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), {SOURCE_UPDATED_AT}, DAY))"
        )
        agg_expr = f"SUM({weight_expr})"
    else:
        # most_common: simple count
        agg_expr = "COUNT(*)"

    return (
        f"{cte_name} AS (\n"
        f"  SELECT\n"
        f"    {CLUSTER_ID},\n"
        f"    {col} AS voted_value,\n"
        f"    {agg_expr} AS vote_weight\n"
        f"  FROM clustered_scored\n"
        f"  WHERE {col} IS NOT NULL\n"
        f"  GROUP BY {CLUSTER_ID}, {col}\n"
        f"  QUALIFY ROW_NUMBER() OVER (\n"
        f"    PARTITION BY {CLUSTER_ID}\n"
        f"    ORDER BY vote_weight DESC\n"
        f"  ) = 1\n"
        f")"
    )


def build_golden_record_cte(params: GoldenRecordParams) -> SQLExpression:
    """Build the golden_fields CTE for field-level merging.

    Returns SQLExpression wrapping CTE body (no CREATE TABLE wrapper).
    Assumes an input CTE named 'clustered' with columns:
    entity_uid, cluster_id, source_name, _source_updated_at, and all source_columns.

    Strategies:
        most_complete   FIRST_VALUE ordered by completeness_score DESC
        most_recent     FIRST_VALUE ordered by _source_updated_at DESC
        source_priority FIRST_VALUE ordered by source priority rank ASC
        most_common     Majority vote: picks value with highest count in cluster
        weighted_vote   Recency-weighted vote with exponential time decay
    """
    parts: list[str] = []

    # First, compute completeness scores
    scoring_cols = params.scoring_columns or params.source_columns
    score_terms = [
        f"CASE WHEN {col} IS NOT NULL THEN 1 ELSE 0 END"
        for col in scoring_cols
    ]
    score_expr = " + ".join(score_terms) if score_terms else "0"

    # Source priority rank
    if params.source_priority:
        priority_cases = []
        for i, src in enumerate(params.source_priority):
            priority_cases.append(f"WHEN '{sql_escape(src)}' THEN {i}")
        case_expr = " ".join(priority_cases)
        source_rank_expr = f"CASE {SOURCE_NAME} {case_expr} ELSE 999 END"
    else:
        source_rank_expr = "0"

    parts.append("clustered_scored AS (")
    parts.append("  SELECT")
    parts.append("    c.*,")
    parts.append(f"    ({score_expr}) AS {COMPLETENESS_SCORE},")
    parts.append(f"    {source_rank_expr} AS {SOURCE_RANK}")
    parts.append("  FROM clustered c")
    parts.append("),")
    parts.append("")

    # Build vote CTEs for most_common / weighted_vote columns
    vote_columns: dict[str, FieldStrategy] = {}
    for col in params.source_columns:
        strategy = _get_strategy(col, params)
        if strategy.strategy in ("most_common", "weighted_vote"):
            vote_columns[col] = strategy

    for col, strategy in vote_columns.items():
        parts.append(_build_vote_cte(col, strategy) + ",")
        parts.append("")

    # Build per-field expressions
    # For vote-based columns: use COALESCE(vote.voted_value, FIRST_VALUE fallback)
    # For other columns: use FIRST_VALUE with strategy-specific ordering
    field_exprs: list[str] = []
    for col in params.source_columns:
        strategy = _get_strategy(col, params)
        if col in vote_columns:
            # Use the voted value, with FIRST_VALUE as fallback
            fallback_order = (
                f"{COMPLETENESS_SCORE} DESC, "
                f"{SOURCE_UPDATED_AT} DESC, "
                f"{ENTITY_UID} ASC"
            )
            field_exprs.append(
                f"    COALESCE(\n"
                f"      vote_{col}.voted_value,\n"
                f"      FIRST_VALUE({col} IGNORE NULLS) OVER (\n"
                f"        PARTITION BY cs.{CLUSTER_ID}\n"
                f"        ORDER BY {fallback_order}\n"
                f"        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING\n"
                f"      )\n"
                f"    ) AS {col}"
            )
        else:
            order_by = _build_order_by(strategy)
            field_exprs.append(
                f"    FIRST_VALUE({col} IGNORE NULLS) OVER (\n"
                f"      PARTITION BY {CLUSTER_ID}\n"
                f"      ORDER BY {order_by}\n"
                f"      ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING\n"
                f"    ) AS {col}"
            )

    parts.append("golden_fields AS (")
    parts.append("  SELECT")
    parts.append(f"    cs.{CLUSTER_ID},")
    parts.append(f"    cs.{ENTITY_UID},")
    parts.append(",\n".join(field_exprs) + ",")
    parts.append(f"    cs.{SOURCE_NAME},")
    parts.append(f"    cs.{SOURCE_UPDATED_AT},")
    parts.append(f"    cs.{COMPLETENESS_SCORE},")
    parts.append(f"    cs.{SOURCE_RANK},")
    parts.append("    ROW_NUMBER() OVER (")
    parts.append(f"      PARTITION BY cs.{CLUSTER_ID}")
    parts.append(
        f"      ORDER BY cs.{COMPLETENESS_SCORE} DESC, "
        f"cs.{SOURCE_UPDATED_AT} DESC, cs.{ENTITY_UID} ASC"
    )
    parts.append("    ) AS rn")

    # FROM clause with optional vote joins
    parts.append("  FROM clustered_scored cs")
    for col in vote_columns:
        parts.append(f"  LEFT JOIN vote_{col} ON cs.{CLUSTER_ID} = vote_{col}.{CLUSTER_ID}")

    parts.append(")")

    return SQLExpression.from_raw("\n".join(parts))

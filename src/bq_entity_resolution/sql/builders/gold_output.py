"""SQL builder for gold output (replaces gold_output.sql.j2).

Generates the final resolved entities table with:
- Cluster assignment join
- Canonical record election (completeness, recency, or source_priority)
- Match metadata from accumulated matches
- Partitioning and clustering options
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    CANONICAL_ENTITY_UID,
    CANONICAL_SCORE,
    CLUSTER_ID,
    ENTITY_UID,
    IS_CANONICAL,
    LEFT_ENTITY_UID,
    MATCH_CONFIDENCE,
    MATCH_TIER_NAME,
    MATCH_TIER_PRIORITY,
    MATCH_TOTAL_SCORE,
    MATCHED_AT,
    MATCHED_BY_TIER,
    PIPELINE_LOADED_AT,
    RESOLVED_ENTITY_ID,
    RIGHT_ENTITY_UID,
    SOURCE_NAME,
    SOURCE_UPDATED_AT,
)
from bq_entity_resolution.sql.builders.golden_record import (
    FieldStrategy,
    GoldenRecordParams,
    build_golden_record_cte,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_identifier, validate_table_ref


@dataclass(frozen=True)
class GoldOutputParams:
    """Parameters for gold output SQL generation."""
    target_table: str
    source_table: str
    cluster_table: str
    matches_table: str
    # 'completeness', 'recency', 'source_priority', 'field_merge'
    canonical_method: str = "completeness"
    scoring_columns: list[str] = field(default_factory=list)
    source_columns: list[str] = field(default_factory=list)
    passthrough_columns: list[str] = field(default_factory=list)
    include_match_metadata: bool = True
    entity_id_prefix: str = "ENT"
    partition_column: str | None = None
    cluster_columns: list[str] = field(default_factory=list)
    source_priority: list[str] = field(default_factory=list)
    # Field-level merge settings (used when canonical_method = 'field_merge')
    field_strategies: list[FieldStrategy] = field(default_factory=list)
    default_field_strategy: str = "most_complete"
    # Reconciliation strategy for match deduplication
    reconciliation_strategy: str = "tier_priority"

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        validate_table_ref(self.source_table)
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.matches_table)
        for col in self.scoring_columns:
            validate_identifier(col, "gold output scoring column")
        for col in self.source_columns:
            validate_identifier(col, "gold output source column")
        for col in self.passthrough_columns:
            validate_identifier(col, "gold output passthrough column")
        for col in self.cluster_columns:
            validate_identifier(col, "gold output cluster column")
        if self.partition_column:
            validate_identifier(self.partition_column, "gold output partition column")


def _match_metadata_order_by(strategy: str) -> str:
    """Return the ORDER BY clause for match metadata deduplication."""
    if strategy == "highest_score":
        return f"ORDER BY {MATCH_TOTAL_SCORE} DESC, {MATCH_TIER_PRIORITY} ASC"
    # tier_priority (default) and manual_review both use tier ordering
    return f"ORDER BY {MATCH_TIER_PRIORITY} ASC, {MATCH_TOTAL_SCORE} DESC"


def build_gold_output_sql(params: GoldOutputParams) -> SQLExpression:
    """Build gold resolved entities output SQL.

    Joins clusters to featured data, elects canonical records,
    and produces the final output with optional match metadata.

    Supports four canonical methods:
    - completeness: record with most non-null fields
    - recency: most recently updated record
    - source_priority: record from highest-priority source
    - field_merge: golden record assembled from best field per column
    """
    if params.canonical_method == "field_merge":
        return _build_field_merge_sql(params)
    return _build_standard_sql(params)


def _build_standard_sql(params: GoldOutputParams) -> SQLExpression:
    """Standard canonical election (one record per cluster)."""
    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{params.target_table}`")

    if params.partition_column:
        parts.append(f"PARTITION BY {params.partition_column}")

    if params.cluster_columns:
        cols = ", ".join(params.cluster_columns)
        parts.append(f"CLUSTER BY {cols}")

    parts.append("AS")
    parts.append("")

    # CTE: clustered
    parts.append("WITH clustered AS (")
    parts.append("  SELECT")
    parts.append("    f.*,")
    parts.append(f"    c.{CLUSTER_ID}")
    parts.append(f"  FROM `{params.source_table}` f")
    parts.append(f"  INNER JOIN `{params.cluster_table}` c USING ({ENTITY_UID})")
    parts.append("),")
    parts.append("")

    # CTE: canonical_scores
    parts.append("canonical_scores AS (")
    parts.append("  SELECT")
    parts.append(f"    {ENTITY_UID},")
    parts.append(f"    {CLUSTER_ID},")

    if params.canonical_method == "completeness":
        score_terms: list[str] = []
        for col in params.scoring_columns:
            score_terms.append(
                f"CASE WHEN {col} IS NOT NULL THEN 1 ELSE 0 END"
            )
        if score_terms:
            parts.append(f"    ({' + '.join(score_terms)}) AS {CANONICAL_SCORE},")
        else:
            parts.append(f"    0 AS {CANONICAL_SCORE},")
    elif params.canonical_method == "recency":
        parts.append(f"    UNIX_MICROS({SOURCE_UPDATED_AT}) AS {CANONICAL_SCORE},")
    elif params.canonical_method == "source_priority":
        cases: list[str] = []
        for i, src in enumerate(params.source_priority):
            cases.append(f"WHEN '{sql_escape(src)}' THEN {1000 - i}")
        case_expr = " ".join(cases)
        parts.append(
            f"    CASE {SOURCE_NAME} {case_expr} ELSE 0 END AS {CANONICAL_SCORE},"
        )

    # Remove trailing comma from last line
    parts[-1] = parts[-1].rstrip(",")
    parts.append("  FROM clustered")
    parts.append("),")
    parts.append("")

    # CTE: canonicals — elect one canonical per cluster
    parts.append("canonicals AS (")
    parts.append(f"  SELECT {CLUSTER_ID}, {ENTITY_UID} AS {CANONICAL_ENTITY_UID}")
    parts.append("  FROM (")
    parts.append("    SELECT")
    parts.append(f"      {CLUSTER_ID},")
    parts.append(f"      {ENTITY_UID},")
    parts.append("      ROW_NUMBER() OVER (")
    parts.append(
        f"        PARTITION BY {CLUSTER_ID} "
        f"ORDER BY {CANONICAL_SCORE} DESC, {ENTITY_UID} ASC"
    )
    parts.append("      ) AS rn")
    parts.append("    FROM canonical_scores")
    parts.append("  )")
    parts.append("  WHERE rn = 1")
    parts.append("),")
    parts.append("")

    # CTE: resolved
    parts.append("resolved AS (")
    parts.append("  SELECT")
    parts.append(f"    cl.{CLUSTER_ID} AS {RESOLVED_ENTITY_ID},")
    parts.append(f"    cl.{CLUSTER_ID},")
    parts.append(f"    can.{CANONICAL_ENTITY_UID},")
    parts.append(
        f"    (f.{ENTITY_UID} = can.{CANONICAL_ENTITY_UID}) AS {IS_CANONICAL},"
    )

    # Source columns
    for col in params.source_columns:
        parts.append(f"    f.{col},")

    # Passthrough columns
    for col in params.passthrough_columns:
        parts.append(f"    f.{col},")

    parts.append(f"    f.{SOURCE_NAME},")
    parts.append(f"    f.{ENTITY_UID},")
    parts.append(f"    f.{SOURCE_UPDATED_AT},")
    parts.append(f"    f.{PIPELINE_LOADED_AT}")
    parts.append("")
    parts.append("  FROM clustered f")
    parts.append(f"  JOIN canonicals can ON f.{CLUSTER_ID} = can.{CLUSTER_ID}")
    parts.append(
        f"  JOIN `{params.cluster_table}` cl ON f.{ENTITY_UID} = cl.{ENTITY_UID}"
    )
    parts.append(")")
    parts.append("")

    # Final SELECT
    _append_final_select(parts, params)

    return SQLExpression.from_raw("\n".join(parts))


def _build_field_merge_sql(params: GoldOutputParams) -> SQLExpression:
    """Field-level golden record assembly (best field from best source)."""
    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{params.target_table}`")

    if params.partition_column:
        parts.append(f"PARTITION BY {params.partition_column}")

    if params.cluster_columns:
        cols = ", ".join(params.cluster_columns)
        parts.append(f"CLUSTER BY {cols}")

    parts.append("AS")
    parts.append("")

    # CTE: clustered
    parts.append("WITH clustered AS (")
    parts.append("  SELECT")
    parts.append("    f.*,")
    parts.append(f"    c.{CLUSTER_ID}")
    parts.append(f"  FROM `{params.source_table}` f")
    parts.append(f"  INNER JOIN `{params.cluster_table}` c USING ({ENTITY_UID})")
    parts.append("),")
    parts.append("")

    # Golden record CTEs
    golden_cte = build_golden_record_cte(GoldenRecordParams(
        source_columns=params.source_columns,
        field_strategies=params.field_strategies,
        default_strategy=params.default_field_strategy,
        source_priority=params.source_priority,
        scoring_columns=params.scoring_columns,
    ))
    parts.append(golden_cte.render() + ",")
    parts.append("")

    # CTE: resolved — use golden_fields for column values
    parts.append("resolved AS (")
    parts.append("  SELECT")
    parts.append(f"    g.{CLUSTER_ID} AS {RESOLVED_ENTITY_ID},")
    parts.append(f"    g.{CLUSTER_ID},")
    parts.append(f"    g.{ENTITY_UID} AS {CANONICAL_ENTITY_UID},")
    parts.append(f"    TRUE AS {IS_CANONICAL},")

    for col in params.source_columns:
        parts.append(f"    g.{col},")

    parts.append(f"    g.{SOURCE_NAME},")
    parts.append(f"    g.{ENTITY_UID},")
    parts.append(f"    g.{SOURCE_UPDATED_AT},")
    parts.append(f"    CURRENT_TIMESTAMP() AS {PIPELINE_LOADED_AT}")
    parts.append("")
    parts.append("  FROM golden_fields g")
    parts.append("  WHERE g.rn = 1")
    parts.append(")")
    parts.append("")

    # Final SELECT
    _append_final_select(parts, params)

    return SQLExpression.from_raw("\n".join(parts))


def _append_final_select(parts: list[str], params: GoldOutputParams) -> None:
    """Append the final SELECT with optional match metadata."""
    parts.append("SELECT")
    parts.append("  r.*")

    if params.include_match_metadata:
        parts.append(f"  ,m.{MATCH_TIER_NAME} AS {MATCHED_BY_TIER}")
        parts.append(f"  ,m.{MATCH_TOTAL_SCORE} AS match_score")
        parts.append(f"  ,m.{MATCH_CONFIDENCE}")
        parts.append(f"  ,m.{MATCHED_AT}")

    parts.append("FROM resolved r")

    if params.include_match_metadata:
        order_by = _match_metadata_order_by(params.reconciliation_strategy)
        parts.append("LEFT JOIN (")
        parts.append("  SELECT")
        parts.append(f"    {LEFT_ENTITY_UID},")
        parts.append(f"    {RIGHT_ENTITY_UID},")
        parts.append(f"    {MATCH_TIER_NAME},")
        parts.append(f"    {MATCH_TOTAL_SCORE},")
        parts.append(f"    {MATCH_CONFIDENCE},")
        parts.append(f"    {MATCHED_AT},")
        parts.append("    ROW_NUMBER() OVER (")
        parts.append(f"      PARTITION BY {RIGHT_ENTITY_UID}")
        parts.append(f"      {order_by}")
        parts.append("    ) AS rn")
        parts.append(f"  FROM `{params.matches_table}`")
        parts.append(") m")
        parts.append(f"  ON r.{ENTITY_UID} = m.{RIGHT_ENTITY_UID} AND m.rn = 1")

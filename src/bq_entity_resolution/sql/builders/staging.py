"""SQL builder for incremental staging (replaces incremental_load.sql.j2).

Generates SQL to load source data into bronze staging area with:
- Deterministic entity UID generation via FARM_FINGERPRINT
- Watermark-based incremental filtering with grace period
- Source-level filters and supplemental joins
- Batch size limits

Entity UID Design — INT64 via FARM_FINGERPRINT
================================================
The entity_uid is the universal join key throughout the entire pipeline:
  staging → features → blocking → matching → clustering → gold output

It is generated as:
  FARM_FINGERPRINT(CONCAT(source_name, '||', CAST(unique_key AS STRING)))

This produces a deterministic INT64 that:
  1. Is unique per source record (source_name scopes the unique_key)
  2. Is stable across runs (same input → same INT64, always)
  3. Enables INT64 equi-joins everywhere downstream (~3-5x faster than STRING)
  4. Takes 8 bytes of storage vs variable-length STRING concatenation
  5. Works naturally with CLUSTER BY for storage co-location

All downstream JOINs (blocking → candidates, candidates → matches,
matches → clusters) use entity_uid INT64 comparisons. This is the
single most impactful performance decision in the pipeline architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bq_entity_resolution.columns import (
    ENTITY_UID,
    PIPELINE_LOADED_AT,
    SOURCE_NAME,
    SOURCE_UPDATED_AT,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import (
    format_watermark_value,
    sql_escape,
    validate_identifier,
    validate_table_ref,
)

_VALID_JOIN_TYPES = frozenset({"LEFT", "INNER", "CROSS", "RIGHT"})


@dataclass(frozen=True)
class JoinDef:
    """A supplemental join for staging."""
    table: str
    on: str
    type: str = "LEFT"
    alias: str = ""

    def __post_init__(self) -> None:
        validate_table_ref(self.table)
        if self.alias:
            validate_identifier(self.alias, "join alias")
        if self.type not in _VALID_JOIN_TYPES:
            raise ValueError(
                f"Invalid join type: {self.type!r}. "
                f"Must be one of {sorted(_VALID_JOIN_TYPES)}."
            )


@dataclass(frozen=True)
class PartitionCursor:
    """A partition-aware cursor for scan optimization.

    When BigQuery tables are partitioned by columns beyond the
    timestamp (e.g. state, region, policy_year), adding partition
    cursors generates AND predicates that enable partition pruning.
    """
    column: str
    value: Any
    strategy: str = "range"  # "range", "equality", "in_list"

    def __post_init__(self) -> None:
        validate_identifier(self.column, "partition cursor column")


@dataclass(frozen=True)
class HashCursor:
    """A hash-based virtual cursor column for batch delineation.

    When no natural secondary cursor exists, generates:
        FARM_FINGERPRINT(column) MOD modulus AS alias

    This adds a deterministic numeric dimension (0..modulus-1) to the
    watermark tuple, enabling clean batch boundaries even when the
    primary cursor (e.g., date) has millions of records per value.
    """
    column: str
    modulus: int = 1000
    alias: str = "_hash_partition"

    def __post_init__(self) -> None:
        validate_identifier(self.column, "hash cursor column")
        validate_identifier(self.alias, "hash cursor alias")


@dataclass(frozen=True)
class StagingParams:
    """Parameters for staging SQL generation."""
    target_table: str
    source_name: str
    source_table: str
    unique_key: str
    updated_at: str
    columns: list[str] = field(default_factory=list)
    passthrough_columns: list[str] = field(default_factory=list)
    joins: list[JoinDef] = field(default_factory=list)
    filter: str | None = None
    watermark: dict[str, Any] | None = None
    grace_period_hours: int = 0
    full_refresh: bool = False
    partition_column: str | None = None
    batch_size: int | None = None
    cluster_by: list[str] = field(default_factory=list)
    partition_by: str | None = None  # e.g. "DATE(source_updated_at)"
    partition_cursors: list[PartitionCursor] = field(default_factory=list)
    cursor_mode: str = "ordered"  # "ordered" or "independent"
    hash_cursor: HashCursor | None = None
    table_expiration_days: int | None = None

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        validate_table_ref(self.source_table)
        validate_identifier(self.unique_key, "staging unique key")
        if self.updated_at:
            validate_identifier(self.updated_at, "staging updated_at")
        for col in self.columns:
            validate_identifier(col, "staging column")
        for col in self.passthrough_columns:
            validate_identifier(col, "staging passthrough column")
        for col in self.cluster_by:
            validate_identifier(col, "staging cluster_by column")
        if self.partition_column:
            validate_identifier(self.partition_column, "staging partition column")


def _build_ordered_watermark(
    watermark: dict[str, Any],
    grace_period_hours: int = 0,
) -> str:
    """Build ordered tuple watermark comparison.

    For columns (c1, c2, c3) with values (v1, v2, v3), generates::

        c1 > v1
        OR (c1 = v1 AND c2 > v2)
        OR (c1 = v1 AND c2 = v2 AND c3 > v3)

    Grace period is applied only to the first (timestamp) column.
    """
    cols = list(watermark.keys())
    vals = list(watermark.values())
    clauses: list[str] = []

    for depth in range(len(cols)):
        eq_parts: list[str] = []
        for i in range(depth):
            fv = format_watermark_value(vals[i])
            eq_parts.append(f"{cols[i]} = {fv}")

        fv = format_watermark_value(vals[depth])
        if depth == 0 and grace_period_hours and grace_period_hours > 0:
            gt_part = (
                f"{cols[depth]} > TIMESTAMP_SUB({fv}, "
                f"INTERVAL {grace_period_hours} HOUR)"
            )
        else:
            gt_part = f"{cols[depth]} > {fv}"

        if eq_parts:
            clause = " AND ".join(eq_parts) + " AND " + gt_part
            clauses.append(f"({clause})")
        else:
            clauses.append(gt_part)

    return "\n  OR ".join(clauses)


def _build_order_by_columns(params: StagingParams) -> list[str]:
    """Build ORDER BY column list for deterministic batching.

    When using ordered cursor mode with multiple watermark columns,
    include all watermark columns in the ORDER BY for deterministic
    batch boundaries. Always ends with entity_uid as tiebreaker.
    """
    order_cols: list[str] = []

    if params.watermark and params.cursor_mode == "ordered":
        # Use watermark columns as primary ordering
        for col in params.watermark:
            if col not in order_cols:
                order_cols.append(col)
    else:
        order_cols.append(params.updated_at)

    # Hash cursor alias in ORDER BY
    if params.hash_cursor and params.hash_cursor.alias not in order_cols:
        order_cols.append(params.hash_cursor.alias)

    # Entity UID as final tiebreaker
    if ENTITY_UID not in order_cols:
        order_cols.append(ENTITY_UID)

    return order_cols


def build_staging_sql(params: StagingParams) -> SQLExpression:
    """Build staging/incremental load SQL.

    Returns an SQLExpression wrapping the generated SQL string.
    """
    parts: list[str] = []

    # CREATE OR REPLACE TABLE
    parts.append(f"CREATE OR REPLACE TABLE `{params.target_table}`")
    if params.partition_by:
        parts.append(f"PARTITION BY {params.partition_by}")
    if params.cluster_by:
        parts.append(f"CLUSTER BY {', '.join(params.cluster_by)}")
    if params.table_expiration_days:
        parts.append(
            f"OPTIONS(expiration_timestamp="
            f"TIMESTAMP_ADD(CURRENT_TIMESTAMP(), "
            f"INTERVAL {params.table_expiration_days} DAY))"
        )
    parts.append("AS")
    parts.append("")
    parts.append("SELECT")

    # Entity UID — INT64 via FARM_FINGERPRINT.
    # PERF: This is the foundation of pipeline performance. By generating
    # entity_uid as INT64 here, ALL downstream JOINs (blocking, matching,
    # clustering) use 8-byte integer comparisons instead of variable-length
    # STRING concatenation comparisons. The CONCAT includes source_name to
    # ensure uniqueness across sources (same unique_key in different sources
    # produces different entity_uids).
    escaped_name = sql_escape(params.source_name)
    parts.append("  FARM_FINGERPRINT(")
    parts.append("    CONCAT(")
    parts.append(f"      '{escaped_name}', '||',")
    parts.append(f"      CAST({params.unique_key} AS STRING)")
    parts.append("    )")
    parts.append(f"  ) AS {ENTITY_UID},")
    parts.append("")
    parts.append(f"  '{escaped_name}' AS {SOURCE_NAME},")
    parts.append("")

    # Source columns
    for col in params.columns:
        parts.append(f"  {col},")

    # Passthrough columns
    for col in params.passthrough_columns:
        parts.append(f"  {col},")

    # Hash cursor virtual column (if configured)
    if params.hash_cursor:
        hc = params.hash_cursor
        parts.append(
            f"  MOD(FARM_FINGERPRINT(CAST({hc.column} AS STRING)), {hc.modulus}) "
            f"AS {hc.alias},"
        )

    # Metadata columns
    parts.append(f"  {params.updated_at} AS {SOURCE_UPDATED_AT},")
    parts.append(f"  CURRENT_TIMESTAMP() AS {PIPELINE_LOADED_AT}")
    parts.append("")
    parts.append(f"FROM `{params.source_table}` AS src")

    # Supplemental joins
    for i, join in enumerate(params.joins):
        alias = join.alias or f"j_{i}"
        parts.append(f"{join.type} JOIN `{join.table}` AS {alias}")
        parts.append(f"  ON {join.on}")

    parts.append("WHERE 1=1")

    # Source-level filter
    if params.filter:
        parts.append(f"AND ({params.filter})")

    # Incremental filter with grace period
    if params.watermark and not params.full_refresh:
        if params.cursor_mode == "ordered" and len(params.watermark) > 1:
            # Ordered tuple comparison: (col1, col2) > (wm1, wm2)
            # col1 > wm1 OR (col1 = wm1 AND col2 > wm2)
            # 3+ cols: c1>w1 OR (c1=w1 AND (c2>w2 OR ...))
            parts.append("AND (")
            wm_clause = _build_ordered_watermark(
                params.watermark, params.grace_period_hours,
            )
            parts.append(f"  {wm_clause}")
            parts.append(")")
        else:
            # Independent (OR) mode — original behavior
            conditions: list[str] = []
            for col, val in params.watermark.items():
                formatted_val = format_watermark_value(val)
                if params.grace_period_hours and params.grace_period_hours > 0:
                    conditions.append(
                        f"{col} > TIMESTAMP_SUB({formatted_val}, "
                        f"INTERVAL {params.grace_period_hours} HOUR)"
                    )
                else:
                    conditions.append(f"{col} > {formatted_val}")
            parts.append("AND (")
            parts.append(f"  {' OR '.join(conditions)}")
            parts.append(")")

    # Partition cursor filters (AND with time watermark for partition pruning)
    if params.partition_cursors and not params.full_refresh:
        for pc in params.partition_cursors:
            formatted_val = format_watermark_value(pc.value)
            if pc.strategy == "range":
                parts.append(f"AND {pc.column} >= {formatted_val}")
            elif pc.strategy == "equality":
                parts.append(f"AND {pc.column} = {formatted_val}")
            elif pc.strategy == "in_list" and isinstance(pc.value, (list, tuple)):
                vals = ", ".join(format_watermark_value(v) for v in pc.value)
                parts.append(f"AND {pc.column} IN ({vals})")

    # Exclude incomplete current day
    if params.partition_column:
        parts.append(f"AND {params.partition_column} < CURRENT_DATE()")

    # Batch size limit with deterministic ordering
    if params.batch_size:
        # Build ORDER BY from watermark columns for deterministic batching
        order_cols = _build_order_by_columns(params)
        parts.append(f"ORDER BY {', '.join(order_cols)}")
        parts.append(f"LIMIT {params.batch_size}")

    return SQLExpression.from_raw("\n".join(parts))

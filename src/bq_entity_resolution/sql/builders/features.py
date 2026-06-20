"""SQL builder for feature engineering (replaces all_features.sql.j2 + term_frequencies.sql.j2).

Generates SQL to:
1. UNION ALL staged source tables
2. Pass 1: Compute independent features from source columns
3. Pass 2: Compute dependent features (reference pass 1 columns)
4. Pass 3: Compute blocking keys and composite keys
5. Term frequency statistics for TF-adjusted matching
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    ENTITY_UID,
    PIPELINE_LOADED_AT,
    SOURCE_NAME,
    SOURCE_UPDATED_AT,
    TERM_FREQUENCY_COLUMN,
    TERM_FREQUENCY_COUNT,
    TERM_FREQUENCY_RATIO,
    TERM_FREQUENCY_VALUE,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref


@dataclass(frozen=True)
class FeatureExpr:
    """A named feature expression."""
    name: str
    expression: str

    def __post_init__(self) -> None:
        validate_identifier(self.name, "feature expression name")


@dataclass(frozen=True)
class CustomJoin:
    """A custom JOIN for feature computation."""
    table: str
    alias: str
    on: str

    def __post_init__(self) -> None:
        validate_table_ref(self.table)
        validate_identifier(self.alias, "custom join alias")


@dataclass(frozen=True)
class EnrichmentJoin:
    """A lookup table enrichment join for feature engineering.

    Enrichment joins bring in external reference data (e.g., Census-standardized
    addresses, vendor lookups) by computing a join key from source columns using
    a registered feature function and matching against a lookup table.

    PERF: When join_key_expression produces INT64 (e.g., via FARM_FINGERPRINT),
    the LEFT JOIN runs at INT64 speed — ~3-5x faster than STRING joins.
    The enrichment columns are then available for downstream feature computation,
    blocking, and matching.
    """
    table: str                  # Fully-qualified BQ table
    alias: str                  # JOIN alias (typically the enrichment name)
    join_key_expression: str    # SQL expression computed from source columns
    lookup_key: str             # Column in the lookup table to join on
    columns: list[str]          # Columns to SELECT from the lookup table
    column_prefix: str = ""     # Prefix for output column names
    match_flag: str = ""        # If set, auto-generates a 0/1 INT64 flag column
    join_type: str = "LEFT"     # LEFT (default) or INNER

    def __post_init__(self) -> None:
        validate_table_ref(self.table)
        validate_identifier(self.alias, "enrichment join alias")
        validate_identifier(self.lookup_key, "enrichment lookup key")
        for col in self.columns:
            validate_identifier(col, "enrichment column")
        if self.column_prefix:
            validate_identifier(self.column_prefix, "enrichment column prefix")
        if self.match_flag:
            validate_identifier(self.match_flag, "enrichment match flag")
        if self.join_type not in ("LEFT", "INNER"):
            raise ValueError(
                f"Invalid join_type: {self.join_type!r}. Must be 'LEFT' or 'INNER'."
            )


@dataclass(frozen=True)
class TFColumn:
    """A column to compute term frequencies for."""
    column_name: str

    def __post_init__(self) -> None:
        validate_identifier(self.column_name, "term frequency column")


@dataclass(frozen=True)
class FeatureParams:
    """Parameters for feature engineering SQL generation."""
    target_table: str
    source_tables: list[str]
    source_columns: list[str]
    passthrough_columns: list[str] = field(default_factory=list)
    feature_expressions: list[FeatureExpr] = field(default_factory=list)
    dependent_features: list[FeatureExpr] = field(default_factory=list)
    blocking_keys: list[FeatureExpr] = field(default_factory=list)
    composite_keys: list[FeatureExpr] = field(default_factory=list)
    custom_joins: list[CustomJoin] = field(default_factory=list)
    enrichment_joins: list[EnrichmentJoin] = field(default_factory=list)
    cluster_by: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        for t in self.source_tables:
            validate_table_ref(t)


def build_features_sql(params: FeatureParams) -> SQLExpression:
    """Build feature engineering SQL.

    Multi-pass CTE:
    - base: UNION ALL of staged sources
    - enriched (optional): LEFT JOIN to lookup tables for enrichment
    - features_pass1: independent features from source columns
    - featured: dependent features that reference pass 1 columns
    - Final SELECT: blocking keys and composite keys

    When enrichment_joins are configured, an 'enriched' CTE is inserted
    between 'base' and 'features_pass1'. This brings in external reference
    data (Census-standardized addresses, GPS coordinates, etc.) that
    downstream features can reference.
    """
    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{params.target_table}`")
    if params.cluster_by:
        parts.append(f"CLUSTER BY {', '.join(params.cluster_by)}")
    parts.append("AS")
    parts.append("")
    parts.append("WITH base AS (")

    # UNION ALL source tables
    for i, src_table in enumerate(params.source_tables):
        parts.append("  SELECT")
        parts.append(f"    {ENTITY_UID},")
        parts.append(f"    {SOURCE_NAME},")
        parts.append(f"    {SOURCE_UPDATED_AT},")
        parts.append(f"    {PIPELINE_LOADED_AT},")

        for col in params.source_columns:
            parts.append(f"    {col},")

        for j, col in enumerate(params.passthrough_columns):
            is_last_col = (j == len(params.passthrough_columns) - 1)
            has_features = len(params.feature_expressions) > 0
            comma = "," if not is_last_col or has_features else ""
            parts.append(f"    {col}{comma}")

        # If no passthrough cols but we need a trailing comma handler
        if not params.passthrough_columns and not params.source_columns:
            pass  # entity_uid, source_name, timestamps are enough

        parts.append(f"  FROM `{src_table}`")

        if i < len(params.source_tables) - 1:
            parts.append("  UNION ALL")

    parts.append("),")
    parts.append("")

    # Enrichment joins: optional CTE that LEFT JOINs external lookup tables.
    # PERF: Enrichment joins using FARM_FINGERPRINT keys are INT64 equi-joins,
    # running at ~3-5x the speed of equivalent STRING joins.
    has_enrichment = bool(params.enrichment_joins)
    if has_enrichment:
        parts.append("enriched AS (")
        parts.append("  SELECT")
        parts.append("    b.*,")

        # Add columns from each enrichment join
        enrichment_cols: list[str] = []
        for ej in params.enrichment_joins:
            for col in ej.columns:
                output_name = f"{ej.column_prefix}{col}" if ej.column_prefix else col
                enrichment_cols.append(
                    f"    {ej.alias}.{col} AS {output_name}"
                )
            if ej.match_flag:
                # Auto-generate a 0/1 INT64 match flag based on first column
                first_col = ej.columns[0] if ej.columns else ej.lookup_key
                enrichment_cols.append(
                    f"    CASE WHEN {ej.alias}.{first_col} IS NOT NULL "
                    f"THEN 1 ELSE 0 END AS {ej.match_flag}"
                )

        parts.append(",\n".join(enrichment_cols))
        parts.append("  FROM base b")

        for ej in params.enrichment_joins:
            parts.append(
                f"  {ej.join_type} JOIN `{ej.table}` AS {ej.alias}"
            )
            parts.append(
                f"    ON {ej.join_key_expression} = {ej.alias}.{ej.lookup_key}"
            )

        parts.append("),")
        parts.append("")

    # Pass 1: Independent features.
    # Source CTE is 'enriched' if enrichment joins exist, otherwise 'base'.
    source_cte = "enriched" if has_enrichment else "base"
    source_alias = "e" if has_enrichment else "b"

    parts.append("features_pass1 AS (")
    parts.append("  SELECT")
    parts.append(f"    {source_alias}.*,")

    for i, feat in enumerate(params.feature_expressions):
        comma = "," if i < len(params.feature_expressions) - 1 else ""
        parts.append(f"    {feat.expression} AS {feat.name}{comma}")

    parts.append(f"  FROM {source_cte} {source_alias}")

    for join in params.custom_joins:
        parts.append(f"  LEFT JOIN `{join.table}` AS {join.alias}")
        parts.append(f"    ON {join.on}")

    parts.append("),")
    parts.append("")

    # Pass 2: Dependent features
    parts.append("featured AS (")
    if params.dependent_features:
        parts.append("  SELECT")
        parts.append("    p.*,")
        for i, feat in enumerate(params.dependent_features):
            comma = "," if i < len(params.dependent_features) - 1 else ""
            parts.append(f"    {feat.expression} AS {feat.name}{comma}")
        parts.append("  FROM features_pass1 p")
    else:
        parts.append("  SELECT p.*")
        parts.append("  FROM features_pass1 p")
    parts.append(")")
    parts.append("")

    # Pass 3: Blocking keys and composite keys
    parts.append("SELECT")
    parts.append("  f.*,")

    all_keys = []
    for bk in params.blocking_keys:
        all_keys.append(f"  {bk.expression} AS {bk.name}")
    for ck in params.composite_keys:
        all_keys.append(f"  {ck.expression} AS {ck.name}")

    if all_keys:
        parts.append(",\n".join(all_keys))
    else:
        # Remove trailing comma from f.*
        parts[-1] = "  f.*"

    parts.append("")
    parts.append("FROM featured f")

    return SQLExpression.from_raw("\n".join(parts))


def build_term_frequencies_sql(
    target_table: str,
    source_table: str,
    tf_columns: list[TFColumn],
) -> SQLExpression:
    """Build term frequency computation SQL.

    Computes value frequencies for each TF-enabled column.
    Common values get higher frequency, reducing match evidence.
    """
    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{target_table}` AS")
    parts.append("")

    for i, col in enumerate(tf_columns):
        if i > 0:
            parts.append("UNION ALL")

        parts.append("SELECT")
        parts.append(f"  '{col.column_name}' AS {TERM_FREQUENCY_COLUMN},")
        parts.append(f"  CAST({col.column_name} AS STRING) AS {TERM_FREQUENCY_VALUE},")
        parts.append(f"  COUNT(*) AS {TERM_FREQUENCY_COUNT},")
        parts.append(f"  COUNT(*) / SUM(COUNT(*)) OVER () AS {TERM_FREQUENCY_RATIO}")
        parts.append(f"FROM `{source_table}`")
        parts.append(f"WHERE {col.column_name} IS NOT NULL")
        parts.append(f"GROUP BY {col.column_name}")

    return SQLExpression.from_raw("\n".join(parts))

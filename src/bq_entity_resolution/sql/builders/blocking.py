"""SQL builder for multi-path blocking (replaces multi_path_candidates.sql.j2).

Generates SQL to create candidate pairs from multiple blocking paths:
- Intra-batch: new records vs new records
- Cross-batch: new records vs gold canonicals
- Per-path candidate limits
- Deduplication across paths
- Prior-tier exclusion
- LSH bucket keys from embeddings

BigQuery Blocking Performance Notes
=====================================
Blocking is the single most performance-critical stage. It determines the
number of candidate pairs that flow into the (expensive) comparison stage.
The JOIN conditions in blocking run on EVERY record, so column types matter:

    INT64 blocking keys (fp_ columns):
      - BQ uses hash-join with 8-byte keys → O(1) per probe
      - CLUSTER BY on INT64 enables storage-level co-location
      - Ideal for: FARM_FINGERPRINT(col), dob_year, entity_uid

    STRING blocking keys (bk_ columns):
      - BQ uses sort-merge or hash-join but hashes variable-length strings
      - Extra cost from byte-by-byte hashing + comparison
      - Acceptable for: soundex (4 chars), zip3 (3 chars), state (2 chars)
      - Avoid for: full address, company names, long identifiers

    Composite blocking (multiple keys per path):
      - Multiple AND conditions: l.key1 = r.key1 AND l.key2 = r.key2
      - BQ may hash only the first key, then filter the rest
      - Alternative: FARM_FINGERPRINT(CONCAT(key1, '||', key2)) produces
        a single INT64 that captures both keys in one comparison

The entity_uid column is INT64 (FARM_FINGERPRINT-based) throughout the
pipeline, ensuring all candidate pair JOINs are INT64-native.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    BLOCKING_METRIC_CANDIDATE_PAIRS,
    BLOCKING_METRIC_COMPUTED_AT,
    BLOCKING_METRIC_MATCHED_PAIRS,
    BLOCKING_METRIC_PRECISION,
    BLOCKING_METRIC_REDUCTION_RATIO,
    BLOCKING_METRIC_TIER_NAME,
    BLOCKING_METRIC_TOTAL_RECORDS,
    BLOCKING_PATH,
    ENTITY_UID,
    LEFT_ENTITY_UID,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_identifier, validate_table_ref


@dataclass(frozen=True)
class BlockingPath:
    """A single blocking path definition."""
    index: int
    keys: list[str] = field(default_factory=list)
    lsh_keys: list[str] = field(default_factory=list)
    candidate_limit: int = 0
    bucket_size_limit: int = 0  # max entities per bucket (0 = no limit)

    def __post_init__(self) -> None:
        for key in self.keys:
            validate_identifier(key, "blocking key")
        for key in self.lsh_keys:
            validate_identifier(key, "LSH blocking key")


@dataclass(frozen=True)
class BlockingParams:
    """Parameters for blocking SQL generation."""
    target_table: str
    source_table: str
    blocking_paths: list[BlockingPath]
    tier_name: str
    cross_batch: bool = False
    canonical_table: str | None = None
    excluded_pairs_table: str | None = None
    lsh_table: str | None = None
    link_type: str | None = None  # 'link_and_dedupe', 'dedupe_only', 'link_only'
    cluster_by: list[str] = field(default_factory=list)
    partition_by: str | None = None

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        validate_table_ref(self.source_table)
        if self.canonical_table is not None:
            validate_table_ref(self.canonical_table)
        if self.excluded_pairs_table is not None:
            validate_table_ref(self.excluded_pairs_table)
        if self.lsh_table is not None:
            validate_table_ref(self.lsh_table)


def _build_join_conditions(
    path: BlockingPath,
    is_cross_batch: bool,
    link_type: str | None,
) -> list[str]:
    """Build the ON clause conditions for a blocking join."""
    conditions: list[str] = []

    # Entity ordering (intra-batch only)
    if not is_cross_batch:
        conditions.append("l.entity_uid < r.entity_uid")
    else:
        conditions.append("l.entity_uid != r.entity_uid")

    # Link type filter
    if link_type == "dedupe_only":
        conditions.append("l.source_name = r.source_name")
    elif link_type == "link_only":
        conditions.append("l.source_name != r.source_name")

    # Blocking keys — equi-join conditions.
    # PERF: Each key produces an equality condition in the JOIN ON clause.
    # INT64 keys (fp_ columns) are ~3-5x faster here than STRING keys.
    # IS NOT NULL filter prevents NULL=NULL matches (which BQ would skip
    # anyway, but explicit filter helps the query optimizer).
    for key in path.keys:
        conditions.append(f"l.{key} = r.{key}")
        conditions.append(f"l.{key} IS NOT NULL")

    # LSH bucket keys — INT64 from FARM_FINGERPRINT of bucket hashes.
    # These enable approximate nearest-neighbor blocking for embeddings.
    for key in path.lsh_keys:
        conditions.append(f"l.{key} = r.{key}")
        conditions.append(f"l.{key} IS NOT NULL")

    return conditions


def _build_path_cte(
    path: BlockingPath,
    tier_name: str,
    source_table: str,
    is_cross_batch: bool,
    canonical_table: str | None,
    lsh_table: str | None,
    link_type: str | None,
) -> str:
    """Build a single blocking path CTE."""
    prefix = "cross" if is_cross_batch else "intra"
    cte_name = f"{prefix}_path_{path.index}"
    path_label = f"{tier_name}_{prefix}_{path.index}"

    # Determine left and right table sources
    has_lsh = bool(path.lsh_keys and lsh_table)
    if has_lsh:
        left_source = "source_with_lsh"
        right_source = "canonical_with_lsh" if is_cross_batch else "source_with_lsh"
    else:
        left_source = f"`{source_table}`"
        right_source = f"`{canonical_table}`" if is_cross_batch else f"`{source_table}`"

    conditions = _build_join_conditions(path, is_cross_batch, link_type)
    on_clause = "\n    AND ".join(conditions)

    lines = [
        f"{cte_name} AS (",
        "  SELECT",
        f"    l.{ENTITY_UID} AS {LEFT_ENTITY_UID},",
        f"    r.{ENTITY_UID} AS {RIGHT_ENTITY_UID},",
        f"    '{path_label}' AS {BLOCKING_PATH}",
        f"  FROM {left_source} l",
        f"  INNER JOIN {right_source} r",
        f"    ON {on_clause}",
    ]

    # Bucket size limit: filter out oversized buckets to prevent cartesian explosion
    if path.bucket_size_limit > 0:
        # Build the partition key from all blocking keys
        bucket_keys = list(path.keys) + list(path.lsh_keys)
        if bucket_keys:
            partition_cols = ", ".join(f"l.{k}" for k in bucket_keys)
            lines.append(f"  QUALIFY COUNT(*) OVER (PARTITION BY {partition_cols})")
            lines.append(f"    <= {path.bucket_size_limit}")

    if path.candidate_limit > 0:
        qualify_keyword = "  AND" if path.bucket_size_limit > 0 else "  QUALIFY"
        lines.append(f"{qualify_keyword} ROW_NUMBER() OVER (")
        lines.append("    PARTITION BY l.entity_uid")
        lines.append("    ORDER BY r.entity_uid")
        lines.append(f"  ) <= {path.candidate_limit}")

    lines.append(")")

    return "\n".join(lines)


def build_blocking_sql(params: BlockingParams) -> SQLExpression:
    """Build multi-path blocking SQL.

    Generates candidate pairs from multiple blocking paths with
    deduplication and optional prior-tier exclusion.
    """
    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{params.target_table}`")
    if params.partition_by:
        parts.append(f"PARTITION BY {params.partition_by}")
    if params.cluster_by:
        parts.append(f"CLUSTER BY {', '.join(params.cluster_by)}")
    parts.append("AS")
    parts.append("")
    parts.append("WITH")

    # LSH pre-join for source
    if params.lsh_table:
        parts.append("source_with_lsh AS (")
        parts.append("  SELECT")
        parts.append("    s.*,")
        parts.append(f"    lsh.* EXCEPT({ENTITY_UID})")
        parts.append(f"  FROM `{params.source_table}` s")
        parts.append(f"  LEFT JOIN `{params.lsh_table}` lsh USING ({ENTITY_UID})")
        parts.append("),")

    # LSH pre-join for canonical (cross-batch only)
    if params.cross_batch and params.lsh_table and params.canonical_table:
        parts.append("canonical_with_lsh AS (")
        parts.append("  SELECT")
        parts.append("    c.*,")
        parts.append(f"    lsh.* EXCEPT({ENTITY_UID})")
        parts.append(f"  FROM `{params.canonical_table}` c")
        parts.append(f"  LEFT JOIN `{params.lsh_table}` lsh USING ({ENTITY_UID})")
        parts.append("),")

    # Intra-batch path CTEs
    for path in params.blocking_paths:
        cte = _build_path_cte(
            path=path,
            tier_name=params.tier_name,
            source_table=params.source_table,
            is_cross_batch=False,
            canonical_table=None,
            lsh_table=params.lsh_table,
            link_type=params.link_type,
        )
        parts.append(f"{cte},")

    # Cross-batch path CTEs
    if params.cross_batch and params.canonical_table:
        for path in params.blocking_paths:
            cte = _build_path_cte(
                path=path,
                tier_name=params.tier_name,
                source_table=params.source_table,
                is_cross_batch=True,
                canonical_table=params.canonical_table,
                lsh_table=params.lsh_table,
                link_type=params.link_type,
            )
            parts.append(f"{cte},")

    # Union all paths
    parts.append("all_candidates AS (")
    union_parts: list[str] = []
    for path in params.blocking_paths:
        union_parts.append(
            f"  SELECT {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}, {BLOCKING_PATH} "
            f"FROM intra_path_{path.index}"
        )
    if params.cross_batch and params.canonical_table:
        for path in params.blocking_paths:
            union_parts.append(
                f"  SELECT {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}, {BLOCKING_PATH} "
                f"FROM cross_path_{path.index}"
            )

    if not union_parts:
        raise ValueError(
            f"No blocking paths defined for tier '{params.tier_name}'. "
            f"Each tier must have at least one blocking path."
        )
    else:
        parts.append("\n  UNION ALL\n".join(union_parts))

    parts.append("),")

    # Deduplicate — removes duplicate pairs across blocking paths.
    # PERF: DISTINCT on two INT64 columns (left_entity_uid, right_entity_uid)
    # is very efficient — BQ hashes 16 bytes per row. This is much faster
    # than deduplicating on STRING pairs would be.
    parts.append("deduplicated AS (")
    parts.append("  SELECT DISTINCT")
    parts.append(f"    {LEFT_ENTITY_UID},")
    parts.append(f"    {RIGHT_ENTITY_UID}")
    parts.append("  FROM all_candidates")
    parts.append(f"  WHERE {LEFT_ENTITY_UID} IS NOT NULL")
    parts.append(")")
    parts.append("")

    # Final select with optional exclusion
    parts.append(f"SELECT d.{LEFT_ENTITY_UID}, d.{RIGHT_ENTITY_UID}")
    parts.append("FROM deduplicated d")

    if params.excluded_pairs_table:
        parts.append(f"LEFT JOIN `{params.excluded_pairs_table}` e")
        parts.append(
            f"  ON (d.{LEFT_ENTITY_UID} = e.{LEFT_ENTITY_UID}"
            f" AND d.{RIGHT_ENTITY_UID} = e.{RIGHT_ENTITY_UID})"
        )
        parts.append(
            f"  OR (d.{LEFT_ENTITY_UID} = e.{RIGHT_ENTITY_UID}"
            f" AND d.{RIGHT_ENTITY_UID} = e.{LEFT_ENTITY_UID})"
        )
        parts.append(f"WHERE e.{LEFT_ENTITY_UID} IS NULL")

    return SQLExpression.from_raw("\n".join(parts))


# ---------------------------------------------------------------------------
# Blocking metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockingMetricsParams:
    """Parameters for blocking evaluation metrics."""
    candidates_table: str
    matches_table: str
    source_table: str
    tier_name: str

    def __post_init__(self) -> None:
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.matches_table)
        validate_table_ref(self.source_table)


def build_blocking_metrics_sql(params: BlockingMetricsParams) -> SQLExpression:
    """Build SQL to compute blocking evaluation metrics.

    Measures how well blocking reduces the comparison space
    while retaining true matches.
    """
    src = params.source_table
    cand = params.candidates_table
    match = params.matches_table
    escaped_tier = sql_escape(params.tier_name)
    sql = (
        f"SELECT\n"
        f"  '{escaped_tier}' AS {BLOCKING_METRIC_TIER_NAME},\n"
        f"  (SELECT COUNT(*) FROM `{src}`)"
        f" AS {BLOCKING_METRIC_TOTAL_RECORDS},\n"
        f"  (SELECT COUNT(*) FROM `{cand}`)"
        f" AS {BLOCKING_METRIC_CANDIDATE_PAIRS},\n"
        f"  (SELECT COUNT(*) FROM `{match}`)"
        f" AS {BLOCKING_METRIC_MATCHED_PAIRS},\n"
        f"  SAFE_DIVIDE(\n"
        f"    (SELECT COUNT(*) FROM `{match}`),\n"
        f"    (SELECT COUNT(*) FROM `{cand}`)\n"
        f"  ) AS {BLOCKING_METRIC_PRECISION},\n"
        f"  SAFE_DIVIDE(\n"
        f"    (SELECT COUNT(*) FROM `{cand}`),\n"
        f"    (SELECT COUNT(*) FROM `{src}`) "
        f"* ((SELECT COUNT(*) FROM `{src}`) - 1) / 2.0\n"
        f"  ) AS {BLOCKING_METRIC_REDUCTION_RATIO},\n"
        f"  CURRENT_TIMESTAMP() AS {BLOCKING_METRIC_COMPUTED_AT}"
    )
    return SQLExpression.from_raw(sql)

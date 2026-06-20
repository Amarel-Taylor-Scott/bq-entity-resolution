"""SQL builders for cluster quality metrics and confidence shaping.

Generates SQL for:
1. Cluster quality metrics (singleton ratio, max size, confidence stats)
2. Post-clustering confidence adjustments (group-size penalty, hub detection)
"""

from __future__ import annotations

from dataclasses import dataclass

from bq_entity_resolution.columns import (
    CLUSTER_ID,
    CLUSTER_METRIC_AVG_CONFIDENCE,
    CLUSTER_METRIC_AVG_SIZE,
    CLUSTER_METRIC_AVG_SOURCE_DIVERSITY,
    CLUSTER_METRIC_COMPUTED_AT,
    CLUSTER_METRIC_COUNT,
    CLUSTER_METRIC_MAX_SIZE,
    CLUSTER_METRIC_MEDIAN_SIZE,
    CLUSTER_METRIC_MIN_CONFIDENCE,
    CLUSTER_METRIC_SINGLETON_COUNT,
    CLUSTER_METRIC_SINGLETON_RATIO,
    ENTITY_UID,
    IS_HUB_NODE,
    LEFT_ENTITY_UID,
    MATCH_CONFIDENCE,
    RIGHT_ENTITY_UID,
    SOURCE_NAME,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_table_ref


@dataclass(frozen=True)
class ClusterMetricsParams:
    """Parameters for cluster quality metrics SQL generation."""
    cluster_table: str
    matches_table: str
    source_table: str = ""  # Featured table with source_name column

    def __post_init__(self) -> None:
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.matches_table)
        if self.source_table:
            validate_table_ref(self.source_table)



def build_cluster_quality_metrics_sql(
    params: ClusterMetricsParams,
) -> SQLExpression:
    """Build cluster quality metrics SQL.

    Computes cluster health statistics for monitoring.
    """
    lines: list[str] = []

    # Join cluster table with source table for source_name if available
    if params.source_table:
        lines.append("WITH cluster_stats AS (")
        lines.append("  SELECT")
        lines.append(f"    c.{CLUSTER_ID},")
        lines.append("    COUNT(*) AS cluster_size,")
        lines.append(f"    COUNT(DISTINCT s.{SOURCE_NAME}) AS source_count")
        lines.append(f"  FROM `{params.cluster_table}` c")
        lines.append(f"  LEFT JOIN `{params.source_table}` s")
        lines.append(f"    ON c.{ENTITY_UID} = s.{ENTITY_UID}")
        lines.append(f"  GROUP BY c.{CLUSTER_ID}")
        lines.append("),")
    else:
        lines.append("WITH cluster_stats AS (")
        lines.append("  SELECT")
        lines.append(f"    {CLUSTER_ID},")
        lines.append("    COUNT(*) AS cluster_size,")
        lines.append("    1 AS source_count")
        lines.append(f"  FROM `{params.cluster_table}`")
        lines.append(f"  GROUP BY {CLUSTER_ID}")
        lines.append("),")

    lines.append("confidence_stats AS (")
    lines.append("  SELECT")
    lines.append(f"    AVG({MATCH_CONFIDENCE}) AS {CLUSTER_METRIC_AVG_CONFIDENCE},")
    lines.append(f"    MIN({MATCH_CONFIDENCE}) AS {CLUSTER_METRIC_MIN_CONFIDENCE}")
    lines.append(f"  FROM `{params.matches_table}`")
    lines.append(")")
    lines.append("SELECT")
    lines.append(f"  COUNT(*) AS {CLUSTER_METRIC_COUNT},")
    lines.append(
        f"  SUM(CASE WHEN cluster_size = 1 THEN 1 ELSE 0 END) AS {CLUSTER_METRIC_SINGLETON_COUNT},"
    )
    lines.append("  SAFE_DIVIDE(")
    lines.append(
        "    SUM(CASE WHEN cluster_size = 1 THEN 1 ELSE 0 END),"
    )
    lines.append("    COUNT(*)")
    lines.append(f"  ) AS {CLUSTER_METRIC_SINGLETON_RATIO},")
    lines.append(f"  MAX(cluster_size) AS {CLUSTER_METRIC_MAX_SIZE},")
    lines.append(f"  AVG(cluster_size) AS {CLUSTER_METRIC_AVG_SIZE},")
    lines.append(
        f"  APPROX_QUANTILES(cluster_size, 2)[OFFSET(1)] AS {CLUSTER_METRIC_MEDIAN_SIZE},"
    )
    lines.append(f"  AVG(source_count) AS {CLUSTER_METRIC_AVG_SOURCE_DIVERSITY},")
    lines.append(f"  cs.{CLUSTER_METRIC_AVG_CONFIDENCE},")
    lines.append(f"  cs.{CLUSTER_METRIC_MIN_CONFIDENCE},")
    lines.append(f"  CURRENT_TIMESTAMP() AS {CLUSTER_METRIC_COMPUTED_AT}")
    lines.append("FROM cluster_stats")
    lines.append("CROSS JOIN confidence_stats cs")
    lines.append(
        f"GROUP BY cs.{CLUSTER_METRIC_AVG_CONFIDENCE}, cs.{CLUSTER_METRIC_MIN_CONFIDENCE}"
    )

    return SQLExpression.from_raw("\n".join(lines))


@dataclass(frozen=True)
class ConfidenceShapingParams:
    """Parameters for post-clustering confidence shaping."""
    cluster_table: str
    matches_table: str
    group_size_penalty: bool = False
    group_size_threshold: int = 10
    group_size_penalty_rate: float = 0.02
    hub_node_detection: bool = False
    hub_degree_threshold: int = 20

    def __post_init__(self) -> None:
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.matches_table)


def build_confidence_shaping_sql(
    params: ConfidenceShapingParams,
) -> SQLExpression:
    """Build SQL to apply post-clustering confidence adjustments.

    Adjusts match_confidence based on cluster characteristics:
    - Group-size penalty: large clusters get penalized confidence.
    - Hub node detection: flags entities with too many connections.
    """
    lines: list[str] = []

    # CTE: cluster sizes
    lines.append("WITH cluster_sizes AS (")
    lines.append("  SELECT")
    lines.append(f"    {CLUSTER_ID},")
    lines.append("    COUNT(*) AS cluster_size")
    lines.append(f"  FROM `{params.cluster_table}`")
    lines.append(f"  GROUP BY {CLUSTER_ID}")
    lines.append("),")

    # CTE: node degrees (for hub detection)
    if params.hub_node_detection:
        lines.append("node_degrees AS (")
        lines.append("  SELECT")
        lines.append(f"    {ENTITY_UID},")
        lines.append("    COUNT(*) AS degree")
        lines.append("  FROM (")
        lines.append(
            f"    SELECT {LEFT_ENTITY_UID} AS {ENTITY_UID} "
            f"FROM `{params.matches_table}`"
        )
        lines.append("    UNION ALL")
        lines.append(
            f"    SELECT {RIGHT_ENTITY_UID} AS {ENTITY_UID} "
            f"FROM `{params.matches_table}`"
        )
        lines.append("  )")
        lines.append(f"  GROUP BY {ENTITY_UID}")
        lines.append("),")

    # CTE: adjusted confidence per match pair.
    # Uses EXCEPT to drop the original match_confidence so it can be
    # replaced by the adjusted value, ensuring downstream consumers
    # always read the shaped confidence.
    lines.append("adjusted AS (")
    lines.append("  SELECT")
    lines.append(f"    m.* EXCEPT({MATCH_CONFIDENCE}),")

    if params.group_size_penalty:
        lines.append(
            f"    CASE WHEN cs.cluster_size > {params.group_size_threshold} "
            f"THEN m.{MATCH_CONFIDENCE} * GREATEST(0.5, "
            f"1.0 - (cs.cluster_size - {params.group_size_threshold}) "
            f"* {params.group_size_penalty_rate}) "
            f"ELSE m.{MATCH_CONFIDENCE} END "
            f"AS {MATCH_CONFIDENCE},"
        )
    else:
        lines.append(f"    m.{MATCH_CONFIDENCE},")

    lines.append(
        f"    m.{MATCH_CONFIDENCE} AS original_confidence,"
    )

    if params.hub_node_detection:
        lines.append(
            f"    CASE WHEN COALESCE(nd_l.degree, 0) > {params.hub_degree_threshold} "
            f"OR COALESCE(nd_r.degree, 0) > {params.hub_degree_threshold} "
            f"THEN TRUE ELSE FALSE END AS {IS_HUB_NODE}"
        )
    else:
        lines.append(f"    FALSE AS {IS_HUB_NODE}")

    lines.append(f"  FROM `{params.matches_table}` m")
    lines.append(
        f"  JOIN `{params.cluster_table}` cl_l "
        f"ON m.{LEFT_ENTITY_UID} = cl_l.{ENTITY_UID}"
    )
    lines.append(
        f"  JOIN `{params.cluster_table}` cl_r "
        f"ON m.{RIGHT_ENTITY_UID} = cl_r.{ENTITY_UID}"
    )
    lines.append(
        f"  JOIN cluster_sizes cs ON cs.{CLUSTER_ID} = "
        f"LEAST(cl_l.{CLUSTER_ID}, cl_r.{CLUSTER_ID})"
    )

    if params.hub_node_detection:
        lines.append(
            f"  LEFT JOIN node_degrees nd_l "
            f"ON m.{LEFT_ENTITY_UID} = nd_l.{ENTITY_UID}"
        )
        lines.append(
            f"  LEFT JOIN node_degrees nd_r "
            f"ON m.{RIGHT_ENTITY_UID} = nd_r.{ENTITY_UID}"
        )

    lines.append(")")

    # Replace matches table with adjusted confidence written back
    # to the match_confidence column so downstream consumers
    # (gold output, cluster quality, etc.) automatically use shaped values.
    lines.append(f"CREATE OR REPLACE TABLE `{params.matches_table}` AS")
    lines.append("SELECT * FROM adjusted;")

    return SQLExpression.from_raw("\n".join(lines))


@dataclass(frozen=True)
class ClusterStabilityParams:
    """Parameters for cluster stability comparison."""
    current_cluster_table: str
    prior_canonical_table: str
    output_table: str

    def __post_init__(self) -> None:
        validate_table_ref(self.current_cluster_table)
        validate_table_ref(self.prior_canonical_table)
        validate_table_ref(self.output_table)


def build_cluster_stability_sql(params: ClusterStabilityParams) -> SQLExpression:
    """Build SQL to detect cluster splits/merges between runs.

    Compares current clustering with prior canonical index to find:
    - Entities that changed cluster_id (re-clustered)
    - New entities (not in prior index)
    - Cluster merges (two prior clusters now merged into one)
    """
    sql = (
        f"CREATE OR REPLACE TABLE `{params.output_table}` AS\n"
        f"SELECT\n"
        f"  COALESCE(c.{ENTITY_UID}, p.{ENTITY_UID}) AS {ENTITY_UID},\n"
        f"  p.{CLUSTER_ID} AS prior_cluster_id,\n"
        f"  c.{CLUSTER_ID} AS current_cluster_id,\n"
        f"  CASE\n"
        f"    WHEN p.{ENTITY_UID} IS NULL THEN 'new_entity'\n"
        f"    WHEN p.{CLUSTER_ID} != c.{CLUSTER_ID} THEN 'reassigned'\n"
        f"    ELSE 'stable'\n"
        f"  END AS change_type,\n"
        f"  CURRENT_TIMESTAMP() AS detected_at\n"
        f"FROM `{params.current_cluster_table}` c\n"
        f"FULL OUTER JOIN `{params.prior_canonical_table}` p\n"
        f"  USING ({ENTITY_UID})\n"
        f"WHERE p.{ENTITY_UID} IS NULL\n"
        f"   OR p.{CLUSTER_ID} != c.{CLUSTER_ID};"
    )
    return SQLExpression.from_raw(sql)


__all__ = [
    "ClusterMetricsParams",
    "ClusterStabilityParams",
    "ConfidenceShapingParams",
    "build_cluster_quality_metrics_sql",
    "build_cluster_stability_sql",
    "build_confidence_shaping_sql",
]

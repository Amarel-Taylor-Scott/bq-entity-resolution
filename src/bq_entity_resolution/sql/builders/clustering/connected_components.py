"""SQL builder for connected components clustering.

Generates SQL for iterative minimum-cluster-id propagation to find
connected components in the match graph.

Clustering Performance Notes
=============================
Connected components runs iteratively until convergence. Each iteration:
  1. JOINs cluster_table x all_matches on entity_uid (INT64) - fast
  2. Computes MIN(cluster_id) for each entity via GROUP BY - INT64 agg
  3. Replaces cluster_table with updated assignments

All columns involved are INT64:
  - entity_uid: INT64 (FARM_FINGERPRINT from staging)
  - cluster_id: INT64 (initialized to entity_uid, propagated via MIN)
  - left_entity_uid / right_entity_uid: INT64

This means ALL JOINs and aggregations in the clustering loop operate on
fixed-width 8-byte integers - the optimal case for BigQuery's columnar
storage engine. No STRING comparisons occur during clustering.

The OR in the LEFT JOIN (ON uid = uid1 OR uid = uid2) may prevent BQ from
using a pure hash-join. For very large match tables (>100M edges), consider
normalizing edges into a symmetric edge list (uid1->uid2 UNION uid2->uid1)
to enable two separate equi-joins instead of one OR-join.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    CLUSTER_CID1,
    CLUSTER_CID2,
    CLUSTER_ID,
    CLUSTER_MIN_NEIGHBOR,
    CLUSTER_UID1,
    CLUSTER_UID2,
    ENTITY_UID,
    LEFT_ENTITY_UID,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_table_ref


@dataclass(frozen=True)
class ClusteringParams:
    """Parameters for cluster assignment SQL generation."""
    all_matches_table: str
    cluster_table: str
    source_table: str
    max_iterations: int = 20
    cluster_by: list[str] = field(default_factory=lambda: ["entity_uid"])

    def __post_init__(self) -> None:
        validate_table_ref(self.all_matches_table)
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.source_table)


@dataclass(frozen=True)
class ClusterMetricsParams:
    """Parameters for cluster quality metrics SQL generation."""
    cluster_table: str
    matches_table: str
    source_table: str = ""  # Featured table with source_name column


def build_cluster_assignment_sql(params: ClusteringParams) -> SQLExpression:
    """Build connected components cluster assignment SQL.

    Uses BigQuery scripting (DECLARE/WHILE) to iteratively propagate
    minimum cluster_id through match edges until convergence.

    Note: This uses BQ scripting which is dialect-specific. For DuckDB,
    the iteration loop must be handled in Python.
    """
    lines: list[str] = []

    # Variable declarations
    lines.append("DECLARE iteration INT64 DEFAULT 0;")
    lines.append("DECLARE rows_updated INT64 DEFAULT 1;")
    lines.append("")

    # Step 1: Initialize ALL entities as their own cluster (singletons).
    # PERF: entity_uid is INT64, so cluster_id starts as INT64. All subsequent
    # MIN/LEAST operations stay in INT64 space — no type conversions needed.
    lines.append(
        f"CREATE OR REPLACE TABLE `{params.cluster_table}` AS"
    )
    lines.append(f"SELECT DISTINCT {ENTITY_UID}, {ENTITY_UID} AS {CLUSTER_ID}")
    lines.append(f"FROM `{params.source_table}`;")
    lines.append("")

    # Step 2: Iterative propagation loop
    lines.append(
        f"WHILE rows_updated > 0 AND iteration < {params.max_iterations} DO"
    )
    lines.append("")

    # Build edge list with current cluster assignments
    lines.append("  CREATE OR REPLACE TEMP TABLE _edge_clusters AS")
    lines.append("  SELECT")
    lines.append(f"    c1.{ENTITY_UID} AS {CLUSTER_UID1},")
    lines.append(f"    c1.{CLUSTER_ID} AS {CLUSTER_CID1},")
    lines.append(f"    c2.{ENTITY_UID} AS {CLUSTER_UID2},")
    lines.append(f"    c2.{CLUSTER_ID} AS {CLUSTER_CID2}")
    lines.append(f"  FROM `{params.all_matches_table}` m")
    lines.append(
        f"  JOIN `{params.cluster_table}` c1 ON m.{LEFT_ENTITY_UID} = c1.{ENTITY_UID}"
    )
    lines.append(
        f"  JOIN `{params.cluster_table}` c2 ON m.{RIGHT_ENTITY_UID} = c2.{ENTITY_UID};"
    )
    lines.append("")

    # Compute new cluster_id = minimum reachable cluster_id
    lines.append("  CREATE OR REPLACE TEMP TABLE _new_clusters AS")
    lines.append("  SELECT")
    lines.append(f"    {ENTITY_UID},")
    lines.append("    LEAST(")
    lines.append(f"      {CLUSTER_ID},")
    lines.append(f"      COALESCE({CLUSTER_MIN_NEIGHBOR}, {CLUSTER_ID})")
    lines.append(f"    ) AS {CLUSTER_ID}")
    lines.append("  FROM (")
    lines.append("    SELECT")
    lines.append(f"      c.{ENTITY_UID},")
    lines.append(f"      c.{CLUSTER_ID},")
    lines.append("      MIN(")
    lines.append("        LEAST(")
    lines.append(f"          COALESCE(e.{CLUSTER_CID1}, c.{CLUSTER_ID}),")
    lines.append(f"          COALESCE(e.{CLUSTER_CID2}, c.{CLUSTER_ID})")
    lines.append("        )")
    lines.append(f"      ) AS {CLUSTER_MIN_NEIGHBOR}")
    lines.append(f"    FROM `{params.cluster_table}` c")
    lines.append("    LEFT JOIN _edge_clusters e")
    lines.append(f"      ON c.{ENTITY_UID} = e.{CLUSTER_UID1} OR c.{ENTITY_UID} = e.{CLUSTER_UID2}")
    lines.append(f"    GROUP BY c.{ENTITY_UID}, c.{CLUSTER_ID}")
    lines.append("  );")
    lines.append("")

    # Count how many changed
    lines.append("  SET rows_updated = (")
    lines.append("    SELECT COUNT(*)")
    lines.append("    FROM _new_clusters n")
    lines.append(f"    JOIN `{params.cluster_table}` o USING ({ENTITY_UID})")
    lines.append(f"    WHERE n.{CLUSTER_ID} != o.{CLUSTER_ID}")
    lines.append("  );")
    lines.append("")

    # Replace cluster table
    lines.append(f"  CREATE OR REPLACE TABLE `{params.cluster_table}` AS")
    lines.append("  SELECT * FROM _new_clusters;")
    lines.append("")
    lines.append("  SET iteration = iteration + 1;")
    lines.append("")
    lines.append("END WHILE;")

    return SQLExpression.from_raw("\n".join(lines))



__all__ = [
    "ClusteringParams",
    "build_cluster_assignment_sql",
]

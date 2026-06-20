"""SQL builder for incremental clustering and canonical index management.

Generates SQL for:
1. Incremental cluster assignment (prior entities + new singletons)
2. Canonical index initialization (CREATE TABLE IF NOT EXISTS)
3. Canonical index population (UPDATE changed + INSERT new)
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
class IncrementalClusteringParams:
    """Parameters for incremental cluster assignment."""
    all_matches_table: str
    cluster_table: str
    source_table: str
    canonical_table: str
    max_iterations: int = 20

    def __post_init__(self) -> None:
        validate_table_ref(self.all_matches_table)
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.source_table)
        validate_table_ref(self.canonical_table)


@dataclass(frozen=True)
class PopulateCanonicalIndexParams:
    """Parameters for canonical index population."""
    canonical_table: str
    source_table: str
    cluster_table: str

    def __post_init__(self) -> None:
        validate_table_ref(self.canonical_table)
        validate_table_ref(self.source_table)
        validate_table_ref(self.cluster_table)


def build_incremental_cluster_sql(
    params: IncrementalClusteringParams,
) -> SQLExpression:
    """Build incremental cluster assignment SQL.

    Initializes from prior cluster assignments (canonical_index) combined
    with new entities from the current batch as singletons, then propagates
    minimum cluster_id through ALL match edges until convergence.
    """
    lines: list[str] = []

    lines.append("DECLARE iteration INT64 DEFAULT 0;")
    lines.append("DECLARE rows_updated INT64 DEFAULT 1;")
    lines.append("")

    # Step 1: Initialize from prior entities + new singletons
    lines.append(
        f"CREATE OR REPLACE TABLE `{params.cluster_table}` AS"
    )
    lines.append(
        f"SELECT {ENTITY_UID}, {CLUSTER_ID} FROM `{params.canonical_table}`"
    )
    lines.append("UNION ALL")
    lines.append(f"SELECT DISTINCT {ENTITY_UID}, {ENTITY_UID} AS {CLUSTER_ID}")
    lines.append(f"FROM `{params.source_table}`")
    lines.append(
        f"WHERE {ENTITY_UID} NOT IN "
        f"(SELECT {ENTITY_UID} FROM `{params.canonical_table}`);"
    )
    lines.append("")

    # Step 2: Iterative propagation
    lines.append(
        f"WHILE rows_updated > 0 AND iteration < {params.max_iterations} DO"
    )
    lines.append("")

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

    lines.append("  SET rows_updated = (")
    lines.append("    SELECT COUNT(*)")
    lines.append("    FROM _new_clusters n")
    lines.append(f"    JOIN `{params.cluster_table}` o USING ({ENTITY_UID})")
    lines.append(f"    WHERE n.{CLUSTER_ID} != o.{CLUSTER_ID}")
    lines.append("  );")
    lines.append("")

    lines.append(f"  CREATE OR REPLACE TABLE `{params.cluster_table}` AS")
    lines.append("  SELECT * FROM _new_clusters;")
    lines.append("")
    lines.append("  SET iteration = iteration + 1;")
    lines.append("")
    lines.append("END WHILE;")

    return SQLExpression.from_raw("\n".join(lines))


@dataclass(frozen=True)
class CanonicalIndexInitParams:
    """Parameters for canonical index initialization."""
    canonical_table: str
    source_table: str  # Featured table (schema reference)
    cluster_by: list[str] = field(default_factory=lambda: ["entity_uid"])
    partition_by: str | None = None

    def __post_init__(self) -> None:
        validate_table_ref(self.canonical_table)
        validate_table_ref(self.source_table)


def build_canonical_index_init_sql(
    params: CanonicalIndexInitParams,
) -> SQLExpression:
    """Build SQL to create canonical_index table if it doesn't exist.

    Creates an empty table with the same schema as the featured table
    plus a cluster_id column. Uses CREATE TABLE IF NOT EXISTS so it's
    safe to call on every run — only creates on the first execution.
    """
    lines: list[str] = []
    lines.append(
        f"CREATE TABLE IF NOT EXISTS `{params.canonical_table}`"
    )
    if params.partition_by:
        lines.append(f"PARTITION BY {params.partition_by}")
    if params.cluster_by:
        lines.append(f"CLUSTER BY {', '.join(params.cluster_by)}")
    lines.append("AS")
    lines.append(f"SELECT *, {ENTITY_UID} AS {CLUSTER_ID}")
    lines.append(f"FROM `{params.source_table}`")
    lines.append("WHERE FALSE;")

    return SQLExpression.from_raw("\n".join(lines))


def build_populate_canonical_index_sql(
    params: PopulateCanonicalIndexParams,
) -> SQLExpression:
    """Build SQL to upsert current batch entities into canonical_index.

    Uses MERGE for atomicity — a crash between UPDATE and INSERT in the
    old pattern could lose new entities.
    """
    sql = (
        f"-- Atomic upsert: update existing + insert new in one MERGE\n"
        f"MERGE INTO `{params.canonical_table}` ci\n"
        f"USING (\n"
        f"  SELECT f.*, cl.{CLUSTER_ID}\n"
        f"  FROM `{params.source_table}` f\n"
        f"  JOIN `{params.cluster_table}` cl USING ({ENTITY_UID})\n"
        f") src\n"
        f"ON ci.{ENTITY_UID} = src.{ENTITY_UID}\n"
        f"WHEN MATCHED AND ci.{CLUSTER_ID} != src.{CLUSTER_ID} THEN\n"
        f"  UPDATE SET {CLUSTER_ID} = src.{CLUSTER_ID}\n"
        f"WHEN NOT MATCHED THEN\n"
        f"  INSERT ROW;"
    )
    return SQLExpression.from_raw(sql)



__all__ = [
    "CanonicalIndexInitParams",
    "IncrementalClusteringParams",
    "PopulateCanonicalIndexParams",
    "build_canonical_index_init_sql",
    "build_incremental_cluster_sql",
    "build_populate_canonical_index_sql",
]

"""SQL builders for alternative clustering strategies.

Provides non-iterative clustering algorithms as alternatives to
connected components:
1. Star clustering - single-pass hub-based clustering
2. Best-match clustering - single-pass 1:1 matching
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    CLUSTER_ID,
    ENTITY_UID,
    LEFT_ENTITY_UID,
    MATCH_CONFIDENCE,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_table_ref


@dataclass(frozen=True)
class StarClusteringParams:
    """Parameters for star clustering SQL generation.

    Star clustering: for each connected component, the node with the
    highest aggregate match score becomes the "center". All neighbors
    join the center's cluster. Faster than connected components but
    may split large clusters.
    """
    all_matches_table: str
    cluster_table: str
    source_table: str
    min_confidence: float = 0.0
    cluster_by: list[str] = field(default_factory=lambda: ["entity_uid"])

    def __post_init__(self) -> None:
        validate_table_ref(self.all_matches_table)
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.source_table)


def build_star_cluster_sql(params: StarClusteringParams) -> SQLExpression:
    """Build star clustering SQL.

    Algorithm:
    1. Initialize all entities as singletons.
    2. For each entity, compute aggregate match score (sum of confidences).
    3. For each match pair, the entity with the lower aggregate score
       adopts the cluster_id of the entity with the higher score.
    4. Single pass — no iteration needed (O(E) where E = number of edges).

    Trade-offs vs connected components:
    - Faster: single pass vs iterative convergence.
    - May produce more clusters: doesn't propagate through long chains.
    - Better for high-confidence matching where clusters are small.
    """
    lines: list[str] = []

    # Step 1: Compute node scores (aggregate match confidence)
    lines.append("WITH node_scores AS (")
    lines.append("  SELECT")
    lines.append(f"    {ENTITY_UID},")
    lines.append(f"    SUM({MATCH_CONFIDENCE}) AS total_score")
    lines.append("  FROM (")
    lines.append(f"    SELECT {LEFT_ENTITY_UID} AS {ENTITY_UID}, "
                 f"{MATCH_CONFIDENCE} FROM `{params.all_matches_table}`")
    if params.min_confidence > 0:
        lines.append(f"    WHERE {MATCH_CONFIDENCE} >= {params.min_confidence}")
    lines.append("    UNION ALL")
    lines.append(f"    SELECT {RIGHT_ENTITY_UID} AS {ENTITY_UID}, "
                 f"{MATCH_CONFIDENCE} FROM `{params.all_matches_table}`")
    if params.min_confidence > 0:
        lines.append(f"    WHERE {MATCH_CONFIDENCE} >= {params.min_confidence}")
    lines.append("  )")
    lines.append(f"  GROUP BY {ENTITY_UID}")
    lines.append("),")

    # Step 2: For each edge, determine the "star center" (higher score wins)
    lines.append("directed_edges AS (")
    lines.append("  SELECT")
    lines.append(f"    m.{LEFT_ENTITY_UID},")
    lines.append(f"    m.{RIGHT_ENTITY_UID},")
    lines.append("    CASE")
    lines.append("      WHEN COALESCE(ls.total_score, 0) >= COALESCE(rs.total_score, 0)")
    lines.append(f"      THEN m.{LEFT_ENTITY_UID}")
    lines.append(f"      ELSE m.{RIGHT_ENTITY_UID}")
    lines.append("    END AS center_uid")
    lines.append(f"  FROM `{params.all_matches_table}` m")
    lines.append(f"  LEFT JOIN node_scores ls ON m.{LEFT_ENTITY_UID} = ls.{ENTITY_UID}")
    lines.append(f"  LEFT JOIN node_scores rs ON m.{RIGHT_ENTITY_UID} = rs.{ENTITY_UID}")
    if params.min_confidence > 0:
        lines.append(f"  WHERE m.{MATCH_CONFIDENCE} >= {params.min_confidence}")
    lines.append("),")

    # Step 3: Each entity adopts the cluster_id of its best center
    lines.append("best_center AS (")
    lines.append("  SELECT")
    lines.append(f"    {ENTITY_UID},")
    lines.append(f"    MIN(center_uid) AS {CLUSTER_ID}")
    lines.append("  FROM (")
    lines.append(f"    SELECT {LEFT_ENTITY_UID} AS {ENTITY_UID}, center_uid "
                 "FROM directed_edges")
    lines.append("    UNION ALL")
    lines.append(f"    SELECT {RIGHT_ENTITY_UID} AS {ENTITY_UID}, center_uid "
                 "FROM directed_edges")
    lines.append("  )")
    lines.append(f"  GROUP BY {ENTITY_UID}")
    lines.append(")")
    lines.append("")

    # Step 4: Build final cluster table (all entities including singletons)
    lines.append(f"CREATE OR REPLACE TABLE `{params.cluster_table}` AS")
    lines.append("SELECT")
    lines.append(f"  s.{ENTITY_UID},")
    lines.append(f"  COALESCE(bc.{CLUSTER_ID}, s.{ENTITY_UID}) AS {CLUSTER_ID}")
    lines.append(f"FROM `{params.source_table}` s")
    lines.append(f"LEFT JOIN best_center bc ON s.{ENTITY_UID} = bc.{ENTITY_UID};")

    return SQLExpression.from_raw("\n".join(lines))


@dataclass(frozen=True)
class BestMatchClusteringParams:
    """Parameters for best-match clustering SQL generation.

    Best-match clustering: each entity joins the cluster of its single
    highest-scoring match. Produces 1:1 mappings — no entity belongs
    to more than one cluster center.
    """
    all_matches_table: str
    cluster_table: str
    source_table: str
    min_confidence: float = 0.0
    cluster_by: list[str] = field(default_factory=lambda: ["entity_uid"])

    def __post_init__(self) -> None:
        validate_table_ref(self.all_matches_table)
        validate_table_ref(self.cluster_table)
        validate_table_ref(self.source_table)


def build_best_match_cluster_sql(
    params: BestMatchClusteringParams,
) -> SQLExpression:
    """Build best-match clustering SQL.

    Algorithm:
    1. For each entity, find its single best match (highest confidence).
    2. If A's best match is B and B's best match is A, they form a pair cluster.
    3. Otherwise, the entity with the higher best-match score becomes the center.
    4. Single pass — deterministic, no iteration needed.

    Trade-offs vs connected components:
    - Produces smaller clusters (max size 2 for pure best-match).
    - No transitivity: A-B match + B-C match does NOT merge A and C.
    - Ideal for 1:1 linking (record linkage, not deduplication).
    """
    lines: list[str] = []

    # Step 1: Find best match per entity (highest confidence)
    lines.append("WITH best_matches AS (")
    lines.append("  SELECT * FROM (")
    lines.append("    SELECT")
    lines.append(f"      {ENTITY_UID},")
    lines.append("      best_match_uid,")
    lines.append(f"      {MATCH_CONFIDENCE},")
    lines.append(f"      ROW_NUMBER() OVER (PARTITION BY {ENTITY_UID} "
                 f"ORDER BY {MATCH_CONFIDENCE} DESC) AS rn")
    lines.append("    FROM (")
    lines.append(f"      SELECT {LEFT_ENTITY_UID} AS {ENTITY_UID}, "
                 f"{RIGHT_ENTITY_UID} AS best_match_uid, "
                 f"{MATCH_CONFIDENCE}")
    lines.append(f"      FROM `{params.all_matches_table}`")
    if params.min_confidence > 0:
        lines.append(f"      WHERE {MATCH_CONFIDENCE} >= {params.min_confidence}")
    lines.append("      UNION ALL")
    lines.append(f"      SELECT {RIGHT_ENTITY_UID} AS {ENTITY_UID}, "
                 f"{LEFT_ENTITY_UID} AS best_match_uid, "
                 f"{MATCH_CONFIDENCE}")
    lines.append(f"      FROM `{params.all_matches_table}`")
    if params.min_confidence > 0:
        lines.append(f"      WHERE {MATCH_CONFIDENCE} >= {params.min_confidence}")
    lines.append("    )")
    lines.append("  ) WHERE rn = 1")
    lines.append("),")

    # Step 2: Assign cluster = MIN(self, best_match) for deterministic clustering
    lines.append("cluster_assignments AS (")
    lines.append("  SELECT")
    lines.append(f"    {ENTITY_UID},")
    lines.append(f"    LEAST({ENTITY_UID}, best_match_uid) AS {CLUSTER_ID}")
    lines.append("  FROM best_matches")
    lines.append(")")

    # Step 3: Build final cluster table (all entities including singletons)
    lines.append(f"CREATE OR REPLACE TABLE `{params.cluster_table}` AS")
    lines.append("SELECT")
    lines.append(f"  s.{ENTITY_UID},")
    lines.append(f"  COALESCE(ca.{CLUSTER_ID}, s.{ENTITY_UID}) AS {CLUSTER_ID}")
    lines.append(f"FROM `{params.source_table}` s")
    lines.append(f"LEFT JOIN cluster_assignments ca ON s.{ENTITY_UID} = ca.{ENTITY_UID};")

    return SQLExpression.from_raw("\n".join(lines))


__all__ = [
    "BestMatchClusteringParams",
    "StarClusteringParams",
    "build_best_match_cluster_sql",
    "build_star_cluster_sql",
]

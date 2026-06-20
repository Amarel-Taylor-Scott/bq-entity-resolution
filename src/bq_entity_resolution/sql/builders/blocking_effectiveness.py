"""SQL builder for blocking effectiveness dashboard.

Generates a cross-tier summary of blocking performance including
reduction ratios, bucket size distributions, and candidate pair counts.
Complements the per-tier BlockingMetricsParams in blocking.py with
a unified cross-tier overview.
"""

from __future__ import annotations

from dataclasses import dataclass

from bq_entity_resolution.columns import (
    BLOCKING_METRIC_CANDIDATE_PAIRS,
    BLOCKING_METRIC_COMPUTED_AT,
    BLOCKING_METRIC_REDUCTION_RATIO,
    BLOCKING_METRIC_TIER_NAME,
    BLOCKING_METRIC_TOTAL_RECORDS,
    LEFT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref


@dataclass(frozen=True)
class TierEffectivenessParams:
    """Effectiveness metrics inputs for a single tier."""

    tier_name: str
    candidates_table: str
    source_table: str

    def __post_init__(self) -> None:
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.source_table)


@dataclass(frozen=True)
class BlockingEffectivenessParams:
    """Parameters for blocking effectiveness dashboard SQL."""

    tier_reports: list[TierEffectivenessParams]

    def __post_init__(self) -> None:
        if not self.tier_reports:
            raise ValueError("At least one tier report is required")


def build_blocking_effectiveness_sql(
    params: BlockingEffectivenessParams,
) -> SQLExpression:
    """Build SQL for a cross-tier blocking effectiveness summary.

    For each tier, computes:
    - total_records: COUNT(*) from source table
    - candidate_pairs: COUNT(*) from candidates table
    - cartesian_baseline: n * (n-1) / 2
    - reduction_ratio: 1 - (candidate_pairs / cartesian_baseline)
    - avg_candidates_per_entity: avg candidates per left entity
    - max_candidates_per_entity: max candidates per left entity
    """
    union_parts: list[str] = []

    for tr in params.tier_reports:
        escaped_tier = sql_escape(tr.tier_name)
        part = (
            f"SELECT\n"
            f"  '{escaped_tier}' AS {BLOCKING_METRIC_TIER_NAME},\n"
            f"  (SELECT COUNT(*) FROM `{tr.source_table}`)"
            f" AS {BLOCKING_METRIC_TOTAL_RECORDS},\n"
            f"  (SELECT COUNT(*) FROM `{tr.candidates_table}`)"
            f" AS {BLOCKING_METRIC_CANDIDATE_PAIRS},\n"
            f"  (SELECT COUNT(*) FROM `{tr.source_table}`) *\n"
            f"    ((SELECT COUNT(*) FROM `{tr.source_table}`) - 1) / 2"
            f" AS cartesian_baseline,\n"
            f"  1.0 - SAFE_DIVIDE(\n"
            f"    (SELECT COUNT(*) FROM `{tr.candidates_table}`),\n"
            f"    (SELECT COUNT(*) FROM `{tr.source_table}`) *\n"
            f"      ((SELECT COUNT(*) FROM `{tr.source_table}`) - 1) / 2.0\n"
            f"  ) AS {BLOCKING_METRIC_REDUCTION_RATIO},\n"
            f"  (SELECT AVG(cnt) FROM (\n"
            f"    SELECT {LEFT_ENTITY_UID}, COUNT(*) AS cnt\n"
            f"    FROM `{tr.candidates_table}`\n"
            f"    GROUP BY {LEFT_ENTITY_UID}\n"
            f"  )) AS avg_candidates_per_entity,\n"
            f"  (SELECT MAX(cnt) FROM (\n"
            f"    SELECT {LEFT_ENTITY_UID}, COUNT(*) AS cnt\n"
            f"    FROM `{tr.candidates_table}`\n"
            f"    GROUP BY {LEFT_ENTITY_UID}\n"
            f"  )) AS max_candidates_per_entity,\n"
            f"  CURRENT_TIMESTAMP() AS {BLOCKING_METRIC_COMPUTED_AT}"
        )
        union_parts.append(part)

    sql = "\nUNION ALL\n".join(union_parts)
    return SQLExpression.from_raw(sql)

"""Per-leaf blocking/resolution metrics.

Each resolution leaf is an independent comparison unit, so its effectiveness is
worth measuring on its own: how many candidate pairs it produced and how much of
the brute-force comparison space it eliminated (reduction ratio). This mirrors
the per-tier blocking metrics but keys the rows by leaf name and accounts for the
self-join (C(n,2)) vs cross-partition (|L|·|R|) comparison space.
"""

from __future__ import annotations

from dataclasses import dataclass

from bq_entity_resolution.columns import (
    BLOCKING_METRIC_CANDIDATE_PAIRS,
    BLOCKING_METRIC_COMPUTED_AT,
    BLOCKING_METRIC_REDUCTION_RATIO,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref

__all__ = ["LeafMetricInput", "build_leaf_metrics_sql"]


@dataclass(frozen=True)
class LeafMetricInput:
    """One leaf's metric inputs."""

    leaf_name: str
    pairs_table: str
    left_table: str
    right_table: str
    is_self_join: bool

    def __post_init__(self) -> None:
        validate_table_ref(self.pairs_table)
        validate_table_ref(self.left_table)
        validate_table_ref(self.right_table)


def _leaf_select(m: LeafMetricInput) -> str:
    leaf_lit = sql_escape(m.leaf_name)
    # Comparison space: self-join → n·(n-1)/2; cross-partition → |L|·|R|.
    space = "lr * (lr - 1) / 2" if m.is_self_join else "lr * rr"
    return (
        "  SELECT\n"
        f"    '{leaf_lit}' AS leaf_name,\n"
        f"    cp AS {BLOCKING_METRIC_CANDIDATE_PAIRS},\n"
        "    lr AS left_records,\n"
        "    rr AS right_records,\n"
        f"    ({space}) AS comparison_space,\n"
        f"    CASE WHEN ({space}) > 0 THEN 1.0 - (cp * 1.0 / ({space})) "
        f"ELSE NULL END AS {BLOCKING_METRIC_REDUCTION_RATIO},\n"
        f"    CURRENT_TIMESTAMP() AS {BLOCKING_METRIC_COMPUTED_AT}\n"
        "  FROM (\n"
        f"    SELECT\n"
        f"      (SELECT COUNT(*) FROM `{m.pairs_table}`) AS cp,\n"
        f"      (SELECT COUNT(*) FROM `{m.left_table}`) AS lr,\n"
        f"      (SELECT COUNT(*) FROM `{m.right_table}`) AS rr\n"
        "  )"
    )


def build_leaf_metrics_sql(
    target: str, leaves: list[LeafMetricInput]
) -> SQLExpression:
    """One metrics row per leaf: candidate pairs, partition sizes, comparison
    space, and reduction ratio."""
    validate_table_ref(target)
    if not leaves:
        raise ValueError("build_leaf_metrics_sql requires at least one leaf")
    body = "\n  UNION ALL\n".join(_leaf_select(m) for m in leaves)
    sql = f"CREATE OR REPLACE TABLE `{target}` AS\n{body}"
    return SQLExpression.from_raw(sql)

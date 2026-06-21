"""Entity-level (consensus) aggregation of the canonical index for new×old leaves.

Design doc §6: a ``new×old`` leaf should compare a fresh record against the
canonical *entity* — the aggregated cluster — rather than against every
historical *record*. This builder collapses the canonical index to one row per
cluster, taking the **most-frequent** (consensus) value of each needed column,
using the same portable ``COUNT(*) … QUALIFY ROW_NUMBER()`` pattern as the
golden-record builder (works on BigQuery and DuckDB).

The representative row's ``entity_uid`` is the ``cluster_id`` itself (a real
entity uid — the cluster's MIN), so leaf pairs ``(new_uid, cluster_id)`` link the
new record into the existing cluster through the unchanged clustering step.
"""

from __future__ import annotations

from bq_entity_resolution.columns import CLUSTER_ID, ENTITY_UID
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref

__all__ = ["build_canonical_aggregate_sql"]


def build_canonical_aggregate_sql(
    *,
    target: str,
    source: str,
    value_columns: list[str],
    group_column: str = CLUSTER_ID,
) -> SQLExpression:
    """One consensus row per cluster from the canonical index.

    ``value_columns`` are the columns the leaf needs (blocking keys, comparison
    columns, short-circuit keys, the touched timestamp). Each is reduced to its
    most-frequent non-null value per ``group_column`` (ties broken
    deterministically by the value), and ``entity_uid`` is set to the cluster id.
    """
    validate_table_ref(target)
    validate_table_ref(source)
    validate_identifier(group_column, "aggregate group column")
    # De-dup while preserving order; never aggregate the group/uid columns.
    seen: set[str] = set()
    cols: list[str] = []
    for c in value_columns:
        validate_identifier(c, "aggregate value column")
        if c in (group_column, ENTITY_UID) or c in seen:
            continue
        seen.add(c)
        cols.append(c)

    parts: list[str] = []
    parts.append(f"CREATE OR REPLACE TABLE `{target}` AS")
    parts.append("WITH")
    parts.append(f"  ids AS (SELECT DISTINCT {group_column} FROM `{source}`),")
    for c in cols:
        parts.append(f"  vote_{c} AS (")
        parts.append(f"    SELECT {group_column}, {c} AS {c}")
        parts.append(f"    FROM `{source}`")
        parts.append(f"    WHERE {c} IS NOT NULL")
        parts.append(f"    GROUP BY {group_column}, {c}")
        parts.append("    QUALIFY ROW_NUMBER() OVER (")
        parts.append(f"      PARTITION BY {group_column} ORDER BY COUNT(*) DESC, {c}")
        parts.append("    ) = 1")
        parts.append("  ),")
    # Final projection: cluster id becomes the entity uid for graph linkage.
    parts.append("  agg AS (")
    parts.append(f"    SELECT ids.{group_column} AS {ENTITY_UID},")
    parts.append(f"      ids.{group_column} AS {group_column}" + ("," if cols else ""))
    for i, c in enumerate(cols):
        tail = "," if i < len(cols) - 1 else ""
        parts.append(f"      vote_{c}.{c} AS {c}{tail}")
    parts.append("    FROM ids")
    for c in cols:
        parts.append(f"    LEFT JOIN vote_{c} USING ({group_column})")
    parts.append("  )")
    parts.append("SELECT * FROM agg")
    return SQLExpression.from_raw("\n".join(parts))

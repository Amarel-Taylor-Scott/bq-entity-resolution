"""SQL for the per-leaf repair watermark.

Scheduled repair leaves (``old×old`` and any ``schedule != every_run`` leaf, or
any leaf with ``touched_only``) record *when* they last ran in a small meta
table. Two things read it:

- ``touched_only`` — the ``old×old`` repair restricts re-comparison to canonical
  entities changed since the last repair (``repair_watermark_floor`` is a scalar
  subquery returning that timestamp, defaulting to the epoch on first run so the
  first repair examines everything).
- cron scheduling — ``select_leaves`` can ask whether a cron firing is due since
  the recorded ``last_repair_at``.

The table lives in the meta (watermark) dataset; see
``naming.leaf_repair_watermarks_table``.
"""

from __future__ import annotations

from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref

__all__ = [
    "build_repair_watermark_ddl",
    "repair_watermark_floor",
    "build_advance_repair_watermark_sql",
]

# First-repair floor: the epoch, so ``touched_only`` examines all canonicals the
# first time a repair leaf runs. Portable typed-literal form (BigQuery + DuckDB).
_EPOCH = "TIMESTAMP '1970-01-01 00:00:00'"


def build_repair_watermark_ddl(table: str) -> SQLExpression:
    """``CREATE TABLE IF NOT EXISTS`` for the per-leaf repair watermark table."""
    validate_table_ref(table)
    sql = (
        f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
        f"  leaf_name STRING NOT NULL,\n"
        f"  last_repair_at TIMESTAMP NOT NULL,\n"
        f"  run_id STRING\n"
        f")"
    )
    return SQLExpression.from_raw(sql)


def repair_watermark_floor(table: str, leaf_name: str) -> str:
    """Scalar subquery returning a leaf's last repair time (epoch if never run).

    Suitable for inlining into a ``WHERE``/``ON`` predicate, e.g.::

        pipeline_loaded_at > (SELECT COALESCE(MAX(last_repair_at), <epoch>) ...)
    """
    validate_table_ref(table)
    leaf_lit = sql_escape(leaf_name)
    return (
        f"(SELECT COALESCE(MAX(last_repair_at), {_EPOCH}) "
        f"FROM `{table}` WHERE leaf_name = '{leaf_lit}')"
    )


def build_advance_repair_watermark_sql(
    table: str, leaf_names: list[str]
) -> SQLExpression:
    """``INSERT`` a fresh ``last_repair_at`` row for each repaired leaf.

    Append-only (mirrors the audit-trail style of the pipeline watermark table);
    ``repair_watermark_floor`` reads ``MAX(last_repair_at)`` so only the latest
    row matters.
    """
    validate_table_ref(table)
    if not leaf_names:
        raise ValueError("build_advance_repair_watermark_sql requires leaf_names")
    selects = [
        f"SELECT '{sql_escape(name)}' AS leaf_name, "
        f"CURRENT_TIMESTAMP() AS last_repair_at, "
        f"CAST(NULL AS STRING) AS run_id"
        for name in leaf_names
    ]
    body = "\n  UNION ALL\n  ".join(selects)
    sql = (
        f"INSERT INTO `{table}` (leaf_name, last_repair_at, run_id)\n"
        f"  {body}"
    )
    return SQLExpression.from_raw(sql)

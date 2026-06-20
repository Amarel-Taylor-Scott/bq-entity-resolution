"""SQL builder for monitoring and audit trail.

Replaces:
- monitoring/persist_sql_log.sql.j2
"""

from __future__ import annotations

from bq_entity_resolution.columns import (
    AUDIT_EXECUTED_AT,
    AUDIT_RUN_ID,
    AUDIT_SQL_TEXT,
    AUDIT_STAGE,
    AUDIT_STEP,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape


def build_persist_sql_log_sql(
    audit_table: str,
    run_id: str,
    entries: list[dict[str, str]],
) -> SQLExpression:
    """Build SQL to persist pipeline SQL audit trail.

    Args:
        audit_table: Fully-qualified audit table name.
        run_id: Pipeline run identifier.
        entries: List of {"stage": str, "step": str, "sql": str, "timestamp": str}.
    """
    lines: list[str] = []

    # Ensure audit table exists
    lines.append(f"CREATE TABLE IF NOT EXISTS `{audit_table}` (")
    lines.append(f"  {AUDIT_RUN_ID} STRING,")
    lines.append(f"  {AUDIT_STAGE} STRING,")
    lines.append(f"  {AUDIT_STEP} STRING,")
    lines.append(f"  {AUDIT_SQL_TEXT} STRING,")
    lines.append(f"  {AUDIT_EXECUTED_AT} STRING")
    lines.append(");")

    if entries:
        lines.append("")
        lines.append(f"INSERT INTO `{audit_table}`")
        lines.append(
            f"  ({AUDIT_RUN_ID}, {AUDIT_STAGE}, {AUDIT_STEP}, "
            f"{AUDIT_SQL_TEXT}, {AUDIT_EXECUTED_AT})"
        )
        lines.append("VALUES")

        escaped_run_id = sql_escape(run_id)
        value_rows: list[str] = []
        for entry in entries:
            escaped_stage = sql_escape(entry["stage"])
            escaped_step = sql_escape(entry["step"])
            escaped_sql = sql_escape(entry["sql"])
            escaped_ts = sql_escape(entry["timestamp"])
            value_rows.append(
                f"  ('{escaped_run_id}', '{escaped_stage}', "
                f"'{escaped_step}', '{escaped_sql}', '{escaped_ts}')"
            )
        lines.append(",\n".join(value_rows) + ";")

    return SQLExpression.from_raw("\n".join(lines))

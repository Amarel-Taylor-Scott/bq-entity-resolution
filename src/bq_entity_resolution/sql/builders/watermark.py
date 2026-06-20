"""SQL builder for watermark and checkpoint tables.

Replaces:
- watermark/create_watermark_table.sql.j2
- watermark/read_watermark.sql.j2
- watermark/update_watermark.sql.j2
- watermark/create_checkpoint_table.sql.j2
"""

from __future__ import annotations

from bq_entity_resolution.columns import (
    CHECKPOINT_COMPLETED_AT,
    CHECKPOINT_RUN_ID,
    CHECKPOINT_STAGE_NAME,
    CHECKPOINT_STATUS,
    WATERMARK_CURSOR_COLUMN,
    WATERMARK_CURSOR_TYPE,
    WATERMARK_CURSOR_VALUE,
    WATERMARK_IS_CURRENT,
    WATERMARK_RUN_ID,
    WATERMARK_SOURCE_NAME,
    WATERMARK_UPDATED_AT,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref


def build_create_watermark_table_sql(table: str) -> SQLExpression:
    """Build DDL to create the watermark tracking table."""
    validate_table_ref(table)
    sql = (
        f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
        f"  {WATERMARK_SOURCE_NAME} STRING NOT NULL,\n"
        f"  {WATERMARK_CURSOR_COLUMN} STRING NOT NULL,\n"
        f"  {WATERMARK_CURSOR_VALUE} STRING NOT NULL,\n"
        f"  {WATERMARK_CURSOR_TYPE} STRING NOT NULL,\n"
        f"  {WATERMARK_UPDATED_AT} TIMESTAMP NOT NULL,\n"
        f"  {WATERMARK_RUN_ID} STRING,\n"
        f"  {WATERMARK_IS_CURRENT} BOOL NOT NULL DEFAULT TRUE\n"
        f")\n"
        f"PARTITION BY DATE({WATERMARK_UPDATED_AT})\n"
        f"CLUSTER BY {WATERMARK_SOURCE_NAME}"
    )
    return SQLExpression.from_raw(sql)


def build_read_watermark_sql(table: str, source_name: str) -> SQLExpression:
    """Build SQL to read current watermark values for a source."""
    validate_table_ref(table)
    escaped = sql_escape(source_name)
    sql = (
        f"SELECT\n"
        f"  {WATERMARK_CURSOR_COLUMN},\n"
        f"  {WATERMARK_CURSOR_VALUE},\n"
        f"  {WATERMARK_CURSOR_TYPE},\n"
        f"  {WATERMARK_UPDATED_AT}\n"
        f"FROM `{table}`\n"
        f"WHERE {WATERMARK_SOURCE_NAME} = '{escaped}'\n"
        f"  AND {WATERMARK_IS_CURRENT} = TRUE\n"
        f"ORDER BY {WATERMARK_CURSOR_COLUMN}"
    )
    return SQLExpression.from_raw(sql)


def build_update_watermark_sql(
    table: str,
    source_name: str,
    cursors: list[dict[str, str]],
    run_id: str,
    now: str,
) -> SQLExpression:
    """Build SQL to update watermark values atomically.

    Uses BEGIN/COMMIT TRANSACTION for atomicity.

    Args:
        table: Fully-qualified watermark table name.
        source_name: Source identifier.
        cursors: List of {"column": str, "value": str, "type": str}.
        run_id: Pipeline run identifier.
        now: ISO timestamp string.
    """
    validate_table_ref(table)
    if not cursors:
        raise ValueError(
            f"No watermark cursors provided for source '{source_name}'. "
            "At least one cursor is required to advance the watermark."
        )

    escaped_source = sql_escape(source_name)
    escaped_run_id = sql_escape(run_id)
    escaped_now = sql_escape(now)

    lines: list[str] = []
    lines.append("BEGIN TRANSACTION;")
    lines.append("")
    lines.append("-- Mark previous watermarks as not current")
    lines.append(f"UPDATE `{table}`")
    lines.append(f"SET {WATERMARK_IS_CURRENT} = FALSE")
    lines.append(f"WHERE {WATERMARK_SOURCE_NAME} = '{escaped_source}'")
    lines.append(f"  AND {WATERMARK_IS_CURRENT} = TRUE;")
    lines.append("")
    lines.append("-- Insert new watermark values")
    lines.append(f"INSERT INTO `{table}`")
    lines.append(
        f"  ({WATERMARK_SOURCE_NAME}, {WATERMARK_CURSOR_COLUMN}, "
        f"{WATERMARK_CURSOR_VALUE}, {WATERMARK_CURSOR_TYPE}, "
        f"{WATERMARK_UPDATED_AT}, {WATERMARK_RUN_ID}, "
        f"{WATERMARK_IS_CURRENT})"
    )
    lines.append("VALUES")

    value_rows: list[str] = []
    for cursor in cursors:
        escaped_col = sql_escape(cursor["column"])
        escaped_val = sql_escape(cursor["value"])
        escaped_type = sql_escape(cursor["type"])
        value_rows.append(
            f"  ('{escaped_source}', '{escaped_col}', '{escaped_val}', "
            f"'{escaped_type}', TIMESTAMP('{escaped_now}'), "
            f"'{escaped_run_id}', TRUE)"
        )

    lines.append(",\n".join(value_rows) + ";")
    lines.append("")
    lines.append("COMMIT TRANSACTION;")

    return SQLExpression.from_raw("\n".join(lines))


def build_fenced_watermark_update_sql(
    watermark_table: str,
    source_name: str,
    cursors: list[dict[str, str]],
    run_id: str,
    now: str,
    lock_table: str,
    pipeline_name: str,
    fencing_token: int,
) -> SQLExpression:
    """Build fenced watermark update SQL.

    Uses a BQ scripting block that first verifies the caller still
    holds the distributed lock with the correct fencing token. If the
    token doesn't match (lock was stolen by another pod), the
    transaction rolls back without modifying the watermark.

    Args:
        watermark_table: Fully-qualified watermark table name.
        source_name: Source identifier.
        cursors: List of {"column": str, "value": str, "type": str}.
        run_id: Pipeline run identifier.
        now: ISO timestamp string.
        lock_table: Fully-qualified lock table name.
        pipeline_name: Pipeline name to look up in lock table.
        fencing_token: Expected fencing token from lock acquisition.
    """
    validate_table_ref(watermark_table)
    validate_table_ref(lock_table)
    if not cursors:
        raise ValueError(
            f"No watermark cursors provided for source '{source_name}'. "
            "At least one cursor is required to advance the watermark."
        )

    escaped_source = sql_escape(source_name)
    escaped_run_id = sql_escape(run_id)
    escaped_now = sql_escape(now)
    escaped_pipeline = sql_escape(pipeline_name)

    lines: list[str] = []
    lines.append("DECLARE current_token INT64;")
    lines.append("")
    lines.append("BEGIN TRANSACTION;")
    lines.append("")
    lines.append("-- Verify fencing token (abort if lock was stolen)")
    lines.append("SET current_token = (")
    lines.append(f"  SELECT fencing_token FROM `{lock_table}`")
    lines.append(f"  WHERE pipeline_name = '{escaped_pipeline}'")
    lines.append("  LIMIT 1")
    lines.append(");")
    lines.append("")
    lines.append(
        f"IF current_token IS NULL OR current_token != {fencing_token} THEN"
    )
    lines.append("  ROLLBACK TRANSACTION;")
    lines.append("END IF;")
    lines.append("")
    lines.append("-- Mark previous watermarks as not current")
    lines.append(f"UPDATE `{watermark_table}`")
    lines.append(f"SET {WATERMARK_IS_CURRENT} = FALSE")
    lines.append(f"WHERE {WATERMARK_SOURCE_NAME} = '{escaped_source}'")
    lines.append(f"  AND {WATERMARK_IS_CURRENT} = TRUE;")
    lines.append("")
    lines.append("-- Insert new watermark values")
    lines.append(f"INSERT INTO `{watermark_table}`")
    lines.append(
        f"  ({WATERMARK_SOURCE_NAME}, {WATERMARK_CURSOR_COLUMN}, "
        f"{WATERMARK_CURSOR_VALUE}, {WATERMARK_CURSOR_TYPE}, "
        f"{WATERMARK_UPDATED_AT}, {WATERMARK_RUN_ID}, "
        f"{WATERMARK_IS_CURRENT})"
    )
    lines.append("VALUES")

    value_rows: list[str] = []
    for cursor in cursors:
        escaped_col = sql_escape(cursor["column"])
        escaped_val = sql_escape(cursor["value"])
        escaped_type = sql_escape(cursor["type"])
        value_rows.append(
            f"  ('{escaped_source}', '{escaped_col}', '{escaped_val}', "
            f"'{escaped_type}', TIMESTAMP('{escaped_now}'), "
            f"'{escaped_run_id}', TRUE)"
        )

    lines.append(",\n".join(value_rows) + ";")
    lines.append("")
    lines.append("COMMIT TRANSACTION;")

    return SQLExpression.from_raw("\n".join(lines))


def build_fenced_checkpoint_insert_sql(
    checkpoint_table: str,
    run_id: str,
    stage_name: str,
    now: str,
    status: str,
    lock_table: str,
    pipeline_name: str,
    fencing_token: int,
) -> SQLExpression:
    """Build fenced checkpoint INSERT SQL.

    Uses a BQ scripting block that first verifies the caller still
    holds the distributed lock with the correct fencing token. If the
    token doesn't match (lock was stolen by another pod), the
    transaction rolls back without recording the checkpoint.

    Args:
        checkpoint_table: Fully-qualified checkpoint table name.
        run_id: Pipeline run identifier.
        stage_name: Name of the completed stage.
        now: ISO timestamp string.
        status: Checkpoint status (e.g. 'completed').
        lock_table: Fully-qualified lock table name.
        pipeline_name: Pipeline name to look up in lock table.
        fencing_token: Expected fencing token from lock acquisition.
    """
    validate_table_ref(checkpoint_table)
    validate_table_ref(lock_table)
    escaped_run_id = sql_escape(run_id)
    escaped_stage = sql_escape(stage_name)
    escaped_now = sql_escape(now)
    escaped_status = sql_escape(status)
    escaped_pipeline = sql_escape(pipeline_name)

    lines: list[str] = []
    lines.append("DECLARE current_token INT64;")
    lines.append("")
    lines.append("BEGIN TRANSACTION;")
    lines.append("")
    lines.append("-- Verify fencing token (abort if lock was stolen)")
    lines.append("SET current_token = (")
    lines.append(f"  SELECT fencing_token FROM `{lock_table}`")
    lines.append(f"  WHERE pipeline_name = '{escaped_pipeline}'")
    lines.append("  LIMIT 1")
    lines.append(");")
    lines.append("")
    lines.append(
        f"IF current_token IS NULL OR current_token != {fencing_token} THEN"
    )
    lines.append("  ROLLBACK TRANSACTION;")
    lines.append("END IF;")
    lines.append("")
    lines.append("-- Insert checkpoint record")
    lines.append(f"INSERT INTO `{checkpoint_table}`")
    lines.append(
        f"  ({CHECKPOINT_RUN_ID}, {CHECKPOINT_STAGE_NAME}, "
        f"{CHECKPOINT_COMPLETED_AT}, {CHECKPOINT_STATUS})"
    )
    lines.append("VALUES")
    lines.append(
        f"  ('{escaped_run_id}', '{escaped_stage}', "
        f"TIMESTAMP('{escaped_now}'), '{escaped_status}');"
    )
    lines.append("")
    lines.append("COMMIT TRANSACTION;")

    return SQLExpression.from_raw("\n".join(lines))


def build_create_checkpoint_table_sql(table: str) -> SQLExpression:
    """Build DDL to create the pipeline checkpoint table."""
    validate_table_ref(table)
    sql = (
        f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
        f"  {CHECKPOINT_RUN_ID} STRING NOT NULL,\n"
        f"  {CHECKPOINT_STAGE_NAME} STRING NOT NULL,\n"
        f"  {CHECKPOINT_COMPLETED_AT} TIMESTAMP NOT NULL,\n"
        f"  {CHECKPOINT_STATUS} STRING NOT NULL\n"
        f")\n"
        f"PARTITION BY DATE({CHECKPOINT_COMPLETED_AT})\n"
        f"CLUSTER BY {CHECKPOINT_RUN_ID}"
    )
    return SQLExpression.from_raw(sql)

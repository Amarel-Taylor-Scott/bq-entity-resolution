"""SQL builder for placeholder detection tracking tables.

Scans featured data for suspected placeholder values and logs them
to a detection table for data quality monitoring over time.
"""

from __future__ import annotations

from dataclasses import dataclass

from bq_entity_resolution.columns import (
    PLACEHOLDER_COLUMN_NAME,
    PLACEHOLDER_DETECTED_AT,
    PLACEHOLDER_MATCH_COUNT,
    PLACEHOLDER_PATTERN_TYPE,
    PLACEHOLDER_RUN_ID,
    PLACEHOLDER_SOURCE_NAME,
    PLACEHOLDER_VALUE,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref


@dataclass(frozen=True)
class PlaceholderScanColumn:
    """A column to scan for placeholder values."""

    column_name: str
    pattern_type: str  # e.g. "phone", "email", "name", "address", "ssn"
    detection_sql: str  # SQL expression returning 1 if placeholder, 0 otherwise


@dataclass(frozen=True)
class PlaceholderScanParams:
    """Parameters for placeholder scan SQL generation."""

    target_table: str  # Where to INSERT results
    source_table: str  # Featured table to scan
    run_id: str
    source_name: str
    scan_columns: list[PlaceholderScanColumn]
    min_count: int = 2


def build_create_placeholder_table_sql(table: str) -> SQLExpression:
    """Build DDL to create the placeholder detection log table."""
    validate_table_ref(table)
    sql = (
        f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
        f"  {PLACEHOLDER_RUN_ID} STRING NOT NULL,\n"
        f"  {PLACEHOLDER_SOURCE_NAME} STRING NOT NULL,\n"
        f"  {PLACEHOLDER_COLUMN_NAME} STRING NOT NULL,\n"
        f"  {PLACEHOLDER_VALUE} STRING,\n"
        f"  {PLACEHOLDER_MATCH_COUNT} INT64,\n"
        f"  {PLACEHOLDER_PATTERN_TYPE} STRING,\n"
        f"  {PLACEHOLDER_DETECTED_AT} TIMESTAMP NOT NULL\n"
        f")\n"
        f"PARTITION BY DATE({PLACEHOLDER_DETECTED_AT})\n"
        f"CLUSTER BY {PLACEHOLDER_RUN_ID}, {PLACEHOLDER_SOURCE_NAME}"
    )
    return SQLExpression.from_raw(sql)


def build_placeholder_scan_sql(params: PlaceholderScanParams) -> SQLExpression:
    """Build SQL to scan for placeholder values and insert results.

    Generates a UNION ALL of per-column scans, each grouping by value
    and filtering by HAVING COUNT >= min_count.
    """
    validate_table_ref(params.target_table)
    validate_table_ref(params.source_table)

    if not params.scan_columns:
        raise ValueError("No scan columns provided for placeholder detection")

    escaped_run_id = sql_escape(params.run_id)
    escaped_source = sql_escape(params.source_name)

    union_parts: list[str] = []
    for sc in params.scan_columns:
        escaped_col_name = sql_escape(sc.column_name)
        escaped_pattern = sql_escape(sc.pattern_type)
        part = (
            f"SELECT\n"
            f"  '{escaped_run_id}' AS {PLACEHOLDER_RUN_ID},\n"
            f"  '{escaped_source}' AS {PLACEHOLDER_SOURCE_NAME},\n"
            f"  '{escaped_col_name}' AS {PLACEHOLDER_COLUMN_NAME},\n"
            f"  CAST({sc.column_name} AS STRING) AS {PLACEHOLDER_VALUE},\n"
            f"  COUNT(*) AS {PLACEHOLDER_MATCH_COUNT},\n"
            f"  '{escaped_pattern}' AS {PLACEHOLDER_PATTERN_TYPE},\n"
            f"  CURRENT_TIMESTAMP() AS {PLACEHOLDER_DETECTED_AT}\n"
            f"FROM `{params.source_table}`\n"
            f"WHERE {sc.detection_sql} = 1\n"
            f"  AND {sc.column_name} IS NOT NULL\n"
            f"GROUP BY {sc.column_name}\n"
            f"HAVING COUNT(*) >= {params.min_count}"
        )
        union_parts.append(part)

    union_sql = "\nUNION ALL\n".join(union_parts)

    lines: list[str] = []
    lines.append(f"INSERT INTO `{params.target_table}`")
    lines.append(
        f"  ({PLACEHOLDER_RUN_ID}, {PLACEHOLDER_SOURCE_NAME}, "
        f"{PLACEHOLDER_COLUMN_NAME}, {PLACEHOLDER_VALUE}, "
        f"{PLACEHOLDER_MATCH_COUNT}, {PLACEHOLDER_PATTERN_TYPE}, "
        f"{PLACEHOLDER_DETECTED_AT})"
    )
    lines.append(union_sql)

    return SQLExpression.from_raw("\n".join(lines))

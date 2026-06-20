"""
Watermark storage helpers.

Provides the table schema and utility functions for the watermark
metadata table.
"""

from __future__ import annotations

WATERMARK_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS `{table}` (
  source_name STRING NOT NULL,
  cursor_column STRING NOT NULL,
  cursor_value STRING NOT NULL,
  cursor_type STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  run_id STRING,
  is_current BOOL NOT NULL DEFAULT TRUE
)
PARTITION BY DATE(updated_at)
CLUSTER BY source_name
"""


def build_watermark_table_name(
    project: str, dataset: str, table_name: str = "pipeline_watermarks"
) -> str:
    """Build fully-qualified watermark table name."""
    return f"{project}.{dataset}.{table_name}"

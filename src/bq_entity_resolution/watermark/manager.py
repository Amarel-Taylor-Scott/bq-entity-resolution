"""
Watermark manager for incremental processing.

Runtime watermark tracking backed by a BigQuery metadata table.
Only advances watermarks after successful pipeline completion.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from bq_entity_resolution.exceptions import LockFencingError, WatermarkError
from bq_entity_resolution.sql.builders.watermark import (
    build_create_watermark_table_sql,
    build_fenced_watermark_update_sql,
    build_read_watermark_sql,
    build_update_watermark_sql,
)
from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref

logger = logging.getLogger(__name__)


class WatermarkManager:
    """
    Manages watermark state in a BigQuery metadata table.

    Advantages over dbt compile-time watermarks:
    - Read at runtime, not compile time
    - Advance only on success (transactional)
    - Compound cursor support (multiple columns)
    - Grace period for late-arriving data
    - Full audit trail
    - Optional fencing token verification for multi-pod safety
    """

    def __init__(
        self,
        bq_client: Any,  # BigQueryClient
        watermark_table: str,
    ):
        self.bq_client = bq_client
        self.watermark_table = watermark_table

    def ensure_table_exists(self) -> None:
        """Create the watermark table if it doesn't exist."""
        expr = build_create_watermark_table_sql(self.watermark_table)
        self.bq_client.execute(expr.render(), job_label="ensure_watermark_table")
        logger.info("Watermark table ensured: %s", self.watermark_table)

    def read(self, source_name: str) -> dict[str, Any] | None:
        """
        Read current watermark for a source.

        Returns dict of {cursor_column: cursor_value} or None if no watermark.
        """
        expr = build_read_watermark_sql(self.watermark_table, source_name)
        try:
            rows = self.bq_client.execute_and_fetch(expr.render())
        except Exception as exc:
            raise WatermarkError(
                f"Failed to read watermark for '{source_name}': {exc}"
            ) from exc

        if not rows:
            logger.info("No watermark found for source '%s'", source_name)
            return None

        result = {}
        for row in rows:
            value = _deserialize(row["cursor_value"], row["cursor_type"])
            result[row["cursor_column"]] = value

        logger.info("Read watermark for '%s': %s", source_name, result)
        return result

    def write(
        self,
        source_name: str,
        cursors: dict[str, Any],
        run_id: str = "",
        fencing_token: int | None = None,
        lock_table: str | None = None,
        pipeline_name: str | None = None,
    ) -> None:
        """
        Write new watermark values.

        Marks previous values as not current and inserts new values.

        When ``fencing_token``, ``lock_table``, and ``pipeline_name`` are
        provided, the watermark write is fenced: the SQL verifies the
        fencing token in the lock table before committing. If the token
        doesn't match (lock was stolen by another pod), the transaction
        rolls back and a ``LockFencingError`` is raised.

        When these parameters are omitted (DuckDB, local dev), the write
        is unfenced for backward compatibility.
        """
        if not cursors:
            logger.warning("No cursor values to write for '%s'", source_name)
            return

        cursor_rows = [
            {
                "column": col,
                "value": _serialize(val),
                "type": _type_name(val),
            }
            for col, val in cursors.items()
        ]

        now = datetime.now(UTC).isoformat()

        fencing_params = (fencing_token, lock_table, pipeline_name)
        fencing_provided = sum(1 for p in fencing_params if p is not None)
        if fencing_provided > 0 and fencing_provided < 3:
            logger.warning(
                "Partial fencing config for watermark write on '%s': "
                "fencing_token=%s, lock_table=%s, pipeline_name=%s. "
                "All three must be provided for fenced writes; "
                "falling back to unfenced write.",
                source_name, fencing_token, lock_table, pipeline_name,
            )

        if fencing_provided == 3:
            assert fencing_token is not None
            assert lock_table is not None
            assert pipeline_name is not None
            expr = build_fenced_watermark_update_sql(
                watermark_table=self.watermark_table,
                source_name=source_name,
                cursors=cursor_rows,
                run_id=run_id,
                now=now,
                lock_table=lock_table,
                pipeline_name=pipeline_name,
                fencing_token=fencing_token,
            )
        else:
            expr = build_update_watermark_sql(
                table=self.watermark_table,
                source_name=source_name,
                cursors=cursor_rows,
                run_id=run_id,
                now=now,
            )

        try:
            self.bq_client.execute(
                expr.render(), job_label=f"watermark_update_{source_name}"
            )
        except LockFencingError:
            raise
        except Exception as exc:
            err_msg = str(exc).lower()
            if "fencing token mismatch" in err_msg or "rollback" in err_msg:
                raise LockFencingError(
                    f"Lock lost during watermark write for '{source_name}': {exc}"
                ) from exc
            raise WatermarkError(
                f"Failed to write watermark for '{source_name}': {exc}"
            ) from exc

        logger.info("Watermark updated for '%s': %s", source_name, cursors)

    def compute_new_watermark(
        self,
        source_table: str,
        cursor_columns: list[str],
    ) -> dict[str, Any]:
        """Query the source table for the maximum cursor values."""
        validate_table_ref(source_table)
        for col in cursor_columns:
            validate_identifier(col, context="cursor column")
        max_exprs = ", ".join(
            f"MAX({col}) AS max_{col}" for col in cursor_columns
        )
        sql = f"SELECT {max_exprs} FROM `{source_table}`"

        try:
            rows = self.bq_client.execute_and_fetch(sql)
        except Exception as exc:
            raise WatermarkError(
                f"Failed to compute watermark from '{source_table}': {exc}"
            ) from exc

        if not rows:
            return {}

        row = rows[0]
        return {
            col: row[f"max_{col}"]
            for col in cursor_columns
            if row.get(f"max_{col}") is not None
        }

    def compute_new_watermark_from_staged(
        self,
        staged_table: str,
        cursor_columns: list[str],
        column_mapping: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Compute new watermark from the staged (bronze) table.

        This is the correct approach for ordered cursors: the watermark
        advances to the MAX values of what was actually staged in this
        batch, not what exists in the raw source (which may be far ahead).

        This prevents watermark drift that could cause the pipeline to
        skip unprocessed records between the batch boundary and the
        source maximum.

        Args:
            staged_table: The bronze staging table for the current batch.
            cursor_columns: Original source cursor column names.
            column_mapping: Optional mapping from source column names to
                staged column names (e.g. {"updated_at": "source_updated_at"}).
        """
        validate_table_ref(staged_table)
        for col in cursor_columns:
            validate_identifier(col, context="cursor column")
        mapping = column_mapping or {}
        for mapped_col in mapping.values():
            validate_identifier(mapped_col, context="mapped cursor column")
        max_exprs = ", ".join(
            f"MAX({mapping.get(col, col)}) AS max_{col}"
            for col in cursor_columns
        )
        sql = f"SELECT {max_exprs} FROM `{staged_table}`"

        try:
            rows = self.bq_client.execute_and_fetch(sql)
        except Exception as exc:
            raise WatermarkError(
                f"Failed to compute watermark from staged '{staged_table}': {exc}"
            ) from exc

        if not rows:
            return {}

        row = rows[0]
        return {
            col: row[f"max_{col}"]
            for col in cursor_columns
            if row.get(f"max_{col}") is not None
        }

    def has_unprocessed_records(
        self,
        source_table: str,
        cursor_columns: list[str],
        current_watermark: dict[str, Any],
        cursor_mode: str = "ordered",
        grace_period_hours: int = 0,
    ) -> bool:
        """Check if there are records beyond the current watermark.

        Used by drain mode to determine when to stop iterating.

        Args:
            source_table: Fully-qualified source table name.
            cursor_columns: Cursor column names.
            current_watermark: Current watermark values.
            cursor_mode: ``"ordered"`` for tuple comparison (consistent
                with staging SQL) or ``"independent"`` for OR logic.
            grace_period_hours: Grace period to apply to the first
                (timestamp) cursor column, matching staging behavior.
        """
        validate_table_ref(source_table)
        for col in cursor_columns:
            validate_identifier(col, context="cursor column")

        if not current_watermark:
            return True

        from bq_entity_resolution.sql.builders.staging import (
            _build_ordered_watermark,
        )
        from bq_entity_resolution.sql.utils import format_watermark_value

        if cursor_mode == "ordered" and len(cursor_columns) > 1:
            # Build the same ordered tuple comparison as staging SQL
            wm_dict = {
                col: current_watermark[col]
                for col in cursor_columns
                if col in current_watermark and current_watermark[col] is not None
            }
            if not wm_dict:
                return True
            where_clause = _build_ordered_watermark(wm_dict, grace_period_hours)
        else:
            # Independent (OR) mode
            conditions: list[str] = []
            for col in cursor_columns:
                val = current_watermark.get(col)
                if val is not None:
                    formatted = format_watermark_value(val)
                    if grace_period_hours and grace_period_hours > 0:
                        conditions.append(
                            f"{col} > TIMESTAMP_SUB({formatted}, "
                            f"INTERVAL {grace_period_hours} HOUR)"
                        )
                    else:
                        conditions.append(f"{col} > {formatted}")
            if not conditions:
                return True
            where_clause = " OR ".join(conditions)

        sql = (
            f"SELECT COUNT(*) AS cnt FROM `{source_table}` "
            f"WHERE {where_clause} LIMIT 1"
        )

        try:
            rows = self.bq_client.execute_and_fetch(sql)
        except Exception as exc:
            logger.warning(
                "Failed to check unprocessed records, assuming more exist: %s", exc
            )
            return True  # Fail-open: assume more records to prevent data loss

        return bool(rows and rows[0].get("cnt", 0) > 0)


def _serialize(value: Any) -> str:
    """Serialize a watermark value to string for storage."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _deserialize(value: str, type_name: str) -> Any:
    """Deserialize a stored watermark value.

    Raises WatermarkError for unsupported types instead of silently
    falling back to string.
    """
    if type_name == "TIMESTAMP":
        return datetime.fromisoformat(value)
    if type_name == "DATE":
        return date.fromisoformat(value)
    if type_name == "INT64":
        return int(value)
    if type_name == "FLOAT64":
        return float(value)
    if type_name in ("NUMERIC", "BIGNUMERIC"):
        return Decimal(value)
    if type_name == "STRING":
        return value
    raise WatermarkError(f"Unsupported watermark type: {type_name!r}")


def _type_name(value: Any) -> str:
    """Determine the type name for a watermark value."""
    if isinstance(value, datetime):
        return "TIMESTAMP"
    if isinstance(value, date):
        return "DATE"
    if isinstance(value, Decimal):
        return "NUMERIC"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    return "STRING"

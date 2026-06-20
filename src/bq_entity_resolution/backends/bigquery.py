"""BigQuery backend: production execution with retries and cost tracking.

Wraps the existing BigQueryClient to conform to the Backend protocol.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.backends.protocol import (
    ColumnDef,
    QueryResult,
    TableSchema,
)
from bq_entity_resolution.clients.bigquery import BigQueryClient
from bq_entity_resolution.clients.bigquery import QueryResult as BQQueryResult

logger = logging.getLogger(__name__)

# BigQuery type mapping for INFORMATION_SCHEMA
_BQ_TYPE_MAP = {
    "STRING": "STRING",
    "INT64": "INT64",
    "INTEGER": "INT64",
    "FLOAT64": "FLOAT64",
    "FLOAT": "FLOAT64",
    "BOOL": "BOOL",
    "BOOLEAN": "BOOL",
    "TIMESTAMP": "TIMESTAMP",
    "DATE": "DATE",
    "DATETIME": "DATETIME",
    "BYTES": "BYTES",
    "NUMERIC": "NUMERIC",
    "BIGNUMERIC": "BIGNUMERIC",
    "GEOGRAPHY": "GEOGRAPHY",
    "JSON": "JSON",
}


class BigQueryBackend:
    """BigQuery production backend.

    Delegates to the existing BigQueryClient which handles retries,
    job labeling, dry-run support, and structured logging.

    Can be constructed with a pre-built BigQueryClient or with
    individual connection parameters. Supports context manager
    protocol for deterministic resource cleanup::

        with BigQueryBackend(project="my-project") as backend:
            result = pipeline.run(backend=backend)
    """

    def __init__(
        self,
        project: str | BigQueryClient | None = None,
        location: str = "US",
        dry_run: bool = False,
        max_bytes_billed: int | None = None,
        default_timeout: int = 600,
        *,
        client: BigQueryClient | None = None,
    ):
        # Accept a pre-built client via keyword or positional arg
        if isinstance(project, BigQueryClient):
            self._client = project
            self._project = project.project
            self._owns_client = False
        elif client is not None:
            self._client = client
            self._project = client.project
            self._owns_client = False
        elif isinstance(project, str):
            self._client = BigQueryClient(
                project=project,
                location=location,
                dry_run=dry_run,
                max_bytes_billed=max_bytes_billed,
                default_timeout=default_timeout,
            )
            self._project = project
            self._owns_client = True
        else:
            raise TypeError(
                "BigQueryBackend requires either project: str or "
                "client: BigQueryClient"
            )

    def _check_open(self) -> None:
        """Raise RuntimeError if the backend has been closed."""
        if self._client is None:
            raise RuntimeError("BigQueryBackend is closed. Cannot execute operations.")

    def close(self) -> None:
        """Close the underlying client if this backend owns it."""
        if self._owns_client and self._client is not None:
            if hasattr(self._client, "close"):
                self._client.close()
            self._client = None  # type: ignore[assignment]

    def __enter__(self) -> BigQueryBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def bq_client(self) -> BigQueryClient:
        """The underlying BigQueryClient (for job tracking, cost checks, etc.)."""
        return self._client

    @property
    def dialect(self) -> str:
        return "bigquery"

    @property
    def total_bytes_billed(self) -> int:
        """Cumulative bytes billed across all queries."""
        return self._client.total_bytes_billed

    def check_cost_ceiling(self, ceiling: int | None) -> None:
        """Raise PipelineAbortError if cost ceiling exceeded."""
        self._client.check_cost_ceiling(ceiling)

    def execute(self, sql: str, label: str = "") -> QueryResult:
        self._check_open()
        bq_result = self._client.execute(sql, job_label=label)
        return _convert_result(bq_result)

    def execute_and_fetch(self, sql: str, label: str = "") -> list[dict[str, Any]]:
        self._check_open()
        return self._client.execute_and_fetch(sql, job_label=label)

    def execute_script(self, sql: str, label: str = "") -> QueryResult:
        self._check_open()
        # BQ handles scripts transparently via execute
        bq_result = self._client.execute(sql, job_label=label)
        return _convert_result(bq_result)

    def execute_script_and_fetch(self, sql: str, label: str = "") -> list[dict[str, Any]]:
        self._check_open()
        return self._client.execute_script_and_fetch(sql, job_label=label)

    def table_exists(self, table_ref: str) -> bool:
        self._check_open()
        from bq_entity_resolution.sql.utils import validate_table_ref

        validate_table_ref(table_ref)
        return self._client.table_exists(table_ref)

    def get_table_schema(self, table_ref: str) -> TableSchema:
        """Read table schema from BigQuery INFORMATION_SCHEMA."""
        self._check_open()
        from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref

        clean_ref = table_ref.replace("`", "")
        parts = clean_ref.split(".")
        if len(parts) != 3:
            raise ValueError(f"Expected project.dataset.table, got: {table_ref}")
        # Validate full reference to prevent SQL injection via project/dataset/table names
        validate_table_ref(clean_ref)
        project, dataset, table = parts
        table_safe = sql_escape(table)
        sql = (
            f"SELECT column_name, data_type, is_nullable "
            f"FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = '{table_safe}' "
            f"ORDER BY ordinal_position"
        )
        rows = self._client.execute_and_fetch(sql, job_label="schema_introspection")
        columns = tuple(
            ColumnDef(
                name=row["column_name"],
                type=_BQ_TYPE_MAP.get(row["data_type"], row["data_type"]),
                nullable=row["is_nullable"] == "YES",
            )
            for row in rows
        )
        return TableSchema(columns=columns)

    def estimate_bytes(self, sql: str, label: str = "") -> int:
        """Estimate bytes processed via BigQuery dry-run API."""
        self._check_open()
        try:
            from google.cloud import bigquery as bq

            job_config = bq.QueryJobConfig(dry_run=True, use_query_cache=False)
            job = self._client._client.query(sql, job_config=job_config)
            return job.total_bytes_processed or 0
        except Exception:
            logger.warning("Dry-run estimate failed for label=%s", label, exc_info=True)
            return 0

    def row_count(self, table_ref: str) -> int:
        self._check_open()
        from bq_entity_resolution.sql.utils import validate_table_ref

        validate_table_ref(table_ref)
        rows = self._client.execute_and_fetch(
            f"SELECT COUNT(*) AS cnt FROM `{table_ref}`",
            job_label="row_count",
        )
        return rows[0]["cnt"] if rows else 0


def _convert_result(bq_result: BQQueryResult) -> QueryResult:
    """Convert BQ client result to backend protocol result."""
    return QueryResult(
        job_id=bq_result.job_id,
        rows_affected=bq_result.rows_affected,
        bytes_billed=bq_result.bytes_billed,
        duration_seconds=bq_result.duration_seconds,
        total_bytes_processed=bq_result.total_bytes_processed,
        slot_milliseconds=bq_result.slot_milliseconds,
    )

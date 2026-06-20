"""BigQuery Emulator backend: Docker-based BQ SQL fidelity testing.

Uses goccy/bigquery-emulator to execute actual BigQuery SQL locally.
Provides full BQ SQL compatibility including geo functions, QUALIFY,
and BQ-specific syntax that DuckDB cannot emulate.

Requires:
- Docker running with bigquery-emulator container
- google-cloud-bigquery Python client
"""

from __future__ import annotations

import logging
import time
from typing import Any

from bq_entity_resolution.backends.protocol import (
    ColumnDef,
    QueryResult,
    TableSchema,
)

logger = logging.getLogger(__name__)

# BQ type mapping
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


class BQEmulatorBackend:
    """BigQuery emulator backend for high-fidelity local testing.

    Connects to a running bigquery-emulator Docker container.
    Supports all BQ SQL syntax, functions, and types.
    """

    def __init__(
        self,
        project: str = "test-project",
        dataset: str = "test_dataset",
        host: str = "localhost",
        port: int = 9050,
    ):
        try:
            from google.api_core.client_options import ClientOptions
            from google.auth.credentials import AnonymousCredentials
            from google.cloud import bigquery
        except ImportError:
            raise ImportError(
                "google-cloud-bigquery is required for the BQ emulator backend. "
                "Install with: pip install google-cloud-bigquery"
            )

        self._project = project
        self._dataset = dataset
        self._client = bigquery.Client(
            project=project,
            credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
            client_options=ClientOptions(
                api_endpoint=f"http://{host}:{port}",
            ),
        )
        # Ensure dataset exists
        self._ensure_dataset()

    def _ensure_dataset(self) -> None:
        """Create the test dataset if it doesn't exist."""
        from google.cloud import bigquery

        dataset_ref = f"{self._project}.{self._dataset}"
        try:
            self._client.get_dataset(dataset_ref)
        except Exception:
            dataset = bigquery.Dataset(dataset_ref)
            try:
                self._client.create_dataset(dataset)
                logger.info("Created dataset: %s", dataset_ref)
            except Exception as e:
                logger.debug("Dataset creation skipped: %s", e)

    def _check_open(self) -> None:
        """Raise RuntimeError if the backend has been closed."""
        if self._client is None:
            raise RuntimeError("BQEmulatorBackend is closed. Cannot execute operations.")

    def close(self) -> None:
        """Close the underlying BigQuery client."""
        if self._client is not None:
            self._client.close()  # type: ignore[no-untyped-call]
            self._client = None  # type: ignore[assignment]

    def __enter__(self) -> BQEmulatorBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def dialect(self) -> str:
        return "bigquery"

    def execute(self, sql: str, label: str = "") -> QueryResult:
        self._check_open()
        start = time.monotonic()
        try:
            job = self._client.query(sql)
            result = job.result()
            duration = time.monotonic() - start
            row_count = result.total_rows if result.total_rows else 0
            return QueryResult(
                job_id=job.job_id or f"bqemu_{label}",
                rows_affected=row_count,
                duration_seconds=duration,
            )
        except Exception as e:
            logger.error("BQ emulator error (label=%s): %s", label, e)
            logger.error("SQL:\n%s", sql[:500])
            raise

    def execute_and_fetch(self, sql: str, label: str = "") -> list[dict[str, Any]]:
        self._check_open()
        job = self._client.query(sql)
        result = job.result()
        return [dict(row) for row in result]

    def execute_script(self, sql: str, label: str = "") -> QueryResult:
        """Execute a multi-statement script.

        The emulator may not support full BQ scripting (DECLARE/WHILE/LOOP).
        We strip scripting constructs and execute the remaining SQL.
        """
        self._check_open()
        # Strip BQ scripting constructs the emulator can't handle

        lines = sql.split("\n")
        filtered = []
        skip = False
        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith("DECLARE "):
                continue
            if stripped.startswith("SET "):
                continue
            if stripped.startswith("WHILE ") or stripped == "LOOP":
                skip = True
                continue
            if stripped.startswith("END WHILE") or stripped.startswith("END LOOP"):
                skip = False
                continue
            if stripped == "LEAVE;":
                continue
            if not skip:
                filtered.append(line)

        clean_sql = "\n".join(filtered).strip()
        if not clean_sql:
            return QueryResult(job_id=f"bqemu_script_{label}")

        start = time.monotonic()
        try:
            job = self._client.query(clean_sql)
            result = job.result()
            row_count = result.total_rows if result.total_rows else 0
            return QueryResult(
                job_id=job.job_id or f"bqemu_script_{label}",
                rows_affected=row_count,
                duration_seconds=time.monotonic() - start,
            )
        except Exception as e:
            logger.error("BQ emulator script error (label=%s): %s", label, e)
            raise

    def execute_script_and_fetch(self, sql: str, label: str = "") -> list[dict[str, Any]]:
        self._check_open()
        job = self._client.query(sql)
        result = job.result()
        return [dict(row) for row in result]

    def table_exists(self, table_ref: str) -> bool:
        self._check_open()
        from google.api_core.exceptions import NotFound

        try:
            self._client.get_table(table_ref)
            return True
        except NotFound:
            return False

    def get_table_schema(self, table_ref: str) -> TableSchema:
        self._check_open()
        table = self._client.get_table(table_ref)
        columns = []
        for field in table.schema:
            mapped_type = _BQ_TYPE_MAP.get(field.field_type, field.field_type)
            nullable = field.mode != "REQUIRED"
            columns.append(ColumnDef(name=field.name, type=mapped_type, nullable=nullable))
        return TableSchema(columns=tuple(columns))

    def estimate_bytes(self, sql: str, label: str = "") -> int:
        """Emulator does not support cost estimation; always returns 0."""
        return 0

    def row_count(self, table_ref: str) -> int:
        self._check_open()
        from bq_entity_resolution.sql.utils import validate_table_ref

        validate_table_ref(table_ref)
        rows = self.execute_and_fetch(f"SELECT COUNT(*) AS cnt FROM `{table_ref}`")
        return rows[0]["cnt"] if rows else 0

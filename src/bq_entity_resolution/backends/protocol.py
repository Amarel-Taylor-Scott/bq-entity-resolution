"""Backend protocol: the contract all execution backends must satisfy.

Backends handle SQL execution and table introspection. The protocol
enables BigQuery for production and DuckDB for local testing from
the same pipeline code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ColumnDef:
    """Column definition for schema contracts."""

    name: str
    type: str  # e.g. "STRING", "INT64", "FLOAT64", "TIMESTAMP"
    nullable: bool = True


@dataclass(frozen=True)
class TableSchema:
    """Schema declaration for a table."""

    columns: tuple[ColumnDef, ...]

    @property
    def required_columns(self) -> list[ColumnDef]:
        return [c for c in self.columns if not c.nullable]

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def get_column(self, name: str) -> ColumnDef | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    def __contains__(self, name: str) -> bool:
        return any(c.name == name for c in self.columns)


@dataclass
class QueryResult:
    """Result metadata from a query execution."""

    job_id: str = ""
    rows_affected: int = 0
    bytes_billed: int = 0
    duration_seconds: float = 0.0
    total_bytes_processed: int = 0
    slot_milliseconds: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class Backend(Protocol):
    """Execution backend protocol.

    Implementations:
    - BigQueryBackend: production execution with retries and job labels
    - DuckDBBackend: local development and testing with BQ function shims

    All backends support context manager protocol for deterministic
    resource cleanup::

        with BigQueryBackend(project="my-project") as backend:
            result = pipeline.run(backend=backend)
    """

    @property
    def dialect(self) -> str:
        """sqlglot dialect name for SQL rendering (e.g. 'bigquery', 'duckdb')."""
        ...

    def execute(self, sql: str, label: str = "") -> QueryResult:
        """Execute a SQL statement and return result metadata."""
        ...

    def execute_and_fetch(self, sql: str, label: str = "") -> list[dict[str, Any]]:
        """Execute SQL and return rows as list of dicts."""
        ...

    def execute_script(self, sql: str, label: str = "") -> QueryResult:
        """Execute a multi-statement SQL script."""
        ...

    def execute_script_and_fetch(self, sql: str, label: str = "") -> list[dict[str, Any]]:
        """Execute a SQL script and return the final result set."""
        ...

    def table_exists(self, table_ref: str) -> bool:
        """Check if a table exists."""
        ...

    def get_table_schema(self, table_ref: str) -> TableSchema:
        """Read actual table schema."""
        ...

    def row_count(self, table_ref: str) -> int:
        """Quick row count for a table."""
        ...

    def estimate_bytes(self, sql: str, label: str = "") -> int:
        """Estimate bytes that would be processed without executing (dry-run).

        Returns 0 if the backend does not support cost estimation.
        Used by Pipeline.estimate_cost() for pre-execution cost checks.
        """
        ...

    def close(self) -> None:
        """Release resources held by this backend."""
        ...

    def __enter__(self) -> Backend:
        """Enter context manager."""
        ...

    def __exit__(self, *args: object) -> None:
        """Exit context manager, calling close()."""
        ...

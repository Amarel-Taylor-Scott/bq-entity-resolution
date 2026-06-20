"""Backend abstractions for SQL execution."""

from typing import Any

from bq_entity_resolution.backends.protocol import Backend, ColumnDef, QueryResult, TableSchema

__all__ = ["Backend", "QueryResult", "TableSchema", "ColumnDef"]


def get_backend(name: str, **kwargs: Any) -> Backend:
    """Factory for creating backend instances.

    Args:
        name: Backend type — 'bigquery', 'duckdb', or 'bqemulator'
        **kwargs: Backend-specific arguments

    Returns:
        A Backend instance.
    """
    if name == "bigquery":
        from bq_entity_resolution.backends.bigquery import BigQueryBackend
        return BigQueryBackend(**kwargs)
    elif name == "duckdb":
        from bq_entity_resolution.backends.duckdb import DuckDBBackend
        return DuckDBBackend(**kwargs)
    elif name == "bqemulator":
        from bq_entity_resolution.backends.bqemulator import BQEmulatorBackend
        return BQEmulatorBackend(**kwargs)
    else:
        raise ValueError(f"Unknown backend: {name}")

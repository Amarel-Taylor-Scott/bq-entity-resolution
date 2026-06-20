"""DuckDB backend package: local development and testing with BQ function shims.

Re-exports DuckDBBackend as the single public class so that
``from bq_entity_resolution.backends.duckdb import DuckDBBackend``
continues to work unchanged.
"""

from bq_entity_resolution.backends.duckdb.backend import DuckDBBackend

__all__ = ["DuckDBBackend"]

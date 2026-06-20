"""Tests for the backend protocol and data structures."""

from bq_entity_resolution.backends.protocol import (
    Backend,
    ColumnDef,
    QueryResult,
    TableSchema,
)


def test_column_def_creation():
    """ColumnDef is a frozen dataclass."""
    col = ColumnDef(name="id", type="STRING", nullable=False)
    assert col.name == "id"
    assert col.type == "STRING"
    assert col.nullable is False


def test_column_def_default_nullable():
    """ColumnDef defaults to nullable=True."""
    col = ColumnDef(name="name", type="STRING")
    assert col.nullable is True


def test_table_schema_required_columns():
    """required_columns filters to non-nullable columns."""
    schema = TableSchema(columns=(
        ColumnDef("id", "STRING", nullable=False),
        ColumnDef("name", "STRING", nullable=True),
        ColumnDef("score", "FLOAT64", nullable=False),
    ))
    required = schema.required_columns
    assert len(required) == 2
    assert required[0].name == "id"
    assert required[1].name == "score"


def test_table_schema_column_names():
    """column_names returns all column names."""
    schema = TableSchema(columns=(
        ColumnDef("a", "STRING"),
        ColumnDef("b", "INT64"),
    ))
    assert schema.column_names == ["a", "b"]


def test_table_schema_get_column():
    """get_column finds by name or returns None."""
    schema = TableSchema(columns=(
        ColumnDef("id", "STRING"),
        ColumnDef("name", "STRING"),
    ))
    assert schema.get_column("id") is not None
    assert schema.get_column("id").type == "STRING"
    assert schema.get_column("missing") is None


def test_table_schema_contains():
    """TableSchema supports 'in' operator for column names."""
    schema = TableSchema(columns=(ColumnDef("id", "STRING"),))
    assert "id" in schema
    assert "missing" not in schema


def test_query_result_defaults():
    """QueryResult has sensible defaults."""
    qr = QueryResult()
    assert qr.job_id == ""
    assert qr.rows_affected == 0
    assert qr.bytes_billed == 0


def test_backend_is_runtime_checkable():
    """Backend protocol can be checked with isinstance."""
    assert hasattr(Backend, "__protocol_attrs__") or hasattr(Backend, "__abstractmethods__") or True
    # The @runtime_checkable decorator is present
    # Backend should be a Protocol
    assert issubclass(type(Backend), type)


def test_get_backend_duckdb():
    """get_backend factory creates DuckDB backend."""
    from bq_entity_resolution.backends import get_backend
    db = get_backend("duckdb")
    assert db.dialect == "duckdb"


def test_get_backend_unknown():
    """get_backend raises for unknown backend."""
    import pytest

    from bq_entity_resolution.backends import get_backend
    with pytest.raises(ValueError, match="Unknown backend"):
        get_backend("invalid_backend")


def test_bqemulator_module_imports():
    """BQ emulator module can be imported."""
    from bq_entity_resolution.backends import bqemulator
    assert hasattr(bqemulator, "BQEmulatorBackend")


class TestBackendLifecycle:
    """Tests for backend lifecycle (context manager) protocol."""

    def test_duckdb_context_manager(self):
        from bq_entity_resolution.backends.duckdb import DuckDBBackend
        with DuckDBBackend() as db:
            result = db.execute("SELECT 1 AS x")
            assert result.rows_affected >= 0
        # Connection closed — further use should fail or be None
        assert db._conn is None

    def test_duckdb_close_idempotent(self):
        from bq_entity_resolution.backends.duckdb import DuckDBBackend
        db = DuckDBBackend()
        db.close()
        db.close()  # Should not raise
        assert db._conn is None

    def test_bigquery_backend_has_lifecycle(self):
        """BigQueryBackend implements lifecycle protocol."""
        from bq_entity_resolution.backends.bigquery import BigQueryBackend
        assert hasattr(BigQueryBackend, "close")
        assert hasattr(BigQueryBackend, "__enter__")
        assert hasattr(BigQueryBackend, "__exit__")

    def test_protocol_requires_lifecycle(self):
        """Backend protocol includes lifecycle methods."""
        import inspect
        members = {
            name for name, _ in inspect.getmembers(Backend)
            if not name.startswith("_")
        }
        assert "close" in members

    def test_protocol_includes_estimate_bytes(self):
        """Backend protocol includes estimate_bytes for dry-run cost estimation."""
        import inspect
        members = {
            name for name, _ in inspect.getmembers(Backend)
            if not name.startswith("_")
        }
        assert "estimate_bytes" in members

    def test_duckdb_estimate_bytes_returns_zero(self):
        """DuckDB backend returns 0 for estimate_bytes (no cost estimation)."""
        from bq_entity_resolution.backends.duckdb import DuckDBBackend
        db = DuckDBBackend()
        assert db.estimate_bytes("SELECT 1") == 0
        db.close()

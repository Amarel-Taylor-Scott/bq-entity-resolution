"""Tests for the DuckDB local backend."""

import pytest

from bq_entity_resolution.backends.duckdb import DuckDBBackend
from bq_entity_resolution.backends.protocol import QueryResult, TableSchema


@pytest.fixture
def db():
    """Fresh in-memory DuckDB backend."""
    return DuckDBBackend(":memory:")


def test_duckdb_backend_dialect(db):
    """DuckDB backend reports correct dialect."""
    assert db.dialect == "duckdb"


def test_duckdb_execute_ddl(db):
    """Can execute DDL statements."""
    result = db.execute("CREATE TABLE test_t (id VARCHAR, name VARCHAR)")
    assert isinstance(result, QueryResult)
    assert result.job_id.startswith("duckdb_")


def test_duckdb_execute_and_fetch(db):
    """execute_and_fetch returns list of dicts."""
    rows = db.execute_and_fetch("SELECT 1 AS a, 'hello' AS b")
    assert len(rows) == 1
    assert rows[0]["a"] == 1
    assert rows[0]["b"] == "hello"


def test_duckdb_table_exists(db):
    """table_exists correctly detects tables."""
    assert db.table_exists("nonexistent") is False
    db.execute("CREATE TABLE my_table (id VARCHAR)")
    assert db.table_exists("my_table") is True


def test_duckdb_get_table_schema(db):
    """get_table_schema returns correct column defs."""
    db.execute("CREATE TABLE schema_test (id VARCHAR NOT NULL, score DOUBLE, name VARCHAR)")
    schema = db.get_table_schema("schema_test")
    assert isinstance(schema, TableSchema)
    assert len(schema.columns) == 3
    assert "id" in schema
    assert "score" in schema


def test_duckdb_row_count(db):
    """row_count returns correct count."""
    db.execute("CREATE TABLE count_test (id VARCHAR)")
    db.execute("INSERT INTO count_test VALUES ('a'), ('b'), ('c')")
    assert db.row_count("count_test") == 3


def test_duckdb_row_count_empty(db):
    """row_count returns 0 for empty table."""
    db.execute("CREATE TABLE empty_test (id VARCHAR)")
    assert db.row_count("empty_test") == 0


# -- BQ function shims --

def test_farm_fingerprint_shim(db):
    """FARM_FINGERPRINT shim produces deterministic hashes."""
    rows = db.execute_and_fetch(
        "SELECT FARM_FINGERPRINT('hello') AS h1, FARM_FINGERPRINT('hello') AS h2"
    )
    assert rows[0]["h1"] == rows[0]["h2"]  # deterministic


def test_farm_fingerprint_different_inputs(db):
    """FARM_FINGERPRINT shim produces different hashes for different inputs."""
    rows = db.execute_and_fetch(
        "SELECT FARM_FINGERPRINT('hello') AS h1, FARM_FINGERPRINT('world') AS h2"
    )
    assert rows[0]["h1"] != rows[0]["h2"]


def test_safe_divide_shim(db):
    """SAFE_DIVIDE shim returns NULL on zero denominator."""
    rows = db.execute_and_fetch(
        "SELECT SAFE_DIVIDE(10, 2) AS ok, SAFE_DIVIDE(10, 0) AS zero_div"
    )
    assert rows[0]["ok"] == 5.0
    assert rows[0]["zero_div"] is None


def test_safe_divide_null_denominator(db):
    """SAFE_DIVIDE shim returns NULL on NULL denominator."""
    rows = db.execute_and_fetch("SELECT SAFE_DIVIDE(10, NULL) AS result")
    assert rows[0]["result"] is None


# -- SQL adaptation --

def test_adapt_removes_backticks(db):
    """Backtick-quoted identifiers are adapted for DuckDB."""
    db.execute("CREATE TABLE adapt_test (id VARCHAR, name VARCHAR)")
    db.execute("INSERT INTO adapt_test VALUES ('1', 'Alice')")
    # This SQL uses backticks (BQ style) — should work after adaptation
    rows = db.execute_and_fetch("SELECT * FROM `adapt_test`")
    assert len(rows) == 1


def test_adapt_fq_table_names(db):
    """Fully-qualified BQ table names are reduced to local names."""
    db.execute("CREATE TABLE my_table (x VARCHAR)")
    db.execute("INSERT INTO my_table VALUES ('test')")
    # BQ-style fully-qualified name
    rows = db.execute_and_fetch('SELECT * FROM `proj.dataset.my_table`')
    assert len(rows) == 1


def test_create_table_from_data(db):
    """create_table_from_data populates a table from dicts."""
    data = [
        {"id": "1", "name": "Alice"},
        {"id": "2", "name": "Bob"},
    ]
    db.create_table_from_data("people", data)
    assert db.row_count("people") == 2


def test_execute_script_multiple_statements(db):
    """execute_script handles multiple semicolon-separated statements."""
    script = """
    CREATE TABLE s1 (id VARCHAR);
    INSERT INTO s1 VALUES ('a');
    INSERT INTO s1 VALUES ('b');
    """
    db.execute_script(script)
    assert db.row_count("s1") == 2


def test_execute_script_and_fetch_returns_last(db):
    """execute_script_and_fetch returns the last SELECT result."""
    script = """
    CREATE TABLE sf (id VARCHAR, val INTEGER);
    INSERT INTO sf VALUES ('a', 1);
    INSERT INTO sf VALUES ('b', 2);
    SELECT id, val FROM sf ORDER BY id;
    """
    rows = db.execute_script_and_fetch(script)
    assert len(rows) == 2
    assert rows[0]["id"] == "a"

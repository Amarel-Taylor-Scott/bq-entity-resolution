"""Integration test: compound detection feature functions execute in DuckDB.

Verifies that the compound detection SQL expressions produce correct results
against real data using the DuckDB backend.
"""

from __future__ import annotations

import pytest

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

# Try importing DuckDB — skip if not available
duckdb = pytest.importorskip("duckdb")


# Sample names covering all compound patterns + non-compounds
SAMPLE_NAMES = [
    ("Mr. and Mrs. Smith", "title_pair", 1),
    ("Mr. & Mrs. Johnson", "title_pair", 1),
    ("Jane and Joe Smith", "conjunction", 1),
    ("Jane & Joe", "conjunction", 1),
    ("Jane + Joe", "conjunction", 1),
    ("The Johnson Family", "family", 1),
    ("John/Jane", "slash", 1),
    ("John / Jane Smith", "slash", 1),
    ("John Smith", None, 0),
    ("Jane Doe", None, 0),
    ("Robert", None, 0),
    ("Dr. Smith", None, 0),
]


@pytest.fixture
def db():
    """Create an in-memory DuckDB connection with test data."""
    conn = duckdb.connect(":memory:")
    # Create test table
    conn.execute(
        "CREATE TABLE test_names (id INT, first_name VARCHAR)"
    )
    for i, (name, _, _) in enumerate(SAMPLE_NAMES):
        conn.execute(
            "INSERT INTO test_names VALUES (?, ?)", [i, name]
        )
    return conn


class TestIsCompoundNameDuckDB:
    """Test is_compound_name function with DuckDB execution."""

    def test_detects_all_compound_names(self, db):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["first_name"])
        # DuckDB uses different regex syntax — adapt for DuckDB
        # Replace REGEXP_CONTAINS with regexp_matches
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS is_compound FROM test_names ORDER BY id"
        ).fetchall()

        for (name, expected_pattern, expected_flag), (result_name, result_flag) in zip(
            SAMPLE_NAMES, results
        ):
            assert result_flag == expected_flag, (
                f"Expected is_compound={expected_flag} for '{name}', got {result_flag}"
            )


class TestCompoundPatternDuckDB:
    """Test compound_pattern function with DuckDB execution."""

    def test_classifies_patterns_correctly(self, db):
        expr = FEATURE_FUNCTIONS["compound_pattern"](["first_name"])
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS pattern FROM test_names ORDER BY id"
        ).fetchall()

        for (name, expected_pattern, _), (result_name, result_pattern) in zip(
            SAMPLE_NAMES, results
        ):
            assert result_pattern == expected_pattern, (
                f"Expected pattern='{expected_pattern}' for '{name}', "
                f"got '{result_pattern}'"
            )


class TestExtractCompoundNamesDuckDB:
    """Test extract_compound_first/second with DuckDB execution."""

    def test_extract_first_from_conjunction(self, db):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["first_name"])
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS extracted "
            f"FROM test_names WHERE first_name = 'Jane and Joe Smith'"
        ).fetchall()
        assert len(results) == 1
        assert results[0][1] == "JANE"

    def test_extract_second_from_conjunction(self, db):
        expr = FEATURE_FUNCTIONS["extract_compound_second"](["first_name"])
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS extracted "
            f"FROM test_names WHERE first_name = 'Jane and Joe Smith'"
        ).fetchall()
        assert len(results) == 1
        assert results[0][1] == "JOE"

    def test_extract_first_from_slash(self, db):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["first_name"])
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS extracted "
            f"FROM test_names WHERE first_name = 'John/Jane'"
        ).fetchall()
        assert len(results) == 1
        assert results[0][1] == "JOHN"

    def test_extract_second_from_slash(self, db):
        expr = FEATURE_FUNCTIONS["extract_compound_second"](["first_name"])
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS extracted "
            f"FROM test_names WHERE first_name = 'John/Jane'"
        ).fetchall()
        assert len(results) == 1
        assert results[0][1] == "JANE"

    def test_extract_returns_null_for_non_compound(self, db):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["first_name"])
        adapted = _adapt_for_duckdb(expr)
        results = db.execute(
            f"SELECT first_name, {adapted} AS extracted "
            f"FROM test_names WHERE first_name = 'John Smith'"
        ).fetchall()
        assert len(results) == 1
        assert results[0][1] is None


def _adapt_for_duckdb(sql: str) -> str:
    """Adapt BigQuery SQL to DuckDB syntax.

    Converts:
    - REGEXP_CONTAINS(col, pattern) -> regexp_matches(col, pattern)
    - REGEXP_EXTRACT(col, pattern) -> regexp_extract(col, pattern, 1)
    - r'...' raw string syntax -> '...' (DuckDB doesn't use r prefix)
    """
    import re

    # Remove r'' raw string prefix — DuckDB uses plain strings
    sql = re.sub(r"\br'", "'", sql)
    # REGEXP_CONTAINS -> regexp_matches
    sql = sql.replace("REGEXP_CONTAINS", "regexp_matches")
    # REGEXP_EXTRACT -> regexp_extract with group index 1
    # BigQuery returns first capture group by default; DuckDB needs explicit index
    sql = sql.replace("REGEXP_EXTRACT", "regexp_extract")
    # Add group index to regexp_extract calls: find calls ending with 'pattern')
    # and insert , 1 before the closing paren. Uses non-greedy match to handle
    # nested parens like regexp_extract(UPPER(col), 'pattern').
    sql = re.sub(
        r"regexp_extract\((.+?),\s*('[^']*')\)",
        r"regexp_extract(\1, \2, 1)",
        sql,
    )
    return sql

"""Tests for DuckDB SQL adaptation parity.

Tests type mapping (NUMERIC, BIGNUMERIC) and scripting detection
(line-start anchoring for DECLARE/BEGIN/WHILE).
"""

from __future__ import annotations

from bq_entity_resolution.backends.duckdb.sql_adapter import adapt_sql
from bq_entity_resolution.pipeline.executor import _is_script_block  # noqa: F401

# ---------------------------------------------------------------------------
# Type adaptation: NUMERIC -> DECIMAL(38, 9)
# ---------------------------------------------------------------------------

class TestNumericTypeAdaptation:
    """NUMERIC and BIGNUMERIC must map to DuckDB DECIMAL types."""

    def test_numeric_maps_to_decimal_38_9(self):
        sql = "CAST(amount AS NUMERIC)"
        result = adapt_sql(sql)
        assert "DECIMAL(38, 9)" in result

    def test_bignumeric_maps_to_decimal_76_38(self):
        sql = "CAST(amount AS BIGNUMERIC)"
        result = adapt_sql(sql)
        assert "DECIMAL(76, 38)" in result

    def test_numeric_in_cast_context(self):
        # adapt_sql handles CAST ... AS NUMERIC, but not column defs
        # This test verifies that AS NUMERIC in CAST context is rewritten
        result = adapt_sql("SELECT CAST(x AS NUMERIC) FROM t")
        assert "DECIMAL(38, 9)" in result

    def test_float64_maps_to_double(self):
        sql = "CAST(score AS FLOAT64)"
        result = adapt_sql(sql)
        assert "AS DOUBLE" in result

    def test_int64_maps_to_bigint(self):
        sql = "CAST(id AS INT64)"
        result = adapt_sql(sql)
        assert "AS BIGINT" in result

    def test_string_maps_to_varchar(self):
        sql = "CAST(name AS STRING)"
        result = adapt_sql(sql)
        assert "AS VARCHAR" in result

    def test_numeric_not_in_column_name(self):
        """NUMERIC in a column name should not be rewritten."""
        sql = "SELECT numeric_value FROM t"
        result = adapt_sql(sql)
        # The word "numeric_value" should survive (no AS keyword before it)
        assert "numeric_value" in result

    def test_multiple_casts(self):
        """Multiple type casts in a single query."""
        sql = (
            "SELECT CAST(a AS NUMERIC), CAST(b AS BIGNUMERIC), "
            "CAST(c AS FLOAT64), CAST(d AS INT64)"
        )
        result = adapt_sql(sql)
        assert "DECIMAL(38, 9)" in result
        assert "DECIMAL(76, 38)" in result
        assert "DOUBLE" in result
        assert "BIGINT" in result


# ---------------------------------------------------------------------------
# Scripting detection: line-start anchoring
# ---------------------------------------------------------------------------

class TestScriptBlockDetection:
    """_is_script_block uses line-start anchoring to avoid false positives."""

    def test_declare_at_line_start(self):
        sql = "DECLARE i INT64 DEFAULT 0;\nSELECT 1;"
        assert _is_script_block(sql) is True

    def test_declare_with_leading_whitespace(self):
        sql = "  DECLARE i INT64;\nSELECT 1;"
        assert _is_script_block(sql) is True

    def test_declare_mid_line_not_detected(self):
        """DECLARE appearing mid-line (e.g., in a comment or string) should not trigger."""
        sql = "SELECT 'DECLARE is a keyword' FROM t"
        assert _is_script_block(sql) is False

    def test_begin_at_line_start(self):
        sql = "BEGIN\n  SELECT 1;\nEND;"
        assert _is_script_block(sql) is True

    def test_while_at_line_start(self):
        sql = "WHILE i < 10 DO\n  SET i = i + 1;\nEND WHILE;"
        assert _is_script_block(sql) is True

    def test_set_at_line_start(self):
        sql = "SET x = 42;"
        assert _is_script_block(sql) is True

    def test_regular_select_not_detected(self):
        sql = "SELECT * FROM customers WHERE status = 'active'"
        assert _is_script_block(sql) is False

    def test_create_table_not_detected(self):
        sql = "CREATE TABLE IF NOT EXISTS t (id INT64)"
        assert _is_script_block(sql) is False

    def test_insert_not_detected(self):
        sql = "INSERT INTO t (id, name) VALUES (1, 'test')"
        assert _is_script_block(sql) is False

    def test_multiline_script(self):
        sql = (
            "DECLARE i INT64 DEFAULT 0;\n"
            "WHILE i < 10 DO\n"
            "  SET i = i + 1;\n"
            "END WHILE;"
        )
        assert _is_script_block(sql) is True

    def test_declare_in_column_alias_not_detected(self):
        """Column named 'declared_at' should not trigger false positive."""
        sql = "SELECT declared_at FROM events"
        assert _is_script_block(sql) is False

    def test_comment_with_declare_not_detected(self):
        """DECLARE inside -- comment may be on its own line, but that's
        actually a scripting block in BQ. The regex matches line-start DECLARE
        regardless, which is the correct behavior for comments that look like scripts."""
        # This tests that mid-line DECLARE in a SELECT context doesn't match
        sql = "SELECT col /* DECLARE */ FROM t"
        assert _is_script_block(sql) is False

    def test_set_with_column_reference(self):
        """SET at line start with variable assignment."""
        sql = "SET total_count = 0;"
        assert _is_script_block(sql) is True

    def test_set_in_update_not_false_positive(self):
        """UPDATE ... SET should not trigger because SET follows UPDATE, not at line start."""
        sql = "UPDATE t SET name = 'test' WHERE id = 1"
        # SET here is preceded by non-whitespace, but the regex looks for line-start SET
        # In this single-line case, SET is mid-line, so should not match
        assert _is_script_block(sql) is False

    def test_empty_sql(self):
        assert _is_script_block("") is False

    def test_whitespace_only(self):
        assert _is_script_block("   \n  \n  ") is False


# ---------------------------------------------------------------------------
# Backtick stripping
# ---------------------------------------------------------------------------

class TestBacktickStripping:
    """adapt_sql strips BigQuery backtick-quoted table names."""

    def test_three_part_name_reduced_to_table(self):
        sql = "SELECT * FROM `proj.dataset.table_name`"
        result = adapt_sql(sql)
        assert "table_name" in result
        assert "`" not in result

    def test_two_part_name_reduced_to_function(self):
        sql = "SELECT `er_udfs.jaro_winkler`(a, b)"
        result = adapt_sql(sql)
        assert "jaro_winkler" in result
        assert "`" not in result


# ---------------------------------------------------------------------------
# Other BQ -> DuckDB rewrites
# ---------------------------------------------------------------------------

class TestOtherRewrites:
    """Test various BQ -> DuckDB SQL rewrites."""

    def test_safe_cast_becomes_try_cast(self):
        sql = "SELECT SAFE_CAST(x AS BIGINT)"
        result = adapt_sql(sql)
        assert "TRY_CAST" in result
        assert "SAFE_CAST" not in result

    def test_except_becomes_exclude(self):
        sql = "SELECT * EXCEPT(internal_id) FROM t"
        result = adapt_sql(sql)
        assert "EXCLUDE" in result
        assert "EXCEPT" not in result

    def test_current_timestamp_rewrite(self):
        sql = "SELECT CURRENT_TIMESTAMP() AS ts"
        result = adapt_sql(sql)
        assert "current_timestamp" in result
        assert "CURRENT_TIMESTAMP()" not in result

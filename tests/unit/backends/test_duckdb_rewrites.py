"""Tests for DuckDB SQL adaptation rewrites added in the audit fixes.

Covers: COUNTIF, TIMESTAMP_DIFF, TO_JSON_STRING(STRUCT(...)),
FIRST_VALUE IGNORE NULLS.
"""

import pytest

from bq_entity_resolution.backends.duckdb import DuckDBBackend


@pytest.fixture
def db():
    """Fresh in-memory DuckDB backend with shims registered."""
    return DuckDBBackend(":memory:")


class TestCountifMacro:
    def test_countif_true_conditions(self, db):
        """COUNTIF counts rows where condition is true."""
        db.execute("CREATE TABLE cf_test (val BIGINT)")
        for v in [1, 2, 3, 4, 5]:
            db.execute(f"INSERT INTO cf_test VALUES ({v})")
        rows = db.execute_and_fetch(
            "SELECT COUNTIF(val > 3) AS cnt FROM cf_test"
        )
        assert rows[0]["cnt"] == 2

    def test_countif_no_matches(self, db):
        db.execute("CREATE TABLE cf_empty (val BIGINT)")
        db.execute("INSERT INTO cf_empty VALUES (1)")
        rows = db.execute_and_fetch(
            "SELECT COUNTIF(val > 100) AS cnt FROM cf_empty"
        )
        assert rows[0]["cnt"] == 0

    def test_countif_all_match(self, db):
        db.execute("CREATE TABLE cf_all (val BIGINT)")
        for v in [10, 20, 30]:
            db.execute(f"INSERT INTO cf_all VALUES ({v})")
        rows = db.execute_and_fetch(
            "SELECT COUNTIF(val > 0) AS cnt FROM cf_all"
        )
        assert rows[0]["cnt"] == 3

    def test_countif_with_boolean_column(self, db):
        db.execute("CREATE TABLE cf_bool (is_match BOOLEAN)")
        db.execute("INSERT INTO cf_bool VALUES (true)")
        db.execute("INSERT INTO cf_bool VALUES (false)")
        db.execute("INSERT INTO cf_bool VALUES (true)")
        rows = db.execute_and_fetch(
            "SELECT COUNTIF(is_match) AS cnt FROM cf_bool"
        )
        assert rows[0]["cnt"] == 2

    def test_countif_with_negation(self, db):
        """COUNTIF(NOT condition) counts non-matching rows."""
        db.execute("CREATE TABLE cf_neg (is_match BOOLEAN)")
        db.execute("INSERT INTO cf_neg VALUES (true)")
        db.execute("INSERT INTO cf_neg VALUES (false)")
        db.execute("INSERT INTO cf_neg VALUES (true)")
        rows = db.execute_and_fetch(
            "SELECT COUNTIF(NOT is_match) AS cnt FROM cf_neg"
        )
        assert rows[0]["cnt"] == 1


class TestTimestampDiffRewrite:
    def test_timestamp_diff_day(self, db):
        """TIMESTAMP_DIFF(ts1, ts2, DAY) rewritten and produces correct result."""
        sql = (
            "SELECT TIMESTAMP_DIFF("
            "TIMESTAMP '2024-01-10 00:00:00', "
            "TIMESTAMP '2024-01-01 00:00:00', "
            "DAY) AS d"
        )
        adapted = db._adapt_sql(sql)
        assert "date_diff('day'" in adapted
        rows = db.execute_and_fetch(sql)
        assert rows[0]["d"] == 9

    def test_timestamp_diff_hour(self, db):
        sql = (
            "SELECT TIMESTAMP_DIFF("
            "TIMESTAMP '2024-01-01 12:00:00', "
            "TIMESTAMP '2024-01-01 00:00:00', "
            "HOUR) AS h"
        )
        adapted = db._adapt_sql(sql)
        assert "date_diff('hour'" in adapted
        rows = db.execute_and_fetch(sql)
        assert rows[0]["h"] == 12

    def test_timestamp_diff_second(self, db):
        sql = (
            "SELECT TIMESTAMP_DIFF("
            "TIMESTAMP '2024-01-01 00:01:00', "
            "TIMESTAMP '2024-01-01 00:00:00', "
            "SECOND) AS s"
        )
        rows = db.execute_and_fetch(sql)
        assert rows[0]["s"] == 60

    def test_timestamp_diff_arg_reorder(self, db):
        """Arguments are reordered: BQ(d1,d2,unit) → DuckDB(unit,d2,d1)."""
        sql = "SELECT TIMESTAMP_DIFF(x, y, DAY) AS d"
        adapted = db._adapt_sql(sql)
        # In DuckDB, d2 comes before d1
        assert "date_diff('day', y, x)" in adapted


class TestToJsonStringRewrite:
    def test_to_json_string_struct_adaptation(self, db):
        """TO_JSON_STRING(STRUCT(cols)) is rewritten to CAST(struct_pack(cols) AS VARCHAR)."""
        sql = "SELECT TO_JSON_STRING(STRUCT(1 AS a, 'hello' AS b)) AS j"
        adapted = db._adapt_sql(sql)
        assert "struct_pack" in adapted
        assert "TO_JSON_STRING" not in adapted
        assert "CAST(" in adapted

    def test_to_json_string_execution_with_named_fields(self, db):
        """struct_pack with DuckDB := syntax executes correctly."""
        # DuckDB struct_pack uses := for named fields
        rows = db.execute_and_fetch(
            "SELECT CAST(struct_pack(a := 1, b := 'hello') AS VARCHAR) AS j"
        )
        result = rows[0]["j"]
        assert isinstance(result, str)
        assert "hello" in result

    def test_to_json_string_preserves_other_functions(self, db):
        """TO_JSON_STRING rewrite only applies to STRUCT(...) patterns."""
        sql = "SELECT CAST(42 AS VARCHAR) AS v"
        adapted = db._adapt_sql(sql)
        assert adapted == sql  # No change


class TestFirstValueIgnoreNulls:
    def test_first_value_ignore_nulls(self, db):
        """FIRST_VALUE with IGNORE NULLS skips NULL values."""
        db.execute(
            "CREATE TABLE fv_test (grp VARCHAR, val VARCHAR, priority BIGINT)"
        )
        db.execute("INSERT INTO fv_test VALUES ('A', NULL, 1)")
        db.execute("INSERT INTO fv_test VALUES ('A', 'found', 2)")
        db.execute("INSERT INTO fv_test VALUES ('A', 'also', 3)")
        rows = db.execute_and_fetch(
            "SELECT DISTINCT grp, "
            "FIRST_VALUE(val IGNORE NULLS) OVER ("
            "  PARTITION BY grp ORDER BY priority "
            "  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING"
            ") AS best_val "
            "FROM fv_test"
        )
        assert rows[0]["best_val"] == "found"

    def test_first_value_all_null(self, db):
        """FIRST_VALUE IGNORE NULLS returns NULL when all values are NULL."""
        db.execute(
            "CREATE TABLE fv_null (grp VARCHAR, val VARCHAR, priority BIGINT)"
        )
        db.execute("INSERT INTO fv_null VALUES ('A', NULL, 1)")
        db.execute("INSERT INTO fv_null VALUES ('A', NULL, 2)")
        rows = db.execute_and_fetch(
            "SELECT DISTINCT grp, "
            "FIRST_VALUE(val IGNORE NULLS) OVER ("
            "  PARTITION BY grp ORDER BY priority "
            "  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING"
            ") AS best_val "
            "FROM fv_null"
        )
        assert rows[0]["best_val"] is None

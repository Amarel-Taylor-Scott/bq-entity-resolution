"""Tests for UDF SQL builder."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.udf import build_jaro_winkler_udf_sql


class TestBuildJaroWinklerUdfSql:
    """Tests for build_jaro_winkler_udf_sql."""

    def test_returns_sql_expression(self):
        result = build_jaro_winkler_udf_sql("proj.dataset")
        sql = result.render()
        assert "CREATE OR REPLACE FUNCTION" in sql

    def test_creates_function_in_correct_dataset(self):
        sql = build_jaro_winkler_udf_sql("proj.my_udfs").render()
        assert "proj.my_udfs.jaro_winkler" in sql

    def test_function_returns_float64(self):
        sql = build_jaro_winkler_udf_sql("proj.d").render()
        assert "RETURNS FLOAT64" in sql

    def test_uses_javascript_language(self):
        sql = build_jaro_winkler_udf_sql("proj.d").render()
        assert "LANGUAGE js" in sql

    def test_includes_winkler_modification(self):
        sql = build_jaro_winkler_udf_sql("proj.d").render()
        # Winkler prefix bonus
        assert "0.1" in sql
        assert "prefix" in sql

    def test_handles_null_inputs(self):
        sql = build_jaro_winkler_udf_sql("proj.d").render()
        assert "!s1 || !s2" in sql
        assert "return 0.0" in sql

    def test_handles_exact_match(self):
        sql = build_jaro_winkler_udf_sql("proj.d").render()
        assert "s1 === s2" in sql
        assert "return 1.0" in sql

    def test_includes_transposition_counting(self):
        sql = build_jaro_winkler_udf_sql("proj.d").render()
        assert "transpositions" in sql

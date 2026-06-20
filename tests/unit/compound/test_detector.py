"""Tests for CompoundDetector SQL generation."""

from __future__ import annotations

from bq_entity_resolution.compound.detector import (
    CompoundDetectionConfig,
    CompoundDetector,
)


class TestCompoundDetector:
    def test_default_config(self):
        det = CompoundDetector()
        assert det.config.name_column == "first_name"
        assert det.config.flag_column == "is_compound_name"

    def test_detection_expression_returns_case(self):
        det = CompoundDetector()
        expr = det.detection_expression("name_col")
        assert "CASE WHEN" in expr
        assert "name_col" in expr
        assert "THEN 1 ELSE 0 END" in expr

    def test_detection_expression_checks_conjunctions(self):
        det = CompoundDetector()
        expr = det.detection_expression("first_name")
        assert "REGEXP_CONTAINS" in expr
        assert "AND" in expr

    def test_detection_expression_checks_title_pairs(self):
        det = CompoundDetector()
        expr = det.detection_expression("first_name")
        # Should check for Mr/Mrs patterns
        assert "MR" in expr
        assert "MRS" in expr

    def test_detection_expression_checks_family(self):
        det = CompoundDetector()
        expr = det.detection_expression("first_name")
        assert "FAMILY" in expr

    def test_detection_expression_checks_slash(self):
        det = CompoundDetector()
        expr = det.detection_expression("first_name")
        assert "/" in expr

    def test_detection_uses_config_name_column(self):
        cfg = CompoundDetectionConfig(name_column="full_name")
        det = CompoundDetector(cfg)
        expr = det.detection_expression()
        assert "full_name" in expr

    def test_custom_patterns_appended(self):
        cfg = CompoundDetectionConfig(custom_patterns=[r"\\bET\\b"])
        det = CompoundDetector(cfg)
        expr = det.detection_expression("name")
        assert "ET" in expr

    def test_pattern_expression_returns_case(self):
        det = CompoundDetector()
        expr = det.pattern_expression("name_col")
        assert "CASE" in expr
        assert "'title_pair'" in expr
        assert "'family'" in expr
        assert "'slash'" in expr
        assert "'conjunction'" in expr
        assert "NULL" in expr

    def test_detection_columns_returns_dict(self):
        det = CompoundDetector()
        cols = det.detection_columns("first_name")
        assert "is_compound_name" in cols
        assert "compound_pattern" in cols
        assert "CASE WHEN" in cols["is_compound_name"]
        assert "CASE" in cols["compound_pattern"]

    def test_detection_columns_uses_custom_flag(self):
        cfg = CompoundDetectionConfig(flag_column="my_flag")
        det = CompoundDetector(cfg)
        cols = det.detection_columns()
        assert "my_flag" in cols
        assert "is_compound_name" not in cols

    def test_filter_sql_no_alias(self):
        det = CompoundDetector()
        sql = det.filter_sql()
        assert "is_compound_name = 0" in sql
        assert "IS NULL" in sql

    def test_filter_sql_with_alias(self):
        det = CompoundDetector()
        sql = det.filter_sql("t")
        assert "t.is_compound_name = 0" in sql
        assert "t.is_compound_name IS NULL" in sql

    def test_filter_sql_custom_flag(self):
        cfg = CompoundDetectionConfig(flag_column="compound_flag")
        det = CompoundDetector(cfg)
        sql = det.filter_sql("src")
        assert "src.compound_flag = 0" in sql

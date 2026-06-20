"""Tests for placeholder tracking SQL builders."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.placeholder_tracking import (
    PlaceholderScanColumn,
    PlaceholderScanParams,
    build_create_placeholder_table_sql,
    build_placeholder_scan_sql,
)


class TestBuildCreatePlaceholderTableSql:
    """Tests for build_create_placeholder_table_sql."""

    def test_returns_sql_expression(self):
        result = build_create_placeholder_table_sql(
            "proj.meta.placeholder_log"
        )
        sql = result.render()
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "proj.meta.placeholder_log" in sql

    def test_includes_required_columns(self):
        sql = build_create_placeholder_table_sql(
            "proj.meta.placeholder_log"
        ).render()
        assert "run_id STRING" in sql
        assert "source_name STRING" in sql
        assert "column_name STRING" in sql
        assert "placeholder_value STRING" in sql
        assert "match_count INT64" in sql
        assert "pattern_type STRING" in sql
        assert "detected_at TIMESTAMP" in sql

    def test_includes_partitioning_and_clustering(self):
        sql = build_create_placeholder_table_sql(
            "proj.meta.placeholder_log"
        ).render()
        assert "PARTITION BY DATE(detected_at)" in sql
        assert "CLUSTER BY run_id, source_name" in sql

    def test_rejects_invalid_table_ref(self):
        with pytest.raises(ValueError):
            build_create_placeholder_table_sql("bad")


class TestBuildPlaceholderScanSql:
    """Tests for build_placeholder_scan_sql."""

    def _make_params(self, **overrides):
        defaults = {
            "target_table": "proj.meta.placeholder_log",
            "source_table": "proj.silver.featured",
            "run_id": "run-1",
            "source_name": "customers",
            "scan_columns": [
                PlaceholderScanColumn(
                    column_name="phone",
                    pattern_type="phone",
                    detection_sql="is_placeholder_phone",
                ),
            ],
            "min_count": 2,
        }
        defaults.update(overrides)
        return PlaceholderScanParams(**defaults)

    def test_returns_sql_expression(self):
        params = self._make_params()
        result = build_placeholder_scan_sql(params)
        sql = result.render()
        assert "INSERT INTO" in sql

    def test_includes_target_table(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "proj.meta.placeholder_log" in sql

    def test_selects_from_source(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "proj.silver.featured" in sql

    def test_includes_run_id(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "'run-1'" in sql

    def test_includes_source_name(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "'customers'" in sql

    def test_includes_column_name(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "'phone'" in sql

    def test_includes_pattern_type(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "'phone'" in sql

    def test_having_clause(self):
        params = self._make_params(min_count=5)
        sql = build_placeholder_scan_sql(params).render()
        assert "HAVING COUNT(*) >= 5" in sql

    def test_multiple_columns_union_all(self):
        params = self._make_params(
            scan_columns=[
                PlaceholderScanColumn(
                    column_name="phone",
                    pattern_type="phone",
                    detection_sql="is_ph_phone",
                ),
                PlaceholderScanColumn(
                    column_name="email",
                    pattern_type="email",
                    detection_sql="is_ph_email",
                ),
            ]
        )
        sql = build_placeholder_scan_sql(params).render()
        assert "UNION ALL" in sql
        assert "'phone'" in sql
        assert "'email'" in sql

    def test_filters_null_values(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "IS NOT NULL" in sql

    def test_uses_detection_sql(self):
        params = self._make_params()
        sql = build_placeholder_scan_sql(params).render()
        assert "is_placeholder_phone = 1" in sql

    def test_escapes_values(self):
        params = self._make_params(
            source_name="it's_a_source",
            run_id="run's",
        )
        sql = build_placeholder_scan_sql(params).render()
        assert "it''s_a_source" in sql
        assert "run''s" in sql

    def test_empty_scan_columns_raises(self):
        params = self._make_params(scan_columns=[])
        with pytest.raises(ValueError, match="No scan columns"):
            build_placeholder_scan_sql(params)

    def test_rejects_invalid_target_table(self):
        params = self._make_params(target_table="bad")
        with pytest.raises(ValueError):
            build_placeholder_scan_sql(params)

    def test_rejects_invalid_source_table(self):
        params = self._make_params(source_table="bad")
        with pytest.raises(ValueError):
            build_placeholder_scan_sql(params)


class TestPlaceholderScanColumnDataclass:
    """Tests for PlaceholderScanColumn frozen dataclass."""

    def test_frozen(self):
        col = PlaceholderScanColumn(
            column_name="phone",
            pattern_type="phone",
            detection_sql="expr",
        )
        with pytest.raises(AttributeError):
            col.column_name = "new"  # type: ignore[misc]

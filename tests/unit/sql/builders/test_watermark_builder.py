"""Tests for watermark and checkpoint SQL builders."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.watermark import (
    build_create_checkpoint_table_sql,
    build_create_watermark_table_sql,
    build_read_watermark_sql,
    build_update_watermark_sql,
)


class TestBuildCreateWatermarkTableSql:
    """Tests for build_create_watermark_table_sql."""

    def test_returns_sql_expression(self):
        result = build_create_watermark_table_sql("proj.meta.watermarks")
        sql = result.render()
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "proj.meta.watermarks" in sql

    def test_includes_required_columns(self):
        sql = build_create_watermark_table_sql("proj.meta.watermarks").render()
        assert "source_name STRING" in sql
        assert "cursor_column STRING" in sql
        assert "cursor_value STRING" in sql
        assert "cursor_type STRING" in sql
        assert "updated_at TIMESTAMP" in sql
        assert "run_id STRING" in sql
        assert "is_current BOOL" in sql

    def test_includes_partitioning_and_clustering(self):
        sql = build_create_watermark_table_sql("proj.meta.watermarks").render()
        assert "PARTITION BY DATE(updated_at)" in sql
        assert "CLUSTER BY source_name" in sql


class TestBuildReadWatermarkSql:
    """Tests for build_read_watermark_sql."""

    def test_returns_sql_expression(self):
        result = build_read_watermark_sql("proj.meta.watermarks", "customers")
        sql = result.render()
        assert "SELECT" in sql
        assert "cursor_column" in sql

    def test_filters_by_source_and_current(self):
        sql = build_read_watermark_sql("proj.meta.watermarks", "my_source").render()
        assert "source_name = 'my_source'" in sql
        assert "is_current = TRUE" in sql

    def test_escapes_source_name(self):
        sql = build_read_watermark_sql("proj.meta.watermarks", "it's_a_source").render()
        assert "it''s_a_source" in sql


class TestBuildUpdateWatermarkSql:
    """Tests for build_update_watermark_sql."""

    def test_returns_sql_expression(self):
        result = build_update_watermark_sql(
            table="proj.meta.watermarks",
            source_name="customers",
            cursors=[{
                "column": "updated_at",
                "value": "2024-01-01T00:00:00Z",
                "type": "timestamp",
            }],
            run_id="run-123",
            now="2024-01-02T00:00:00Z",
        )
        sql = result.render()
        assert "BEGIN TRANSACTION" in sql
        assert "COMMIT TRANSACTION" in sql

    def test_marks_old_watermarks_not_current(self):
        sql = build_update_watermark_sql(
            table="proj.meta.watermarks",
            source_name="src",
            cursors=[{"column": "c", "value": "v", "type": "t"}],
            run_id="r",
            now="n",
        ).render()
        assert "SET is_current = FALSE" in sql
        assert "source_name = 'src'" in sql

    def test_inserts_new_watermark_values(self):
        sql = build_update_watermark_sql(
            table="proj.meta.watermarks",
            source_name="src",
            cursors=[
                {"column": "col1", "value": "val1", "type": "string"},
                {"column": "col2", "value": "val2", "type": "timestamp"},
            ],
            run_id="run-1",
            now="2024-01-01",
        ).render()
        assert "INSERT INTO" in sql
        assert "col1" in sql
        assert "col2" in sql
        assert "val1" in sql
        assert "val2" in sql

    def test_escapes_values(self):
        sql = build_update_watermark_sql(
            table="proj.meta.watermarks",
            source_name="it's",
            cursors=[{"column": "c", "value": "val'ue", "type": "t"}],
            run_id="run's",
            now="now",
        ).render()
        assert "it''s" in sql
        assert "val''ue" in sql
        assert "run''s" in sql


class TestBuildCreateCheckpointTableSql:
    """Tests for build_create_checkpoint_table_sql."""

    def test_returns_sql_expression(self):
        result = build_create_checkpoint_table_sql("proj.meta.checkpoints")
        sql = result.render()
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "proj.meta.checkpoints" in sql

    def test_includes_required_columns(self):
        sql = build_create_checkpoint_table_sql("proj.meta.checkpoints").render()
        assert "run_id STRING" in sql
        assert "stage_name STRING" in sql
        assert "completed_at TIMESTAMP" in sql
        assert "status STRING" in sql

    def test_includes_partitioning_and_clustering(self):
        sql = build_create_checkpoint_table_sql("proj.meta.checkpoints").render()
        assert "PARTITION BY DATE(completed_at)" in sql
        assert "CLUSTER BY run_id" in sql

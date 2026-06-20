"""Tests for job tracking SQL builders."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.job_tracking import (
    JobDetail,
    RunComparisonParams,
    build_create_job_tracking_table_sql,
    build_insert_job_details_sql,
    build_run_comparison_sql,
    compute_sql_hash,
)


class TestComputeSqlHash:
    """Tests for compute_sql_hash."""

    def test_returns_16_char_hex(self):
        result = compute_sql_hash("SELECT 1")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        a = compute_sql_hash("SELECT * FROM t")
        b = compute_sql_hash("SELECT * FROM t")
        assert a == b

    def test_different_sql_different_hash(self):
        a = compute_sql_hash("SELECT 1")
        b = compute_sql_hash("SELECT 2")
        assert a != b


class TestBuildCreateJobTrackingTableSql:
    """Tests for build_create_job_tracking_table_sql."""

    def test_returns_sql_expression(self):
        result = build_create_job_tracking_table_sql("proj.meta.job_details")
        sql = result.render()
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "proj.meta.job_details" in sql

    def test_includes_required_columns(self):
        sql = build_create_job_tracking_table_sql(
            "proj.meta.job_details"
        ).render()
        assert "run_id STRING" in sql
        assert "stage_name STRING" in sql
        assert "query_index INT64" in sql
        assert "job_id STRING" in sql
        assert "bytes_billed INT64" in sql
        assert "total_bytes_processed INT64" in sql
        assert "slot_milliseconds INT64" in sql
        assert "duration_seconds FLOAT64" in sql
        assert "rows_affected INT64" in sql
        assert "started_at TIMESTAMP" in sql
        assert "sql_hash STRING" in sql

    def test_includes_partitioning_and_clustering(self):
        sql = build_create_job_tracking_table_sql(
            "proj.meta.job_details"
        ).render()
        assert "PARTITION BY DATE(started_at)" in sql
        assert "CLUSTER BY run_id, stage_name" in sql

    def test_rejects_invalid_table_ref(self):
        with pytest.raises(ValueError):
            build_create_job_tracking_table_sql("bad")


class TestBuildInsertJobDetailsSql:
    """Tests for build_insert_job_details_sql."""

    def _make_detail(self, **overrides):
        defaults = {
            "stage_name": "staging",
            "query_index": 0,
            "job_id": "job-abc-123",
            "bytes_billed": 1024,
            "total_bytes_processed": 2048,
            "slot_milliseconds": 500,
            "duration_seconds": 1.5,
            "rows_affected": 100,
            "started_at": "2024-01-01T00:00:00Z",
            "sql_hash": "abcdef1234567890",
        }
        defaults.update(overrides)
        return JobDetail(**defaults)

    def test_returns_sql_expression(self):
        detail = self._make_detail()
        result = build_insert_job_details_sql(
            "proj.meta.job_details", "run-1", [detail]
        )
        sql = result.render()
        assert "INSERT INTO" in sql
        assert "proj.meta.job_details" in sql

    def test_includes_all_values(self):
        detail = self._make_detail()
        sql = build_insert_job_details_sql(
            "proj.meta.job_details", "run-1", [detail]
        ).render()
        assert "'run-1'" in sql
        assert "'staging'" in sql
        assert "job-abc-123" in sql
        assert "1024" in sql
        assert "2048" in sql
        assert "500" in sql
        assert "1.5" in sql
        assert "100" in sql
        assert "abcdef1234567890" in sql

    def test_multiple_details(self):
        details = [
            self._make_detail(stage_name="staging", query_index=0),
            self._make_detail(stage_name="features", query_index=1),
        ]
        sql = build_insert_job_details_sql(
            "proj.meta.job_details", "run-1", details
        ).render()
        assert "'staging'" in sql
        assert "'features'" in sql

    def test_null_job_id(self):
        detail = self._make_detail(job_id="")
        sql = build_insert_job_details_sql(
            "proj.meta.job_details", "run-1", [detail]
        ).render()
        assert "NULL" in sql

    def test_null_started_at(self):
        detail = self._make_detail(started_at="")
        sql = build_insert_job_details_sql(
            "proj.meta.job_details", "run-1", [detail]
        ).render()
        assert "NULL" in sql

    def test_escapes_values(self):
        detail = self._make_detail(stage_name="it's_a_stage")
        sql = build_insert_job_details_sql(
            "proj.meta.job_details", "run's", [detail]
        ).render()
        assert "it''s_a_stage" in sql
        assert "run''s" in sql

    def test_empty_details_raises(self):
        with pytest.raises(ValueError, match="No job details"):
            build_insert_job_details_sql(
                "proj.meta.job_details", "run-1", []
            )

    def test_rejects_invalid_table_ref(self):
        detail = self._make_detail()
        with pytest.raises(ValueError):
            build_insert_job_details_sql("bad", "run-1", [detail])


class TestJobDetailDataclass:
    """Tests for the JobDetail frozen dataclass."""

    def test_frozen(self):
        detail = JobDetail(
            stage_name="s", query_index=0, job_id="j",
            bytes_billed=0, total_bytes_processed=0,
            slot_milliseconds=0, duration_seconds=0.0,
            rows_affected=0, started_at="", sql_hash="",
        )
        with pytest.raises(AttributeError):
            detail.stage_name = "new"  # type: ignore[misc]


class TestRunComparisonSql:
    """Tests for run comparison SQL builder."""

    def test_generates_full_outer_join(self):
        params = RunComparisonParams(
            job_tracking_table="proj.ds.pipeline_job_details",
            run_id_a="run_20240101",
            run_id_b="run_20240102",
        )
        sql = build_run_comparison_sql(params).render()
        assert "FULL OUTER JOIN" in sql
        assert "run_a" in sql
        assert "run_b" in sql

    def test_computes_deltas(self):
        params = RunComparisonParams(
            job_tracking_table="proj.ds.pipeline_job_details",
            run_id_a="run_a",
            run_id_b="run_b",
        )
        sql = build_run_comparison_sql(params).render()
        assert "bytes_billed_delta" in sql
        assert "duration_delta" in sql
        assert "bytes_billed_pct_change" in sql

    def test_comparison_status(self):
        params = RunComparisonParams(
            job_tracking_table="proj.ds.pipeline_job_details",
            run_id_a="run_a",
            run_id_b="run_b",
        )
        sql = build_run_comparison_sql(params).render()
        assert "'NEW'" in sql
        assert "'REMOVED'" in sql
        assert "'MATCHED'" in sql

    def test_validates_table_ref(self):
        with pytest.raises(ValueError):
            RunComparisonParams(
                job_tracking_table="invalid",
                run_id_a="a",
                run_id_b="b",
            )

    def test_escapes_run_ids(self):
        params = RunComparisonParams(
            job_tracking_table="proj.ds.pipeline_job_details",
            run_id_a="run's_a",
            run_id_b="run_b",
        )
        sql = build_run_comparison_sql(params).render()
        assert "run''s_a" in sql

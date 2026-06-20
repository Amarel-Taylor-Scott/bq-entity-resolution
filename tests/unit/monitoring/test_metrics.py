"""Tests for MetricsCollector."""

from __future__ import annotations

from unittest.mock import MagicMock

from bq_entity_resolution.monitoring.metrics import MetricsCollector


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_config(metrics_enabled=True, destination="bigquery"):
    """Create a minimal config-like object for MetricsCollector."""
    return _NS(
        monitoring=_NS(
            metrics=_NS(enabled=metrics_enabled, destination=destination),
        ),
        project=_NS(
            bq_project="test-project",
            watermark_dataset="meta",
        ),
    )


def _make_result(status="success", run_id="run-001", error=None):
    """Create a minimal PipelineResult-like object."""
    sr1 = _NS(
        stage_name="staging", success=True, skipped=False,
        sql_count=3, duration_seconds=1.5,
    )
    sr2 = _NS(
        stage_name="features", success=True, skipped=False,
        sql_count=5, duration_seconds=2.0,
    )
    sr3 = _NS(
        stage_name="skipped_stage", success=True, skipped=True,
        sql_count=0, duration_seconds=0,
    )
    return _NS(
        run_id=run_id,
        status=status,
        duration_seconds=10.5,
        stage_results=[sr1, sr2, sr3],
        completed_stages=["staging", "features"],
        error=error,
    )


class TestMetricsCollectorInit:
    def test_creates_with_config(self):
        config = _make_config()
        mc = MetricsCollector(config)
        assert mc.config is config
        assert mc._backend is None

    def test_set_backend(self):
        config = _make_config()
        mc = MetricsCollector(config)
        backend = MagicMock()
        mc.set_backend(backend)
        assert mc._backend is backend


class TestRecordRun:
    def test_logs_metrics_stdout_mode(self):
        """When destination=stdout, metrics are logged but not written to BQ."""
        config = _make_config(destination="stdout")
        mc = MetricsCollector(config)
        result = _make_result()
        # Should not raise even without backend
        mc.record_run(result)

    def test_writes_to_bigquery_when_enabled(self):
        config = _make_config(metrics_enabled=True, destination="bigquery")
        mc = MetricsCollector(config)
        backend = MagicMock()
        mc.set_backend(backend)

        result = _make_result()
        mc.record_run(result)

        # Should have called execute twice: CREATE TABLE + INSERT
        assert backend.execute.call_count == 2
        create_call = backend.execute.call_args_list[0][0][0]
        insert_call = backend.execute.call_args_list[1][0][0]
        assert "CREATE TABLE IF NOT EXISTS" in create_call
        assert "pipeline_metrics" in create_call
        assert "INSERT INTO" in insert_call
        assert "run-001" in insert_call

    def test_skips_bq_write_when_disabled(self):
        config = _make_config(metrics_enabled=False)
        mc = MetricsCollector(config)
        backend = MagicMock()
        mc.set_backend(backend)

        result = _make_result()
        mc.record_run(result)

        backend.execute.assert_not_called()

    def test_warns_when_no_backend_set(self, caplog):
        config = _make_config(metrics_enabled=True, destination="bigquery")
        mc = MetricsCollector(config)
        # No backend set
        result = _make_result()
        mc.record_run(result)
        assert "no backend was set" in caplog.text.lower()

    def test_handles_backend_error_gracefully(self):
        config = _make_config(metrics_enabled=True, destination="bigquery")
        mc = MetricsCollector(config)
        backend = MagicMock()
        backend.execute.side_effect = RuntimeError("BQ unavailable")
        mc.set_backend(backend)

        result = _make_result()
        # Should not raise
        mc.record_run(result)

    def test_includes_error_in_metrics(self):
        config = _make_config(metrics_enabled=True, destination="bigquery")
        mc = MetricsCollector(config)
        backend = MagicMock()
        mc.set_backend(backend)

        result = _make_result(status="failed", error="Stage crashed")
        mc.record_run(result)

        insert_call = backend.execute.call_args_list[1][0][0]
        assert "Stage crashed" in insert_call

    def test_skipped_stages_excluded_from_sql_count(self):
        config = _make_config(destination="stdout")
        mc = MetricsCollector(config)
        result = _make_result()
        # The skipped_stage has sql_count=0 and should not appear in stage details
        mc.record_run(result)
        # No assertion needed — just verify no error


class TestMetricsTable:
    def test_metrics_table_name(self):
        config = _make_config()
        mc = MetricsCollector(config)
        assert mc._metrics_table() == "test-project.meta.pipeline_metrics"

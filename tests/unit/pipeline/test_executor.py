"""Tests for the pipeline executor."""

from datetime import UTC

import pytest

from bq_entity_resolution.backends.protocol import QueryResult
from bq_entity_resolution.pipeline.executor import (
    PipelineExecutor,
    PipelineResult,
    StageExecutionResult,
)
from bq_entity_resolution.pipeline.gates import (
    DataQualityGate,
    GateResult,
)
from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
from bq_entity_resolution.sql.expression import SQLExpression

# -- Mock backend --


class MockBackend:
    """Mock backend that records executed SQL."""

    def __init__(self, fail_on: str | None = None):
        self.executed: list[str] = []
        self._fail_on = fail_on

    @property
    def dialect(self):
        return "bigquery"

    def execute(self, sql, label=""):
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError(f"Simulated failure: {self._fail_on}")
        self.executed.append(sql)
        return QueryResult(rows_affected=10)

    def execute_script(self, sql, label=""):
        self.executed.append(sql)
        return QueryResult(rows_affected=5)

    def execute_and_fetch(self, sql, label=""):
        self.executed.append(sql)
        return [{"count": 100}]

    def table_exists(self, ref):
        return True

    def row_count(self, ref):
        return 100


# -- Helpers --


def _make_plan(stage_names, sql_per_stage=1):
    """Create a simple pipeline plan."""
    stages = []
    for name in stage_names:
        exprs = tuple(
            SQLExpression.from_raw(f"SELECT '{name}_{i}'")
            for i in range(sql_per_stage)
        )
        stages.append(StagePlan(
            stage_name=name,
            sql_expressions=exprs,
            inputs={},
            outputs={},
            dependencies=(),
        ))
    return PipelinePlan(stages=tuple(stages))


# -- Tests --


class TestPipelineExecutor:
    def test_execute_simple_plan(self):
        """Executor runs all stages in order."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)
        plan = _make_plan(["a", "b", "c"])

        result = executor.execute(plan, run_id="test_run")

        assert result.success
        assert result.status == "success"
        assert len(result.completed_stages) == 3
        assert len(backend.executed) == 3

    def test_execute_records_sql_log(self):
        """Executor records SQL in the result log (always redacted)."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)
        plan = _make_plan(["staging"])

        result = executor.execute(plan, run_id="test_run")

        assert len(result.sql_log) == 1
        assert result.sql_log[0]["stage"] == "staging"
        # SQL is always redacted; string literals are replaced
        assert "sql" in result.sql_log[0]
        assert "timestamp" in result.sql_log[0]

    def test_sql_log_redaction(self):
        """SQL log redacts string literals by default."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)
        plan = _make_plan(["staging"])

        result = executor.execute(plan, run_id="test_run")

        assert len(result.sql_log) == 1
        assert "<REDACTED>" in result.sql_log[0]["sql"]
        assert "staging_0" not in result.sql_log[0]["sql"]

    def test_skip_stages(self):
        """Executor skips specified stages."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)
        plan = _make_plan(["a", "b", "c"])

        result = executor.execute(
            plan, run_id="test_run", skip_stages={"a", "c"}
        )

        assert result.success
        assert result.completed_stages == ["b"]
        assert len(backend.executed) == 1

    def test_stage_failure_stops_pipeline(self):
        """Executor stops on stage failure and raises."""
        backend = MockBackend(fail_on="stage_b")
        executor = PipelineExecutor(backend)
        plan = _make_plan(["stage_a", "stage_b", "stage_c"])

        with pytest.raises(RuntimeError, match="stage_b"):
            executor.execute(plan, run_id="test_run")

    def test_failure_records_error(self):
        """Failed pipeline records error in result."""
        backend = MockBackend(fail_on="bad")
        executor = PipelineExecutor(backend)

        sp = StagePlan(
            stage_name="bad_stage",
            sql_expressions=(SQLExpression.from_raw("SELECT 'bad'"),),
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=(sp,))

        with pytest.raises(RuntimeError):
            executor.execute(plan, run_id="test_run")

    def test_empty_stage_no_sql(self):
        """Stage with no SQL expressions is handled gracefully."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)

        sp = StagePlan(
            stage_name="empty",
            sql_expressions=(),
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=(sp,))
        result = executor.execute(plan, run_id="test_run")

        assert result.success
        assert len(backend.executed) == 0

    def test_scripting_detected(self):
        """SQL with DECLARE + WHILE uses execute_script."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)

        scripting_sql = "DECLARE i INT64 DEFAULT 0;\nWHILE i < 10 DO\nSET i = i + 1;\nEND WHILE;"
        sp = StagePlan(
            stage_name="clustering",
            sql_expressions=(SQLExpression.from_raw(scripting_sql),),
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=(sp,))
        result = executor.execute(plan, run_id="test_run")

        assert result.success
        assert len(backend.executed) == 1
        assert "DECLARE" in backend.executed[0]

    def test_auto_generates_run_id(self):
        """Executor auto-generates run ID when not provided."""
        backend = MockBackend()
        executor = PipelineExecutor(backend)
        plan = _make_plan(["a"])

        result = executor.execute(plan)

        assert result.run_id.startswith("er_run_")


class TestQualityGateIntegration:
    def test_passing_gate(self):
        """Quality gate that passes does not affect execution."""

        class AlwaysPassGate(DataQualityGate):
            def applies_to(self, stage_name):
                return True

            def check(self, stage_name, backend, outputs):
                return GateResult(passed=True, message="OK")

        backend = MockBackend()
        executor = PipelineExecutor(backend, quality_gates=[AlwaysPassGate()])
        plan = _make_plan(["a"])

        result = executor.execute(plan, run_id="test")
        assert result.success

    def test_failing_error_gate_stops_pipeline(self):
        """Quality gate failure with severity='error' stops pipeline."""

        class AlwaysFailGate(DataQualityGate):
            def applies_to(self, stage_name):
                return True

            def check(self, stage_name, backend, outputs):
                return GateResult(
                    passed=False,
                    message="gate failed",
                    severity="error",
                )

        backend = MockBackend()
        executor = PipelineExecutor(
            backend, quality_gates=[AlwaysFailGate()]
        )
        plan = _make_plan(["a"])

        with pytest.raises(RuntimeError, match="Quality gate failed"):
            executor.execute(plan, run_id="test")

    def test_warning_gate_continues(self):
        """Quality gate with severity='warning' logs but continues."""

        class WarnGate(DataQualityGate):
            def applies_to(self, stage_name):
                return True

            def check(self, stage_name, backend, outputs):
                return GateResult(
                    passed=False,
                    message="just a warning",
                    severity="warning",
                )

        backend = MockBackend()
        executor = PipelineExecutor(backend, quality_gates=[WarnGate()])
        plan = _make_plan(["a", "b"])

        result = executor.execute(plan, run_id="test")
        assert result.success


class TestPipelineResult:
    def test_defaults(self):
        result = PipelineResult(run_id="test")
        assert result.status == "running"
        assert result.success is False
        assert result.completed_stages == []

    def test_duration(self):
        from datetime import datetime, timedelta

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(seconds=42)
        result = PipelineResult(
            run_id="test", started_at=start, finished_at=end
        )
        assert result.duration_seconds == 42.0


class TestStageExecutionResult:
    def test_defaults(self):
        r = StageExecutionResult(stage_name="test")
        assert r.success is True
        assert r.skipped is False
        assert r.error is None


class TestCostAlertingBudgetGuards:
    """Tests for per-run cumulative cost threshold enforcement."""

    def test_abort_threshold_raises_error(self):
        """PipelineCostExceededError raised when abort threshold exceeded."""
        from unittest.mock import MagicMock

        from bq_entity_resolution.exceptions import PipelineCostExceededError

        backend = MagicMock()
        # Simulate query returning 10GB billed
        qr = MagicMock()
        qr.bytes_billed = 10_000_000_000
        qr.rows_affected = 100
        qr.job_id = "j1"
        qr.total_bytes_processed = 10_000_000_000
        qr.slot_milliseconds = 500
        backend.execute.return_value = qr

        executor = PipelineExecutor(
            backend=backend,
            cost_abort_threshold_bytes=5_000_000_000,  # 5GB
        )

        plan = MagicMock()
        plan.stages = [MagicMock()]
        plan.stages[0].stage_name = "staging_test"
        plan.stages[0].sql_count = 1
        expr = MagicMock()
        expr.render.return_value = "SELECT 1"
        plan.stages[0].sql_expressions = [expr]
        plan.stages[0].outputs = {}

        with pytest.raises(PipelineCostExceededError, match="exceeds abort"):
            executor.execute(plan, run_id="test-run")

    def test_alert_threshold_logs_warning(self):
        """Warning logged when alert threshold exceeded."""
        from unittest.mock import MagicMock

        backend = MagicMock()
        qr = MagicMock()
        qr.bytes_billed = 1_000_000
        qr.rows_affected = 10
        qr.job_id = "j1"
        qr.total_bytes_processed = 1_000_000
        qr.slot_milliseconds = 100
        backend.execute.return_value = qr

        executor = PipelineExecutor(
            backend=backend,
            cost_alert_threshold_bytes=500_000,  # 500KB
        )

        plan = MagicMock()
        plan.stages = [MagicMock()]
        plan.stages[0].stage_name = "staging_test"
        plan.stages[0].sql_count = 1
        expr = MagicMock()
        expr.render.return_value = "SELECT 1"
        plan.stages[0].sql_expressions = [expr]
        plan.stages[0].outputs = {}

        executor.execute(plan, run_id="test-run")

        # Verify the alert was fired (warning logged, no exception)
        assert executor._cost_alert_fired is True
        assert executor._cumulative_bytes_billed == 1_000_000

    def test_no_threshold_no_error(self):
        """No error when thresholds are None."""
        from unittest.mock import MagicMock

        executor = PipelineExecutor(
            backend=MagicMock(),
        )
        assert executor._cost_alert_threshold is None
        assert executor._cost_abort_threshold is None
        assert executor._cumulative_bytes_billed == 0

    def test_cumulative_tracking_initialized_to_zero(self):
        """Cumulative bytes starts at 0."""
        from unittest.mock import MagicMock

        executor = PipelineExecutor(
            backend=MagicMock(),
            cost_abort_threshold_bytes=1000,
        )
        assert executor._cumulative_bytes_billed == 0
        assert executor._cost_alert_fired is False

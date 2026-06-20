"""Tests for checkpoint abort after consecutive failures."""

from __future__ import annotations

import pytest

from bq_entity_resolution.backends.protocol import QueryResult
from bq_entity_resolution.pipeline.executor import PipelineExecutor
from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
from bq_entity_resolution.sql.expression import SQLExpression

# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------

class MockBackend:
    """Backend that always succeeds."""

    def __init__(self):
        self.executed: list[str] = []

    @property
    def dialect(self):
        return "bigquery"

    def execute(self, sql, label=""):
        self.executed.append(sql)
        return QueryResult(rows_affected=1)

    def execute_script(self, sql, label=""):
        self.executed.append(sql)
        return QueryResult(rows_affected=1)


class AlwaysFailCheckpoint:
    """Checkpoint manager that always fails to persist."""

    def __init__(self):
        self.calls = 0

    def ensure_table_exists(self):
        pass

    def load_completed_stages(self, run_id):
        return set()

    def find_resumable_run(self):
        return None

    def mark_stage_complete(self, run_id, stage_name, **kwargs):
        self.calls += 1
        raise ConnectionError("Checkpoint backend unavailable")

    def mark_run_complete(self, run_id, **kwargs):
        pass


class FailThenSucceedCheckpoint:
    """Checkpoint manager that fails N times then succeeds."""

    def __init__(self, fail_count: int = 2):
        self._fail_count = fail_count
        self._attempts = 0
        self.completed_stages: list[str] = []

    def ensure_table_exists(self):
        pass

    def load_completed_stages(self, run_id):
        return set()

    def find_resumable_run(self):
        return None

    def mark_stage_complete(self, run_id, stage_name, **kwargs):
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise ConnectionError("Checkpoint backend unavailable")
        self.completed_stages.append(stage_name)

    def mark_run_complete(self, run_id, **kwargs):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(stage_names: list[str]) -> PipelinePlan:
    stages = []
    for name in stage_names:
        stages.append(StagePlan(
            stage_name=name,
            sql_expressions=(SQLExpression.from_raw(f"SELECT 1 -- {name}"),),
            inputs={},
            outputs={},
            dependencies=(),
        ))
    return PipelinePlan(stages=tuple(stages))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckpointAbort:
    """Executor aborts after 3 consecutive checkpoint failures."""

    def test_aborts_after_three_consecutive_failures(self):
        """Pipeline should abort when checkpoint fails 3 times in a row."""
        backend = MockBackend()
        checkpoint = AlwaysFailCheckpoint()
        executor = PipelineExecutor(
            backend, checkpoint_manager=checkpoint
        )
        plan = _make_plan(["stage_a", "stage_b", "stage_c", "stage_d"])

        with pytest.raises(RuntimeError, match="consecutive"):
            executor.execute(plan, run_id="test_run")

        # Should have attempted checkpoint writes for 3 stages
        assert checkpoint.calls == 3

    def test_counter_resets_on_success(self):
        """After a successful checkpoint, the failure counter resets."""
        backend = MockBackend()
        # Fails 2 times, then succeeds -- counter should reset, not abort
        checkpoint = FailThenSucceedCheckpoint(fail_count=2)
        executor = PipelineExecutor(
            backend, checkpoint_manager=checkpoint
        )
        plan = _make_plan(["stage_a", "stage_b", "stage_c", "stage_d"])

        result = executor.execute(plan, run_id="test_run")

        # Pipeline completes successfully
        assert result.success
        # stages c and d should have been checkpointed (after 2 fails on a/b)
        assert "stage_c" in checkpoint.completed_stages
        assert "stage_d" in checkpoint.completed_stages

    def test_no_checkpoint_no_abort(self):
        """Without checkpoint manager, pipeline always completes."""
        backend = MockBackend()
        executor = PipelineExecutor(backend, checkpoint_manager=None)
        plan = _make_plan(["a", "b", "c", "d"])

        result = executor.execute(plan, run_id="test_run")
        assert result.success

    def test_single_failure_continues(self):
        """One checkpoint failure should not abort."""
        backend = MockBackend()
        checkpoint = FailThenSucceedCheckpoint(fail_count=1)
        executor = PipelineExecutor(
            backend, checkpoint_manager=checkpoint
        )
        plan = _make_plan(["a", "b", "c"])

        result = executor.execute(plan, run_id="test_run")
        assert result.success

    def test_two_failures_continues(self):
        """Two consecutive checkpoint failures should not abort."""
        backend = MockBackend()
        checkpoint = FailThenSucceedCheckpoint(fail_count=2)
        executor = PipelineExecutor(
            backend, checkpoint_manager=checkpoint
        )
        plan = _make_plan(["a", "b", "c", "d"])

        result = executor.execute(plan, run_id="test_run")
        assert result.success

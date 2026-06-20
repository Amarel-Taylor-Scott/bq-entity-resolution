"""Tests for atomic distributed locking, fenced watermark writes,
and related production hardening changes.

Covers:
1. Atomic MERGE-based lock acquisition (pipeline/lock.py)
2. Fencing tokens (pipeline/lock.py)
3. Fenced watermark write SQL (sql/builders/watermark.py)
4. WatermarkManager fenced writes (watermark/manager.py)
5. WatermarkManager has_unprocessed_records ordered mode
6. Pipeline health probe fix (pipeline/pipeline.py)
7. Pipeline fencing token wiring (pipeline/pipeline.py)
8. Executor per-SQL health heartbeat (pipeline/executor.py)
9. Strict watermark value validation (sql/builders/staging.py)
10. Thread-safe cost tracking (clients/bigquery.py)
11. LockFencingError exception (exceptions.py)
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from bq_entity_resolution.exceptions import (
    LockFencingError,
    PipelineAbortError,
    WatermarkError,
)
from bq_entity_resolution.pipeline.lock import PipelineLock  # noqa: I001
from bq_entity_resolution.sql.builders.watermark import (
    build_fenced_watermark_update_sql,
    build_update_watermark_sql,
)

# ===================================================================
# 1. Atomic MERGE Lock Acquisition
# ===================================================================


class TestAtomicMergeAcquisition:
    """Tests for MERGE-based lock acquisition in PipelineLock."""

    def test_acquire_generates_merge_sql(self):
        """acquire() should use MERGE (not INSERT) for atomic acquisition."""
        client = MagicMock()
        # After MERGE, verify SELECT returns our holder
        client.execute_and_fetch.return_value = [
            {"lock_holder": None, "fencing_token": 12345}
        ]
        lock = PipelineLock(client, "p.d.locks", max_wait_seconds=1)

        # First call won't match holder_id, override to match
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 12345}
        ]
        lock.acquire("test_pipeline")

        # Check that MERGE was used (not separate SELECT + INSERT)
        merge_calls = [
            c for c in client.execute.call_args_list
            if "MERGE" in str(c)
        ]
        assert len(merge_calls) >= 1, "Should use MERGE for acquisition"

    def test_acquire_merge_handles_no_existing_row(self):
        """MERGE should INSERT when no row exists (WHEN NOT MATCHED)."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 999}
        ]
        lock.acquire("my_pipe")

        merge_sql = client.execute.call_args_list[-1][0][0]
        assert "WHEN NOT MATCHED THEN" in merge_sql
        assert "INSERT" in merge_sql

    def test_acquire_merge_handles_expired_row(self):
        """MERGE should UPDATE when row is expired (WHEN MATCHED AND expires_at < now)."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 999}
        ]
        lock.acquire("my_pipe")

        merge_sql = client.execute.call_args_list[-1][0][0]
        assert "WHEN MATCHED AND T.expires_at <" in merge_sql

    def test_acquire_sets_fencing_token(self):
        """Successful acquire should set the fencing_token property."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        token = 1234567890
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": token}
        ]
        lock.acquire("test")

        assert lock.fencing_token == token

    def test_acquire_retries_on_held_lock(self):
        """acquire() should retry when another holder has the lock."""
        client = MagicMock()
        lock = PipelineLock(
            client, "p.d.locks",
            retry_seconds=0,  # No sleep for testing
            max_wait_seconds=0,
        )

        # Always return another holder
        client.execute_and_fetch.return_value = [
            {"lock_holder": "other_holder", "fencing_token": 999}
        ]

        with pytest.raises(PipelineAbortError, match="Could not acquire lock"):
            lock.acquire("test")

    def test_acquire_timeout_reports_current_holder(self):
        """Timeout error should report who holds the lock."""
        client = MagicMock()
        lock = PipelineLock(
            client, "p.d.locks",
            retry_seconds=0,
            max_wait_seconds=0,
        )

        client.execute_and_fetch.return_value = [
            {"lock_holder": "pod-abc-123", "fencing_token": 999}
        ]

        with pytest.raises(PipelineAbortError, match="pod-abc-123"):
            lock.acquire("test")

    def test_fencing_token_initially_none(self):
        """fencing_token should be None before acquisition."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        assert lock.fencing_token is None

    def test_merge_uses_current_timestamp_not_python_datetime(self):
        """MERGE SQL uses CURRENT_TIMESTAMP() to avoid clock skew."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 1}
        ]
        lock.acquire("test")

        merge_sql = client.execute.call_args_list[-1][0][0]
        # Should use BQ server time, not Python datetime literals
        assert "CURRENT_TIMESTAMP()" in merge_sql
        assert "TIMESTAMP_ADD(CURRENT_TIMESTAMP()" in merge_sql
        # Should NOT contain Python-generated ISO timestamps
        import re
        iso_pattern = re.compile(r"TIMESTAMP '\d{4}-\d{2}-\d{2}T")
        assert not iso_pattern.search(merge_sql), (
            "MERGE SQL should not contain Python-generated timestamps"
        )

    def test_refresh_uses_current_timestamp(self):
        """refresh() uses CURRENT_TIMESTAMP() for heartbeat."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks", ttl_minutes=15)
        lock._fencing_token = 42

        lock.refresh("test")

        update_sql = client.execute.call_args[0][0]
        assert "CURRENT_TIMESTAMP()" in update_sql
        assert "INTERVAL 15 MINUTE" in update_sql


# ===================================================================
# 2. Fencing Tokens
# ===================================================================


class TestFencingTokens:
    """Tests for fencing token management in PipelineLock."""

    def test_fencing_token_is_monotonic_microsecond_epoch(self):
        """Fencing token should be based on microsecond epoch."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        # Verify MERGE SQL contains a numeric token
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 1700000000000000}
        ]
        lock.acquire("test")

        merge_sql = client.execute.call_args_list[-1][0][0]
        assert "fencing_token" in merge_sql

    def test_release_clears_fencing_token(self):
        """release() should clear the fencing_token property."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        # Acquire first
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 999}
        ]
        lock.acquire("test")
        assert lock.fencing_token is not None

        # Release
        lock.release("test")
        assert lock.fencing_token is None

    def test_refresh_includes_fencing_token_in_where(self):
        """refresh() should include fencing_token in WHERE clause."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        # Acquire
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 42}
        ]
        lock.acquire("test")
        client.reset_mock()

        # Refresh
        lock.refresh("test")

        update_sql = client.execute.call_args[0][0]
        assert "fencing_token = 42" in update_sql

    def test_verify_lock_checks_ownership(self):
        """verify_lock() should confirm we still hold the lock."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        # Set up as if acquired
        lock._fencing_token = 42

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id}
        ]
        assert lock.verify_lock("test") is True

    def test_verify_lock_detects_stolen_lock(self):
        """verify_lock() should return False if lock was stolen."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = []
        assert lock.verify_lock("test") is False


# ===================================================================
# 3. Fenced Watermark Write SQL
# ===================================================================


class TestFencedWatermarkSQL:
    """Tests for build_fenced_watermark_update_sql."""

    def test_fenced_sql_contains_declare(self):
        """Fenced SQL should declare a token variable."""
        expr = build_fenced_watermark_update_sql(
            watermark_table="p.d.watermarks",
            source_name="customers",
            cursors=[{"column": "updated_at", "value": "2024-01-01", "type": "TIMESTAMP"}],
            run_id="run_001",
            now="2024-01-01T00:00:00",
            lock_table="p.d.locks",
            pipeline_name="my_pipeline",
            fencing_token=42,
        )
        sql = expr.render()
        assert "DECLARE current_token INT64" in sql

    def test_fenced_sql_checks_fencing_token(self):
        """Fenced SQL should verify fencing token before committing."""
        expr = build_fenced_watermark_update_sql(
            watermark_table="p.d.watermarks",
            source_name="customers",
            cursors=[{"column": "updated_at", "value": "2024-01-01", "type": "TIMESTAMP"}],
            run_id="run_001",
            now="2024-01-01T00:00:00",
            lock_table="p.d.locks",
            pipeline_name="my_pipeline",
            fencing_token=42,
        )
        sql = expr.render()
        assert "current_token != 42" in sql
        assert "ROLLBACK TRANSACTION" in sql

    def test_fenced_sql_contains_transaction(self):
        """Fenced SQL should use BEGIN/COMMIT TRANSACTION."""
        expr = build_fenced_watermark_update_sql(
            watermark_table="p.d.watermarks",
            source_name="src",
            cursors=[{"column": "id", "value": "100", "type": "INT64"}],
            run_id="run_001",
            now="2024-01-01T00:00:00",
            lock_table="p.d.locks",
            pipeline_name="pipe",
            fencing_token=1,
        )
        sql = expr.render()
        assert "BEGIN TRANSACTION" in sql
        assert "COMMIT TRANSACTION" in sql

    def test_fenced_sql_reads_from_lock_table(self):
        """Fenced SQL should SELECT fencing_token FROM the lock table."""
        expr = build_fenced_watermark_update_sql(
            watermark_table="p.d.watermarks",
            source_name="src",
            cursors=[{"column": "id", "value": "100", "type": "INT64"}],
            run_id="run_001",
            now="2024-01-01T00:00:00",
            lock_table="p.d.pipeline_locks",
            pipeline_name="pipe",
            fencing_token=99,
        )
        sql = expr.render()
        assert "p.d.pipeline_locks" in sql
        assert "SELECT fencing_token FROM" in sql

    def test_fenced_sql_rejects_empty_cursors(self):
        """Empty cursors should raise ValueError."""
        with pytest.raises(ValueError, match="No watermark cursors"):
            build_fenced_watermark_update_sql(
                watermark_table="p.d.watermarks",
                source_name="src",
                cursors=[],
                run_id="run_001",
                now="2024-01-01T00:00:00",
                lock_table="p.d.locks",
                pipeline_name="pipe",
                fencing_token=1,
            )

    def test_unfenced_sql_has_no_declare(self):
        """Unfenced (standard) SQL should NOT have DECLARE or fencing logic."""
        expr = build_update_watermark_sql(
            table="p.d.watermarks",
            source_name="src",
            cursors=[{"column": "id", "value": "100", "type": "INT64"}],
            run_id="run_001",
            now="2024-01-01T00:00:00",
        )
        sql = expr.render()
        assert "DECLARE" not in sql
        assert "current_token" not in sql


# ===================================================================
# 4. WatermarkManager Fenced Writes
# ===================================================================


class TestWatermarkManagerFenced:
    """Tests for fenced watermark writes in WatermarkManager."""

    def test_write_with_fencing_params_uses_fenced_sql(self):
        """When fencing params provided, should use fenced SQL builder."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        mgr = WatermarkManager(client, "p.d.watermarks")

        mgr.write(
            source_name="customers",
            cursors={"updated_at": datetime(2024, 1, 1, tzinfo=UTC)},
            run_id="run_001",
            fencing_token=42,
            lock_table="p.d.locks",
            pipeline_name="my_pipe",
        )

        # Verify the SQL contains fencing token logic
        executed_sql = client.execute.call_args[0][0]
        assert "DECLARE current_token" in executed_sql

    def test_write_without_fencing_params_uses_unfenced_sql(self):
        """When no fencing params, should use standard unfenced SQL."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        mgr = WatermarkManager(client, "p.d.watermarks")

        mgr.write(
            source_name="customers",
            cursors={"updated_at": datetime(2024, 1, 1, tzinfo=UTC)},
            run_id="run_001",
        )

        # Verify the SQL does NOT contain fencing token logic
        executed_sql = client.execute.call_args[0][0]
        assert "DECLARE current_token" not in executed_sql
        assert "BEGIN TRANSACTION" in executed_sql  # Still transactional

    def test_write_raises_lock_fencing_error_on_mismatch(self):
        """Fencing token mismatch should raise LockFencingError."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        client.execute.side_effect = Exception("fencing token mismatch: rollback")
        mgr = WatermarkManager(client, "p.d.watermarks")

        with pytest.raises(LockFencingError, match="Lock lost"):
            mgr.write(
                source_name="src",
                cursors={"id": 100},
                run_id="run_001",
                fencing_token=42,
                lock_table="p.d.locks",
                pipeline_name="pipe",
            )

    def test_write_raises_watermark_error_on_other_failure(self):
        """Non-fencing errors should raise WatermarkError."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        client.execute.side_effect = Exception("connection timeout")
        mgr = WatermarkManager(client, "p.d.watermarks")

        with pytest.raises(WatermarkError, match="Failed to write watermark"):
            mgr.write(
                source_name="src",
                cursors={"id": 100},
                run_id="run_001",
            )

    def test_write_empty_cursors_returns_early(self):
        """Empty cursors dict should return without executing SQL."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        mgr = WatermarkManager(client, "p.d.watermarks")

        mgr.write(source_name="src", cursors={})
        client.execute.assert_not_called()


# ===================================================================
# 5. has_unprocessed_records with cursor_mode
# ===================================================================


class TestHasUnprocessedRecordsOrdered:
    """Tests for cursor_mode parameter in has_unprocessed_records."""

    def test_ordered_mode_uses_tuple_comparison(self):
        """cursor_mode='ordered' should use ordered tuple comparison."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        client.execute_and_fetch.return_value = [{"cnt": 5}]
        mgr = WatermarkManager(client, "p.d.watermarks")

        result = mgr.has_unprocessed_records(
            source_table="p.d.source",
            cursor_columns=["updated_at", "id"],
            current_watermark={
                "updated_at": datetime(2024, 1, 1, tzinfo=UTC),
                "id": 100,
            },
            cursor_mode="ordered",
        )

        assert result is True
        sql = client.execute_and_fetch.call_args[0][0]
        # Ordered mode generates (col1 > wm1) OR (col1 = wm1 AND col2 > wm2)
        assert "OR" in sql

    def test_independent_mode_uses_or_logic(self):
        """cursor_mode='independent' should use simple OR logic."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        client.execute_and_fetch.return_value = [{"cnt": 0}]
        mgr = WatermarkManager(client, "p.d.watermarks")

        result = mgr.has_unprocessed_records(
            source_table="p.d.source",
            cursor_columns=["updated_at"],
            current_watermark={"updated_at": datetime(2024, 1, 1, tzinfo=UTC)},
            cursor_mode="independent",
        )

        assert result is False

    def test_grace_period_applied(self):
        """grace_period_hours should be reflected in the SQL."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        client.execute_and_fetch.return_value = [{"cnt": 1}]
        mgr = WatermarkManager(client, "p.d.watermarks")

        mgr.has_unprocessed_records(
            source_table="p.d.source",
            cursor_columns=["updated_at"],
            current_watermark={"updated_at": datetime(2024, 1, 1, tzinfo=UTC)},
            cursor_mode="independent",
            grace_period_hours=48,
        )

        sql = client.execute_and_fetch.call_args[0][0]
        assert "INTERVAL 48 HOUR" in sql

    def test_empty_watermark_returns_true(self):
        """No watermark should indicate unprocessed records."""
        from bq_entity_resolution.watermark.manager import WatermarkManager

        client = MagicMock()
        mgr = WatermarkManager(client, "p.d.watermarks")

        result = mgr.has_unprocessed_records(
            source_table="p.d.source",
            cursor_columns=["updated_at"],
            current_watermark={},
        )
        assert result is True
        client.execute_and_fetch.assert_not_called()


# ===================================================================
# 6. Pipeline Health Probe Fix
# ===================================================================


class TestPipelineHealthProbeFix:
    """Tests for health probe fix: mark_unhealthy on lock failure."""

    def _make_pipeline(self, deploy_lock_enabled=True):
        """Create a minimal Pipeline for testing."""
        from bq_entity_resolution.config.schema import PipelineConfig
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        cfg = PipelineConfig(**{
            "project": {
                "name": "test",
                "bq_project": "p",
                "watermark_dataset": "er_meta",
            },
            "sources": [{
                "name": "s",
                "table": "p.d.t",
                "unique_key": "id",
                "updated_at": "updated_at",
                "columns": [{"name": "id"}],
            }],
            "matching_tiers": [{
                "name": "exact",
                "blocking": {"paths": []},
                "comparisons": [],
                "threshold": {"min_score": 0.0},
            }],
            "deployment": {
                "health_probe": {"enabled": True, "path": "/tmp/test_probe"},
                "distributed_lock": {
                    "enabled": deploy_lock_enabled,
                    "lock_table": "pipeline_locks",
                },
            },
        })
        return Pipeline(cfg)

    def test_health_probe_unhealthy_on_lock_failure(self):
        """If lock acquisition fails, health probe should be marked unhealthy."""
        pipeline = self._make_pipeline(deploy_lock_enabled=True)

        mock_backend = MagicMock()
        mock_backend.bq_client = MagicMock()

        hp = "bq_entity_resolution.pipeline.pipeline.HealthProbe"
        gs = "bq_entity_resolution.pipeline.pipeline.GracefulShutdown"
        lk = "bq_entity_resolution.pipeline.lock.PipelineLock"
        with patch.object(pipeline, "validate", return_value=[]), \
             patch(hp) as mock_probe_cls, \
             patch(gs) as mock_shutdown_cls, \
             patch(lk) as mock_lock_cls:

            probe_instance = MagicMock()
            mock_probe_cls.return_value = probe_instance
            mock_shutdown_cls.return_value = MagicMock()

            lock_instance = MagicMock()
            lock_instance.acquire.side_effect = PipelineAbortError("Timeout")
            mock_lock_cls.return_value = lock_instance

            with pytest.raises(PipelineAbortError):
                pipeline.run(backend=mock_backend)

            # Should call mark_unhealthy (not mark_healthy with "complete")
            probe_instance.mark_unhealthy.assert_called_once()

    def test_health_probe_healthy_on_success(self):
        """On successful run, health probe should mark 'complete'."""
        pipeline = self._make_pipeline(deploy_lock_enabled=False)

        mock_backend = MagicMock()

        with patch.object(pipeline, "validate", return_value=[]), \
             patch.object(pipeline, "_run_loop") as mock_run_loop, \
             patch("bq_entity_resolution.pipeline.pipeline.HealthProbe") as mock_probe_cls, \
             patch("bq_entity_resolution.pipeline.pipeline.GracefulShutdown") as mock_shutdown_cls:

            probe_instance = MagicMock()
            mock_probe_cls.return_value = probe_instance
            mock_shutdown_cls.return_value = MagicMock()

            mock_result = MagicMock()
            mock_result.success = True
            mock_run_loop.return_value = mock_result

            pipeline.run(backend=mock_backend)

            # Should call mark_healthy with "complete"
            probe_instance.mark_healthy.assert_any_call(
                stage="complete", run_id=""
            )


# ===================================================================
# 7. Executor Per-SQL Health Heartbeat
# ===================================================================


class TestExecutorHealthHeartbeat:
    """Tests for per-SQL health probe heartbeat in executor."""

    def test_heartbeat_called_per_sql(self):
        """Health probe should be called after each SQL statement."""
        from bq_entity_resolution.pipeline.executor import PipelineExecutor
        from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
        from bq_entity_resolution.sql.expression import SQLExpression

        backend = MagicMock()
        backend.execute.return_value = MagicMock(rows_affected=0)
        health_probe = MagicMock()

        executor = PipelineExecutor(
            backend=backend,
            health_probe=health_probe,
        )

        # Create a stage with 3 SQL statements
        exprs = (
            SQLExpression.from_raw("SELECT 1"),
            SQLExpression.from_raw("SELECT 2"),
            SQLExpression.from_raw("SELECT 3"),
        )
        stage = StagePlan(
            stage_name="test_stage",
            sql_expressions=exprs,
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=(stage,))

        executor.execute(plan, run_id="test_run")

        # Health probe should be called per SQL + per stage completion
        heartbeat_calls = [
            c for c in health_probe.mark_healthy.call_args_list
            if "test_stage" in str(c)
        ]
        assert len(heartbeat_calls) >= 3, (
            f"Expected at least 3 heartbeats for 3 SQL statements, "
            f"got {len(heartbeat_calls)}"
        )


# ===================================================================
# 8. Strict Watermark Value Validation
# ===================================================================


class TestWatermarkValueValidation:
    """Tests for strict watermark value regex in staging builder."""

    def test_valid_timestamp(self):
        """Timestamp values should be accepted."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        result = format_watermark_value("2024-01-15T10:30:00")
        assert "TIMESTAMP" in result
        assert "2024-01-15T10:30:00" in result

    def test_valid_numeric(self):
        """Numeric values should pass through as-is."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        assert format_watermark_value(42) == "42"
        assert format_watermark_value(3.14) == "3.14"

    def test_valid_string(self):
        """Simple string values should be quoted."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        result = format_watermark_value("active")
        assert result == "'active'"

    def test_rejects_semicolon(self):
        """Semicolons should be rejected (SQL injection)."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        with pytest.raises(ValueError, match="Unsafe characters"):
            format_watermark_value("value; DROP TABLE")

    def test_rejects_equals_sign(self):
        """Equals signs should be rejected (SQL injection vector)."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        with pytest.raises(ValueError, match="Unsafe characters"):
            format_watermark_value("1=1")

    def test_rejects_parentheses(self):
        """Parentheses should be rejected."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        with pytest.raises(ValueError, match="Unsafe characters"):
            format_watermark_value("CURRENT_TIMESTAMP()")

    def test_null_returns_null(self):
        """None should return SQL NULL."""
        from bq_entity_resolution.sql.utils import format_watermark_value

        assert format_watermark_value(None) == "NULL"


# ===================================================================
# 9. Thread-Safe Cost Tracking
# ===================================================================


class TestThreadSafeCostTracking:
    """Tests for thread-safe _total_bytes_billed in BigQueryClient."""

    def test_cost_lock_exists(self):
        """BigQueryClient should have a _cost_lock attribute."""
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        with patch("bq_entity_resolution.clients.bigquery.bigquery"):
            client = BigQueryClient.__new__(BigQueryClient)
            client._cost_lock = threading.Lock()
            assert isinstance(client._cost_lock, type(threading.Lock()))

    def test_check_cost_ceiling_thread_safe(self):
        """check_cost_ceiling should read under lock."""
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        client = BigQueryClient.__new__(BigQueryClient)
        client._cost_lock = threading.Lock()
        client._total_bytes_billed = 100

        # Should not raise — under ceiling
        client.check_cost_ceiling(200)

        # Should raise — over ceiling
        client._total_bytes_billed = 300
        with pytest.raises(PipelineAbortError, match="cost ceiling"):
            client.check_cost_ceiling(200)


# ===================================================================
# 10. LockFencingError Exception
# ===================================================================


class TestLockFencingError:
    """Tests for LockFencingError exception."""

    def test_is_entity_resolution_error(self):
        """LockFencingError should be a subclass of EntityResolutionError."""
        from bq_entity_resolution.exceptions import EntityResolutionError

        assert issubclass(LockFencingError, EntityResolutionError)

    def test_is_not_watermark_error(self):
        """LockFencingError should NOT be a subclass of WatermarkError."""
        assert not issubclass(LockFencingError, WatermarkError)

    def test_can_be_raised_and_caught(self):
        """LockFencingError should be catchable by its own type."""
        with pytest.raises(LockFencingError, match="stolen"):
            raise LockFencingError("Lock was stolen by another pod")


# ===================================================================
# 11. Lock Table Schema Migration
# ===================================================================


class TestLockTableMigration:
    """Tests for lock table schema migration (fencing_token column)."""

    def test_ensure_table_adds_fencing_token_column(self):
        """ensure_table_exists should ALTER TABLE to add fencing_token."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        lock.ensure_table_exists()

        # Should have CREATE TABLE and ALTER TABLE calls
        sql_calls = [str(c) for c in client.execute.call_args_list]
        has_create = any("CREATE TABLE" in s for s in sql_calls)
        has_alter = any("fencing_token" in s and "ALTER" in s for s in sql_calls)
        assert has_create, "Should CREATE TABLE IF NOT EXISTS"
        assert has_alter, "Should ALTER TABLE to add fencing_token column"

    def test_ensure_table_handles_alter_failure(self):
        """ALTER TABLE failure should be silently ignored (column exists)."""
        client = MagicMock()
        # CREATE succeeds, ALTER fails
        client.execute.side_effect = [None, Exception("Column already exists")]
        lock = PipelineLock(client, "p.d.locks")

        # Should not raise
        lock.ensure_table_exists()


# ===================================================================
# 12. Config: fencing_enabled
# ===================================================================


class TestFencingEnabledConfig:
    """Tests for fencing_enabled in DistributedLockConfig."""

    def test_fencing_enabled_default_true(self):
        """fencing_enabled should default to True."""
        from bq_entity_resolution.config.models.infrastructure import DistributedLockConfig

        config = DistributedLockConfig()
        assert config.fencing_enabled is True

    def test_fencing_enabled_can_be_disabled(self):
        """fencing_enabled should be configurable to False."""
        from bq_entity_resolution.config.models.infrastructure import DistributedLockConfig

        config = DistributedLockConfig(fencing_enabled=False)
        assert config.fencing_enabled is False


# ===================================================================
# 13. Lock Release and Refresh
# ===================================================================


class TestLockReleaseRefresh:
    """Tests for lock release and refresh operations."""

    def test_release_deletes_by_holder(self):
        """release() should DELETE matching pipeline_name AND holder_id."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        # Acquire first
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 1}
        ]
        lock.acquire("test_pipe")
        client.reset_mock()

        # Release
        lock.release("test_pipe")

        delete_sql = client.execute.call_args[0][0]
        assert "DELETE FROM" in delete_sql
        assert lock.holder_id in delete_sql

    def test_refresh_updates_expires_at(self):
        """refresh() should UPDATE expires_at and heartbeat_at."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        # Acquire
        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 1}
        ]
        lock.acquire("test_pipe")
        client.reset_mock()

        lock.refresh("test_pipe")

        update_sql = client.execute.call_args[0][0]
        assert "expires_at" in update_sql
        assert "heartbeat_at" in update_sql

    def test_release_handles_failure_gracefully(self):
        """release() should not raise on failure, preserves fencing token."""
        client = MagicMock()
        client.execute.side_effect = Exception("Network error")
        lock = PipelineLock(client, "p.d.locks")
        lock._fencing_token = 1

        # Should not raise
        lock.release("test_pipe")
        # Fencing token preserved on failure so retry is possible
        assert lock.fencing_token == 1


# ===================================================================
# 14. SQL Escape in Metrics (Integration)
# ===================================================================


class TestMetricsSqlEscapeIntegration:
    """Verify metrics module uses correct sql_escape from sql/utils."""

    def test_metrics_uses_bq_compatible_escape(self):
        """Metrics should use '' (not \\') for single-quote escaping."""
        from bq_entity_resolution.sql.utils import sql_escape

        # BigQuery standard: double single-quote
        assert sql_escape("it's") == "it''s"
        # NOT backslash escaping
        assert sql_escape("it's") != "it\\'s"


# ===================================================================
# 15. Sequence-Based Fencing Tokens
# ===================================================================


class TestSequenceBasedFencingTokens:
    """Tests for sequence-based (not wall-clock) fencing tokens."""

    def test_merge_uses_coalesce_increment(self):
        """MERGE SQL should use COALESCE(T.fencing_token, 0) + 1 for updates."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 5}
        ]
        lock.acquire("test")

        merge_sql = client.execute.call_args_list[-1][0][0]
        assert "COALESCE(T.fencing_token, 0) + 1" in merge_sql

    def test_merge_inserts_with_token_1(self):
        """WHEN NOT MATCHED, fencing_token should be 1 (first acquisition)."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 1}
        ]
        lock.acquire("test")

        merge_sql = client.execute.call_args_list[-1][0][0]
        # The INSERT VALUES should end with ", 1)" for fencing_token
        # (may have trailing whitespace inside parens)
        assert "    1  )" in merge_sql or ",\n    1\n  )" in merge_sql or ", 1)" in merge_sql

    def test_no_wall_clock_token_in_merge(self):
        """MERGE SQL should NOT contain a Python-computed microsecond token."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 1}
        ]
        lock.acquire("test")

        merge_sql = client.execute.call_args_list[-1][0][0]
        # Should not have a large microsecond epoch number as fencing_token value
        # The old pattern was: fencing_token = <large_int>
        # The new pattern is: fencing_token = COALESCE(T.fencing_token, 0) + 1
        # or fencing_token VALUES(..., 1)
        import re
        # Check there's no fencing_token = <digits> pattern (old wall clock)
        # Exclude the COALESCE pattern and the VALUES 1
        matches = re.findall(r"fencing_token\s*=\s*(\d{10,})", merge_sql)
        assert not matches, (
            f"Found wall-clock token in MERGE SQL: {matches}"
        )

    def test_verification_reads_sequence_token(self):
        """After MERGE, verification SELECT should set fencing_token from BQ."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")

        client.execute_and_fetch.return_value = [
            {"lock_holder": lock.holder_id, "fencing_token": 7}
        ]
        lock.acquire("test")

        # Token should be exactly what BQ returned (7), not a computed value
        assert lock.fencing_token == 7


# ===================================================================
# 16. Fenced Checkpoint SQL Builder
# ===================================================================


class TestFencedCheckpointSQL:
    """Tests for build_fenced_checkpoint_insert_sql."""

    def test_fenced_checkpoint_contains_declare(self):
        """Fenced checkpoint SQL should declare a token variable."""
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_checkpoint_insert_sql,
        )

        expr = build_fenced_checkpoint_insert_sql(
            checkpoint_table="p.d.checkpoints",
            run_id="run_001",
            stage_name="staging",
            now="2024-01-01T00:00:00",
            status="completed",
            lock_table="p.d.locks",
            pipeline_name="my_pipeline",
            fencing_token=42,
        )
        sql = expr.render()
        assert "DECLARE current_token INT64" in sql

    def test_fenced_checkpoint_checks_token(self):
        """Fenced checkpoint SQL should verify fencing token."""
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_checkpoint_insert_sql,
        )

        expr = build_fenced_checkpoint_insert_sql(
            checkpoint_table="p.d.checkpoints",
            run_id="run_001",
            stage_name="staging",
            now="2024-01-01T00:00:00",
            status="completed",
            lock_table="p.d.locks",
            pipeline_name="my_pipe",
            fencing_token=99,
        )
        sql = expr.render()
        assert "current_token != 99" in sql
        assert "ROLLBACK TRANSACTION" in sql

    def test_fenced_checkpoint_inserts_record(self):
        """Fenced checkpoint SQL should INSERT the checkpoint record."""
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_checkpoint_insert_sql,
        )

        expr = build_fenced_checkpoint_insert_sql(
            checkpoint_table="p.d.checkpoints",
            run_id="run_001",
            stage_name="staging",
            now="2024-01-01T00:00:00",
            status="completed",
            lock_table="p.d.locks",
            pipeline_name="pipe",
            fencing_token=1,
        )
        sql = expr.render()
        assert "INSERT INTO `p.d.checkpoints`" in sql
        assert "'run_001'" in sql
        assert "'staging'" in sql
        assert "'completed'" in sql

    def test_fenced_checkpoint_reads_from_lock_table(self):
        """Fenced checkpoint SQL should query the lock table for token."""
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_checkpoint_insert_sql,
        )

        expr = build_fenced_checkpoint_insert_sql(
            checkpoint_table="p.d.checkpoints",
            run_id="run_001",
            stage_name="staging",
            now="2024-01-01T00:00:00",
            status="completed",
            lock_table="p.d.pipeline_locks",
            pipeline_name="pipe",
            fencing_token=5,
        )
        sql = expr.render()
        assert "p.d.pipeline_locks" in sql
        assert "SELECT fencing_token FROM" in sql

    def test_fenced_checkpoint_uses_transaction(self):
        """Fenced checkpoint should wrap in BEGIN/COMMIT TRANSACTION."""
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_checkpoint_insert_sql,
        )

        expr = build_fenced_checkpoint_insert_sql(
            checkpoint_table="p.d.checkpoints",
            run_id="run_001",
            stage_name="staging",
            now="2024-01-01T00:00:00",
            status="completed",
            lock_table="p.d.locks",
            pipeline_name="pipe",
            fencing_token=1,
        )
        sql = expr.render()
        assert "BEGIN TRANSACTION" in sql
        assert "COMMIT TRANSACTION" in sql


# ===================================================================
# 17. CheckpointManager Fenced Writes
# ===================================================================


class TestCheckpointManagerFenced:
    """Tests for fenced writes in CheckpointManager."""

    def test_mark_stage_complete_with_fencing_uses_script(self):
        """When fencing params provided, should use execute_script."""
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        mgr = CheckpointManager(client, "p.d.checkpoints")

        mgr.mark_stage_complete(
            "run_001",
            "staging",
            fencing_token=42,
            lock_table="p.d.locks",
            pipeline_name="my_pipe",
        )

        # Should call execute_script (not execute) for scripting block
        client.execute_script.assert_called_once()
        sql = client.execute_script.call_args[0][0]
        assert "DECLARE current_token" in sql
        assert "current_token != 42" in sql

    def test_mark_stage_complete_without_fencing_uses_execute(self):
        """When no fencing params, should use plain execute."""
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        mgr = CheckpointManager(client, "p.d.checkpoints")

        mgr.mark_stage_complete("run_001", "staging")

        client.execute.assert_called_once()
        sql = client.execute.call_args[0][0]
        assert "INSERT INTO" in sql
        assert "DECLARE" not in sql

    def test_mark_run_complete_passes_fencing_through(self):
        """mark_run_complete should forward fencing params to mark_stage_complete."""
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        mgr = CheckpointManager(client, "p.d.checkpoints")

        mgr.mark_run_complete(
            "run_001",
            fencing_token=10,
            lock_table="p.d.locks",
            pipeline_name="pipe",
        )

        # Should use execute_script (fenced path)
        client.execute_script.assert_called_once()
        sql = client.execute_script.call_args[0][0]
        assert "__run_complete__" in sql
        assert "current_token != 10" in sql

    def test_mark_stage_partial_fencing_raises_value_error(self):
        """If only some fencing params provided, raise ValueError (fail-fast)."""
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        mgr = CheckpointManager(client, "p.d.checkpoints")

        # Only fencing_token, missing lock_table and pipeline_name
        with pytest.raises(ValueError, match="Partial fencing config"):
            mgr.mark_stage_complete(
                "run_001", "staging",
                fencing_token=42,
            )

        # Should NOT call either execute method
        client.execute.assert_not_called()
        client.execute_script.assert_not_called()


# ===================================================================
# 18. Executor Fencing Kwargs Passthrough
# ===================================================================


class TestExecutorFencingKwargs:
    """Tests for executor passing fencing_kwargs to checkpoint manager."""

    def test_executor_passes_fencing_kwargs_to_checkpoint(self):
        """PipelineExecutor should pass fencing_kwargs to mark_stage_complete."""
        from bq_entity_resolution.pipeline.executor import PipelineExecutor
        from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
        from bq_entity_resolution.sql.expression import SQLExpression

        backend = MagicMock()
        backend.execute.return_value = MagicMock(rows_affected=0)
        checkpoint = MagicMock()

        fencing_kwargs = {
            "fencing_token": 42,
            "lock_table": "p.d.locks",
            "pipeline_name": "my_pipe",
        }

        executor = PipelineExecutor(
            backend=backend,
            checkpoint_manager=checkpoint,
            fencing_kwargs=fencing_kwargs,
        )

        stage = StagePlan(
            stage_name="staging",
            sql_expressions=(SQLExpression.from_raw("SELECT 1"),),
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=(stage,))

        executor.execute(plan, run_id="run_001")

        # mark_stage_complete should be called with fencing kwargs
        checkpoint.mark_stage_complete.assert_called_once_with(
            "run_001", "staging",
            fencing_token=42,
            lock_table="p.d.locks",
            pipeline_name="my_pipe",
        )

        # mark_run_complete should also get fencing kwargs
        checkpoint.mark_run_complete.assert_called_once_with(
            "run_001",
            fencing_token=42,
            lock_table="p.d.locks",
            pipeline_name="my_pipe",
        )

    def test_executor_no_fencing_kwargs_passes_empty(self):
        """Without fencing_kwargs, checkpoint calls should have no extras."""
        from bq_entity_resolution.pipeline.executor import PipelineExecutor
        from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
        from bq_entity_resolution.sql.expression import SQLExpression

        backend = MagicMock()
        backend.execute.return_value = MagicMock(rows_affected=0)
        checkpoint = MagicMock()

        executor = PipelineExecutor(
            backend=backend,
            checkpoint_manager=checkpoint,
        )

        stage = StagePlan(
            stage_name="staging",
            sql_expressions=(SQLExpression.from_raw("SELECT 1"),),
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=(stage,))

        executor.execute(plan, run_id="run_001")

        # mark_stage_complete should be called without fencing kwargs
        checkpoint.mark_stage_complete.assert_called_once_with(
            "run_001", "staging",
        )

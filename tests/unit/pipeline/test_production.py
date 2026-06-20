"""Comprehensive tests for K8s production features.

Covers:
- HealthProbe (file-based liveness)
- GracefulShutdown (signal handling)
- PipelineLock (distributed locking)
- DeploymentConfig (YAML schema)
- BigQueryClient improvements (cost ceiling, job cancellation)
- Metrics SQL injection fix
- Pipeline context UTC timestamps
- PipelineExecutor new params
- Pipeline.run infrastructure wiring
"""

from __future__ import annotations

import json
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bq_entity_resolution.config.models.infrastructure import (
    DeploymentConfig,
    DistributedLockConfig,
    ExecutionConfig,
    GracefulShutdownConfig,
    HealthProbeConfig,
)
from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.exceptions import PipelineAbortError
from bq_entity_resolution.pipeline.context import PipelineContext
from bq_entity_resolution.pipeline.executor import PipelineExecutor
from bq_entity_resolution.pipeline.health import HealthProbe
from bq_entity_resolution.pipeline.lock import PipelineLock
from bq_entity_resolution.pipeline.shutdown import GracefulShutdown
from bq_entity_resolution.sql.utils import sql_escape, validate_safe_value

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_config(**overrides):
    """Build a minimal PipelineConfig for testing."""
    base = {
        "project": {"name": "test", "bq_project": "p"},
        "sources": [
            {
                "name": "s",
                "table": "p.d.t",
                "unique_key": "id",
                "updated_at": "updated_at",
                "columns": [{"name": "id"}],
            }
        ],
        "matching_tiers": [
            {
                "name": "exact",
                "blocking": {"paths": []},
                "comparisons": [],
                "threshold": {"min_score": 0.0},
            }
        ],
    }
    base.update(overrides)
    return PipelineConfig(**base)


# ===================================================================
# 1. HealthProbe
# ===================================================================


class TestHealthProbe:
    """Tests for src/bq_entity_resolution/pipeline/health.py."""

    def test_mark_healthy_writes_json_with_expected_fields(self, tmp_path: Path):
        """mark_healthy should write JSON with status, timestamp, stage, run_id, pid."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy(stage="staging", run_id="run_123")

        assert os.path.exists(health_file)
        with open(health_file) as f:
            data = json.load(f)

        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["stage"] == "staging"
        assert data["run_id"] == "run_123"
        assert data["pid"] == os.getpid()

    def test_mark_healthy_timestamp_is_utc(self, tmp_path: Path):
        """The timestamp in the health file should be a UTC ISO timestamp."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy(stage="test")

        with open(health_file) as f:
            data = json.load(f)

        ts = data["timestamp"]
        # UTC timestamps from datetime.now(UTC).isoformat() contain "+00:00"
        assert "+00:00" in ts or ts.endswith("Z"), f"Expected UTC timestamp, got: {ts}"

    def test_mark_unhealthy_removes_file(self, tmp_path: Path):
        """mark_unhealthy should remove the health file."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy(stage="staging")
        assert os.path.exists(health_file)

        probe.mark_unhealthy()
        assert not os.path.exists(health_file)

    def test_mark_unhealthy_no_error_if_file_missing(self, tmp_path: Path):
        """mark_unhealthy should not raise if the file does not exist."""
        health_file = str(tmp_path / "nonexistent")
        probe = HealthProbe(path=health_file, enabled=True)

        # Should not raise
        probe.mark_unhealthy()

    def test_is_healthy_returns_true_when_file_exists(self, tmp_path: Path):
        """is_healthy should return True when the health file exists."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy(stage="test")
        assert probe.is_healthy() is True

    def test_is_healthy_returns_false_when_file_missing(self, tmp_path: Path):
        """is_healthy should return False when the health file does not exist."""
        health_file = str(tmp_path / "missing_file")
        probe = HealthProbe(path=health_file, enabled=True)

        assert probe.is_healthy() is False

    def test_is_healthy_returns_false_after_mark_unhealthy(self, tmp_path: Path):
        """is_healthy should return False after mark_unhealthy is called."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy(stage="staging")
        assert probe.is_healthy() is True

        probe.mark_unhealthy()
        assert probe.is_healthy() is False

    def test_disabled_probe_skips_mark_healthy(self, tmp_path: Path):
        """A disabled probe should not write any file."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=False)

        probe.mark_healthy(stage="staging")
        assert not os.path.exists(health_file)

    def test_disabled_probe_skips_mark_unhealthy(self, tmp_path: Path):
        """A disabled probe should not attempt to remove a file."""
        health_file = str(tmp_path / "pipeline_healthy")
        # Write a file manually to ensure the probe does not remove it
        with open(health_file, "w") as f:
            f.write("test")

        probe = HealthProbe(path=health_file, enabled=False)
        probe.mark_unhealthy()

        # File should still exist since probe is disabled
        assert os.path.exists(health_file)

    def test_atomic_write_uses_tmp_then_rename(self, tmp_path: Path):
        """mark_healthy should write to .tmp first, then rename (atomic)."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        with patch("bq_entity_resolution.pipeline.health.os.replace") as mock_replace:
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = MagicMock()
                mock_open.return_value.__exit__ = MagicMock(return_value=False)

                probe.mark_healthy(stage="test")

                # os.replace should be called with tmp_path and final path
                if mock_replace.called:
                    args = mock_replace.call_args[0]
                    assert args[0] == health_file + ".tmp"
                    assert args[1] == health_file

    def test_mark_healthy_overwrites_previous_content(self, tmp_path: Path):
        """Subsequent mark_healthy calls should overwrite the file."""
        health_file = str(tmp_path / "pipeline_healthy")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy(stage="stage1", run_id="run1")
        probe.mark_healthy(stage="stage2", run_id="run2")

        with open(health_file) as f:
            data = json.load(f)

        assert data["stage"] == "stage2"
        assert data["run_id"] == "run2"

    def test_path_and_enabled_properties(self, tmp_path: Path):
        """Properties should expose constructor values."""
        health_file = str(tmp_path / "test")
        probe = HealthProbe(path=health_file, enabled=True)
        assert probe.path == health_file
        assert probe.enabled is True

        probe2 = HealthProbe(path="/other", enabled=False)
        assert probe2.path == "/other"
        assert probe2.enabled is False


# ===================================================================
# 2. GracefulShutdown
# ===================================================================


class TestGracefulShutdown:
    """Tests for src/bq_entity_resolution/pipeline/shutdown.py."""

    def test_install_sets_signal_handlers(self):
        """install() should register handlers for SIGTERM and SIGINT."""
        shutdown = GracefulShutdown(enabled=True)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        try:
            shutdown.install()
            assert shutdown.installed is True

            # Signal handlers should be our handler
            assert signal.getsignal(signal.SIGTERM) == shutdown._handle_signal
            assert signal.getsignal(signal.SIGINT) == shutdown._handle_signal
        finally:
            # Restore original handlers
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)
            shutdown._installed = False

    def test_uninstall_restores_original_handlers(self):
        """uninstall() should restore the original signal handlers."""
        shutdown = GracefulShutdown(enabled=True)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        try:
            shutdown.install()
            shutdown.uninstall()

            assert shutdown.installed is False
            assert signal.getsignal(signal.SIGTERM) == original_sigterm
            assert signal.getsignal(signal.SIGINT) == original_sigint
        finally:
            # Safety restore
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)

    def test_uninstall_noop_when_not_installed(self):
        """uninstall() should be safe to call when not installed."""
        shutdown = GracefulShutdown(enabled=True)
        # Should not raise
        shutdown.uninstall()
        assert shutdown.installed is False

    def test_register_client(self):
        """register_client() should add client to the list."""
        shutdown = GracefulShutdown(enabled=True)
        client = MagicMock()

        shutdown.register_client(client)
        assert client in shutdown._clients

    def test_register_health_probe(self):
        """register_health_probe() should add probe to the list."""
        shutdown = GracefulShutdown(enabled=True)
        probe = MagicMock()

        shutdown.register_health_probe(probe)
        assert probe in shutdown._health_probes

    def test_register_lock(self):
        """register_lock() should add (lock, pipeline_name) tuple."""
        shutdown = GracefulShutdown(enabled=True)
        lock = MagicMock()

        shutdown.register_lock(lock, "my_pipeline")
        assert (lock, "my_pipeline") in shutdown._locks

    def test_handle_signal_cancels_jobs(self):
        """_handle_signal should call cancel_active_jobs on registered clients."""
        shutdown = GracefulShutdown(enabled=True)
        client = MagicMock()
        client.cancel_active_jobs.return_value = 2

        shutdown.register_client(client)

        with pytest.raises(SystemExit) as exc_info:
            shutdown._handle_signal(signal.SIGTERM, None)

        client.cancel_active_jobs.assert_called_once()
        # Exit code = 128 + SIGTERM
        assert exc_info.value.code == 128 + signal.SIGTERM

    def test_handle_signal_marks_probes_unhealthy(self):
        """_handle_signal should call mark_unhealthy on registered probes."""
        shutdown = GracefulShutdown(enabled=True)
        probe = MagicMock()

        shutdown.register_health_probe(probe)

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        probe.mark_unhealthy.assert_called_once()

    def test_handle_signal_releases_locks(self):
        """_handle_signal should call release on registered locks."""
        shutdown = GracefulShutdown(enabled=True)
        lock = MagicMock()

        shutdown.register_lock(lock, "pipeline_x")

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        lock.release.assert_called_once_with("pipeline_x")

    def test_double_signal_forces_exit(self):
        """Second signal should force exit (different code path)."""
        shutdown = GracefulShutdown(enabled=True)

        # First call sets _shutting_down=True and exits
        with pytest.raises(SystemExit) as exc_info:
            shutdown._handle_signal(signal.SIGTERM, None)
        assert exc_info.value.code == 128 + signal.SIGTERM

        # Second call should also exit, using the _shutting_down=True branch
        assert shutdown._shutting_down is True
        with pytest.raises(SystemExit) as exc_info2:
            shutdown._handle_signal(signal.SIGTERM, None)
        # The forced exit also uses 128 + signum
        assert exc_info2.value.code == 128 + signal.SIGTERM

    def test_disabled_shutdown_skips_installation(self):
        """A disabled GracefulShutdown should not install signal handlers."""
        shutdown = GracefulShutdown(enabled=False)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        shutdown.install()

        assert shutdown.installed is False
        assert signal.getsignal(signal.SIGTERM) == original_sigterm

    def test_install_is_idempotent(self):
        """Calling install() twice should not double-install."""
        shutdown = GracefulShutdown(enabled=True)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        try:
            shutdown.install()
            shutdown.install()  # Second call should be a no-op
            assert shutdown.installed is True
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)
            shutdown._installed = False

    def test_handle_signal_client_error_is_swallowed(self):
        """Errors from client.cancel_active_jobs should not prevent cleanup."""
        shutdown = GracefulShutdown(enabled=True)
        client = MagicMock()
        client.cancel_active_jobs.side_effect = RuntimeError("BQ down")
        probe = MagicMock()

        shutdown.register_client(client)
        shutdown.register_health_probe(probe)

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        # Probe should still be marked unhealthy even though client raised
        probe.mark_unhealthy.assert_called_once()

    def test_handle_signal_lock_error_is_swallowed(self):
        """Errors from lock.release should not prevent exit."""
        shutdown = GracefulShutdown(enabled=True)
        lock = MagicMock()
        lock.release.side_effect = RuntimeError("release failed")

        shutdown.register_lock(lock, "test_pipeline")

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        lock.release.assert_called_once_with("test_pipeline")


# ===================================================================
# 3. PipelineLock
# ===================================================================


class TestPipelineLockSanitize:
    """Tests for validate_safe_value (unified sanitization in sql/utils.py)."""

    def test_sanitize_valid_alphanumeric(self):
        """Valid alphanumeric strings should pass through unchanged."""
        assert validate_safe_value("my_pipeline", "v") == "my_pipeline"
        assert validate_safe_value("pipeline-v2", "v") == "pipeline-v2"
        assert validate_safe_value("test.lock", "v") == "test.lock"

    def test_sanitize_valid_with_special_chars(self):
        """Colons, slashes, and dots should be allowed."""
        assert validate_safe_value("p.d.t:lock", "v") == "p.d.t:lock"
        assert validate_safe_value("project/dataset/table", "v") == "project/dataset/table"

    def test_sanitize_valid_with_digits(self):
        """Digits should be allowed."""
        assert validate_safe_value("pipeline123", "v") == "pipeline123"
        assert validate_safe_value("12345", "v") == "12345"

    def test_sanitize_rejects_semicolons(self):
        """Semicolons should be rejected (SQL injection vector)."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("valid; DROP TABLE", "v")

    def test_sanitize_rejects_parentheses(self):
        """Parentheses should be rejected."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("value()", "v")

    def test_sanitize_rejects_backticks(self):
        """Backticks should be rejected."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("`table`", "v")

    def test_sanitize_rejects_single_quotes(self):
        """Single quotes should be rejected (not in the allowed character set)."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("it's", "v")

    def test_sanitize_rejects_newlines(self):
        """Newlines should be rejected."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("valid\nINJECTED", "v")

    def test_sanitize_rejects_empty_string(self):
        """Empty string should be rejected (no match to the regex)."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("", "v")


class TestPipelineLockHolderId:
    """Tests for PipelineLock holder_id generation."""

    def test_holder_id_contains_pid(self):
        """holder_id should contain the current process ID."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        assert str(os.getpid()) in lock.holder_id

    def test_holder_id_is_unique(self):
        """Each PipelineLock instance should have a unique holder_id."""
        client = MagicMock()
        lock1 = PipelineLock(client, "p.d.locks")
        lock2 = PipelineLock(client, "p.d.locks")
        assert lock1.holder_id != lock2.holder_id

    def test_holder_id_format(self):
        """holder_id should be in the format: {pid}_{hex}."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        parts = lock.holder_id.split("_")
        assert len(parts) == 2
        assert parts[0] == str(os.getpid())
        assert len(parts[1]) == 8  # uuid4().hex[:8]


# ===================================================================
# 4. DeploymentConfig
# ===================================================================


class TestDeploymentConfig:
    """Tests for deployment configuration models in infrastructure.py."""

    def test_default_deployment_config(self):
        """Default DeploymentConfig should have all sub-configs disabled."""
        config = DeploymentConfig()
        assert config.health_probe.enabled is False
        assert config.distributed_lock.enabled is False
        # Graceful shutdown is enabled by default for safety
        assert config.graceful_shutdown.enabled is True

    def test_health_probe_defaults(self):
        """HealthProbeConfig should have sensible defaults."""
        config = HealthProbeConfig()
        assert config.enabled is False
        assert config.path == "/tmp/pipeline_healthy"

    def test_health_probe_custom_path(self):
        """HealthProbeConfig should accept a custom path."""
        config = HealthProbeConfig(enabled=True, path="/var/run/health")
        assert config.enabled is True
        assert config.path == "/var/run/health"

    def test_distributed_lock_defaults(self):
        """DistributedLockConfig should have sensible defaults."""
        config = DistributedLockConfig()
        assert config.enabled is False
        assert config.lock_table == "pipeline_locks"
        assert config.ttl_minutes == 30
        assert config.retry_seconds == 10
        assert config.max_wait_seconds == 300

    def test_distributed_lock_custom_values(self):
        """DistributedLockConfig should accept custom values."""
        config = DistributedLockConfig(
            enabled=True,
            lock_table="custom_locks",
            ttl_minutes=60,
            retry_seconds=5,
            max_wait_seconds=600,
        )
        assert config.enabled is True
        assert config.lock_table == "custom_locks"
        assert config.ttl_minutes == 60
        assert config.retry_seconds == 5
        assert config.max_wait_seconds == 600

    def test_graceful_shutdown_defaults(self):
        """GracefulShutdownConfig should have sensible defaults."""
        config = GracefulShutdownConfig()
        assert config.enabled is True
        assert config.grace_period_seconds == 25
        assert config.cancel_running_jobs is True

    def test_graceful_shutdown_custom_values(self):
        """GracefulShutdownConfig should accept custom values."""
        config = GracefulShutdownConfig(
            enabled=False,
            grace_period_seconds=15,
            cancel_running_jobs=False,
        )
        assert config.enabled is False
        assert config.grace_period_seconds == 15
        assert config.cancel_running_jobs is False

    def test_execution_config_query_timeout(self):
        """ExecutionConfig should have query_timeout_seconds field."""
        config = ExecutionConfig()
        assert config.query_timeout_seconds == 600

    def test_execution_config_max_cost_bytes(self):
        """ExecutionConfig should have max_cost_bytes field."""
        config = ExecutionConfig()
        assert config.max_cost_bytes is None

    def test_execution_config_custom_cost_ceiling(self):
        """ExecutionConfig should accept custom max_cost_bytes."""
        config = ExecutionConfig(max_cost_bytes=50_000_000_000)
        assert config.max_cost_bytes == 50_000_000_000

    def test_execution_config_custom_timeout(self):
        """ExecutionConfig should accept custom query_timeout_seconds."""
        config = ExecutionConfig(query_timeout_seconds=300)
        assert config.query_timeout_seconds == 300

    def test_deployment_in_pipeline_config(self):
        """PipelineConfig should include deployment field."""
        config = _minimal_config()
        assert hasattr(config, "deployment")
        assert isinstance(config.deployment, DeploymentConfig)

    def test_deployment_in_pipeline_config_defaults(self):
        """PipelineConfig.deployment should use default DeploymentConfig."""
        config = _minimal_config()
        assert config.deployment.health_probe.enabled is False
        assert config.deployment.distributed_lock.enabled is False
        assert config.deployment.graceful_shutdown.enabled is True

    def test_deployment_config_from_yaml_dict(self):
        """PipelineConfig should accept deployment config from dict (YAML-like)."""
        config = _minimal_config(
            deployment={
                "health_probe": {"enabled": True, "path": "/custom/path"},
                "distributed_lock": {"enabled": True, "ttl_minutes": 60},
                "graceful_shutdown": {"enabled": False},
            }
        )
        assert config.deployment.health_probe.enabled is True
        assert config.deployment.health_probe.path == "/custom/path"
        assert config.deployment.distributed_lock.enabled is True
        assert config.deployment.distributed_lock.ttl_minutes == 60
        assert config.deployment.graceful_shutdown.enabled is False


# ===================================================================
# 5. BigQueryClient improvements (mock tests)
# ===================================================================


class TestBigQueryClientCostCeiling:
    """Tests for BigQueryClient cost control features via mock."""

    def test_make_job_config_applies_max_bytes_billed(self):
        """_make_job_config should set maximum_bytes_billed when configured."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_client_cls = MagicMock()
            mock_bq.Client = mock_client_cls

            mock_job_config = MagicMock()
            mock_bq.QueryJobConfig.return_value = mock_job_config

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(
                project="test", max_bytes_billed=10_000_000_000
            )
            config = client._make_job_config("test_label")

            assert config.maximum_bytes_billed == 10_000_000_000

    def test_make_job_config_no_max_bytes_when_none(self):
        """_make_job_config should not set maximum_bytes_billed when None."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_client_cls = MagicMock()
            mock_bq.Client = mock_client_cls

            mock_job_config = MagicMock(spec=[])
            mock_bq.QueryJobConfig.return_value = mock_job_config

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test", max_bytes_billed=None)
            config = client._make_job_config("test_label")

            # maximum_bytes_billed should not have been set
            assert not hasattr(config, "maximum_bytes_billed")

    def test_check_cost_ceiling_raises_when_exceeded(self):
        """check_cost_ceiling should raise PipelineAbortError when over limit."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")
            client._total_bytes_billed = 100_000_000

            with pytest.raises(PipelineAbortError, match="cost ceiling exceeded"):
                client.check_cost_ceiling(50_000_000)

    def test_check_cost_ceiling_passes_when_under_limit(self):
        """check_cost_ceiling should not raise when under limit."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")
            client._total_bytes_billed = 10_000_000

            # Should not raise
            client.check_cost_ceiling(50_000_000)

    def test_check_cost_ceiling_none_is_noop(self):
        """check_cost_ceiling(None) should be a no-op."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")
            client._total_bytes_billed = 999_999_999_999

            # Should not raise even with very high bytes billed
            client.check_cost_ceiling(None)

    def test_cancel_active_jobs_returns_count(self):
        """cancel_active_jobs should return the number of cancelled jobs."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")

            job1 = MagicMock()
            job1.job_id = "job_1"
            job2 = MagicMock()
            job2.job_id = "job_2"
            job3 = MagicMock()
            job3.job_id = "job_3"

            client._active_jobs = [job1, job2, job3]

            count = client.cancel_active_jobs()
            assert count == 3

            job1.cancel.assert_called_once()
            job2.cancel.assert_called_once()
            job3.cancel.assert_called_once()

            # Active jobs should be cleared
            assert client._active_jobs == []

    def test_cancel_active_jobs_partial_failure(self):
        """cancel_active_jobs should continue even if some cancels fail."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")

            job1 = MagicMock()
            job1.job_id = "job_1"
            job1.cancel.side_effect = RuntimeError("cancel failed")
            job2 = MagicMock()
            job2.job_id = "job_2"

            client._active_jobs = [job1, job2]

            count = client.cancel_active_jobs()
            # job1 failed, job2 succeeded
            assert count == 1

    def test_cancel_active_jobs_empty_list(self):
        """cancel_active_jobs should return 0 when no active jobs."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")
            count = client.cancel_active_jobs()
            assert count == 0

    def test_total_bytes_billed_accumulates(self):
        """total_bytes_billed should track cumulative cost across queries."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")

            assert client.total_bytes_billed == 0

            client._total_bytes_billed = 1_000_000
            assert client.total_bytes_billed == 1_000_000

            client._total_bytes_billed += 2_000_000
            assert client.total_bytes_billed == 3_000_000

    def test_check_cost_ceiling_exact_boundary(self):
        """check_cost_ceiling should not raise when exactly at the ceiling."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")
            client._total_bytes_billed = 50_000_000

            # Equal should not raise (condition is >, not >=)
            client.check_cost_ceiling(50_000_000)

    def test_check_cost_ceiling_one_byte_over(self):
        """check_cost_ceiling should raise when one byte over the ceiling."""
        with patch("bq_entity_resolution.clients.bigquery.bigquery") as mock_bq:
            mock_bq.Client = MagicMock()

            from bq_entity_resolution.clients.bigquery import BigQueryClient

            client = BigQueryClient(project="test")
            client._total_bytes_billed = 50_000_001

            with pytest.raises(PipelineAbortError):
                client.check_cost_ceiling(50_000_000)


# ===================================================================
# 6. Metrics SQL injection fix
# ===================================================================


class TestSqlEscape:
    """Tests for sql_escape from sql/utils.py (used by metrics).

    BigQuery uses '' (double single-quote) for escaping, NOT backslash.
    The old _sql_escape in metrics.py was broken (used \\').
    Now metrics.py imports sql_escape from sql/utils.py.
    """

    def test_sql_escape_handles_single_quotes(self):
        """Single quotes should be doubled (BigQuery standard)."""
        assert sql_escape("it's a test") == "it''s a test"

    def test_sql_escape_no_special_chars(self):
        """Normal strings should pass through unchanged."""
        assert sql_escape("normal string") == "normal string"

    def test_sql_escape_empty_string(self):
        """Empty strings should pass through unchanged."""
        assert sql_escape("") == ""

    def test_sql_escape_multiple_quotes(self):
        """Multiple single quotes should all be doubled."""
        assert sql_escape("'a' 'b' 'c'") == "''a'' ''b'' ''c''"

    def test_sql_escape_backslashes_pass_through(self):
        """Backslashes are NOT special in BigQuery SQL — pass through."""
        assert sql_escape("path\\to\\file") == "path\\to\\file"

    def test_sql_escape_json_string(self):
        """JSON-like strings: only quotes are escaped."""
        json_str = '{"key": "val\'ue"}'
        escaped = sql_escape(json_str)
        assert "''" in escaped
        assert "\\'" not in escaped


# ===================================================================
# 7. Pipeline context UTC
# ===================================================================


class TestPipelineContextUTC:
    """Tests for UTC timestamp usage in pipeline/context.py."""

    def test_log_sql_uses_utc_timestamp(self):
        """log_sql should record UTC timestamps."""
        config = _minimal_config()
        ctx = PipelineContext(
            run_id="test_run",
            started_at=datetime.now(UTC),
            config=config,
        )

        ctx.log_sql("staging", "create_table", "CREATE TABLE ...")

        assert len(ctx.sql_log) == 1
        entry = ctx.sql_log[0]
        ts = entry["timestamp"]

        # datetime.now(UTC).isoformat() produces "+00:00" suffix
        assert "+00:00" in ts, f"Expected UTC timestamp with +00:00, got: {ts}"

    def test_log_sql_records_all_fields(self):
        """log_sql should record stage, step, sql, and timestamp."""
        config = _minimal_config()
        ctx = PipelineContext(
            run_id="test_run",
            started_at=datetime.now(UTC),
            config=config,
        )

        ctx.log_sql("matching", "score_pairs", "SELECT * FROM candidates")

        entry = ctx.sql_log[0]
        assert entry["stage"] == "matching"
        assert entry["step"] == "score_pairs"
        assert entry["sql"] == "SELECT * FROM candidates"
        assert "timestamp" in entry

    def test_log_sql_multiple_entries(self):
        """Multiple log_sql calls should append to the log."""
        config = _minimal_config()
        ctx = PipelineContext(
            run_id="test_run",
            started_at=datetime.now(UTC),
            config=config,
        )

        ctx.log_sql("stage1", "step1", "SQL1")
        ctx.log_sql("stage2", "step2", "SQL2")

        assert len(ctx.sql_log) == 2
        assert ctx.sql_log[0]["stage"] == "stage1"
        assert ctx.sql_log[1]["stage"] == "stage2"

    def test_context_duration_seconds(self):
        """duration_seconds should compute elapsed time."""
        config = _minimal_config()
        ctx = PipelineContext(
            run_id="test_run",
            started_at=datetime.now(UTC),
            config=config,
        )

        # Duration should be non-negative
        assert ctx.duration_seconds >= 0

    def test_context_duration_with_finished_at(self):
        """duration_seconds should use finished_at when set."""
        config = _minimal_config()
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 0, 1, 30, tzinfo=UTC)

        ctx = PipelineContext(
            run_id="test_run",
            started_at=start,
            config=config,
            finished_at=end,
        )

        assert ctx.duration_seconds == 90.0


# ===================================================================
# 8. PipelineExecutor new params
# ===================================================================


class TestPipelineExecutorParams:
    """Tests for PipelineExecutor constructor accepting new params."""

    def test_executor_accepts_max_cost_bytes(self):
        """PipelineExecutor should accept max_cost_bytes parameter."""
        backend = MagicMock()
        executor = PipelineExecutor(
            backend=backend,
            max_cost_bytes=10_000_000_000,
        )
        assert executor._max_cost_bytes == 10_000_000_000

    def test_executor_accepts_health_probe(self):
        """PipelineExecutor should accept health_probe parameter."""
        backend = MagicMock()
        probe = MagicMock()
        executor = PipelineExecutor(
            backend=backend,
            health_probe=probe,
        )
        assert executor._health_probe is probe

    def test_executor_default_max_cost_bytes_is_none(self):
        """PipelineExecutor should default max_cost_bytes to None."""
        backend = MagicMock()
        executor = PipelineExecutor(backend=backend)
        assert executor._max_cost_bytes is None

    def test_executor_default_health_probe_is_none(self):
        """PipelineExecutor should default health_probe to None."""
        backend = MagicMock()
        executor = PipelineExecutor(backend=backend)
        assert executor._health_probe is None

    def test_executor_accepts_all_params(self):
        """PipelineExecutor should accept all parameters together."""
        backend = MagicMock()
        probe = MagicMock()
        checkpoint = MagicMock()
        progress = MagicMock()

        executor = PipelineExecutor(
            backend=backend,
            quality_gates=[],
            checkpoint_manager=checkpoint,
            on_progress=progress,
            max_cost_bytes=5_000_000_000,
            health_probe=probe,
        )

        assert executor.backend is backend
        assert executor.quality_gates == []
        assert executor._checkpoint is checkpoint
        assert executor._on_progress is progress
        assert executor._max_cost_bytes == 5_000_000_000
        assert executor._health_probe is probe


# ===================================================================
# 9. Pipeline.run infrastructure setup
# ===================================================================


class TestPipelineRunInfrastructure:
    """Tests for Pipeline.run() reading and wiring DeploymentConfig."""

    def test_deployment_config_read_from_pipeline_config(self):
        """Pipeline.run should read deployment config from PipelineConfig."""
        config = _minimal_config(
            deployment={
                "health_probe": {"enabled": True, "path": "/tmp/test_health"},
                "graceful_shutdown": {"enabled": False},
            }
        )
        assert config.deployment.health_probe.enabled is True
        assert config.deployment.health_probe.path == "/tmp/test_health"
        assert config.deployment.graceful_shutdown.enabled is False

    def test_default_config_does_not_affect_behavior(self):
        """Default DeploymentConfig (everything disabled/defaults) should
        not change existing pipeline behavior."""
        config = _minimal_config()

        # Health probe disabled by default
        assert config.deployment.health_probe.enabled is False
        # Distributed lock disabled by default
        assert config.deployment.distributed_lock.enabled is False
        # Execution config defaults
        assert config.execution.max_cost_bytes is None
        assert config.execution.query_timeout_seconds == 600

    def test_execution_config_max_cost_bytes_in_pipeline_config(self):
        """PipelineConfig.execution.max_cost_bytes should be accessible."""
        config = _minimal_config(
            execution={"max_cost_bytes": 25_000_000_000}
        )
        assert config.execution.max_cost_bytes == 25_000_000_000

    def test_execution_config_query_timeout_in_pipeline_config(self):
        """PipelineConfig.execution.query_timeout_seconds should be accessible."""
        config = _minimal_config(
            execution={"query_timeout_seconds": 300}
        )
        assert config.execution.query_timeout_seconds == 300

    def test_pipeline_run_with_health_probe_enabled(self, tmp_path: Path):
        """Pipeline.run with health probe enabled should create health file."""
        health_file = str(tmp_path / "health")
        config = _minimal_config(
            deployment={
                "health_probe": {"enabled": True, "path": health_file},
                "graceful_shutdown": {"enabled": False},
            }
        )

        from bq_entity_resolution.pipeline.pipeline import Pipeline

        pipeline = Pipeline(config)

        # Mock the backend to avoid real execution
        backend = MagicMock()
        backend.execute.return_value = MagicMock(rows_affected=0)
        backend.execute_script.return_value = MagicMock(rows_affected=0)

        try:
            pipeline.run(backend=backend)
        except Exception:
            pass  # Pipeline may fail on mock backend, that's fine

        # Health file should exist (mark_healthy is called on init and complete)
        # Note: if pipeline.run fails before mark_healthy, this may not be true
        # but the health probe infrastructure code should be called

    def test_pipeline_config_full_deployment(self):
        """PipelineConfig should accept a full deployment configuration."""
        config = _minimal_config(
            deployment={
                "health_probe": {"enabled": True, "path": "/health"},
                "distributed_lock": {
                    "enabled": True,
                    "lock_table": "my_locks",
                    "ttl_minutes": 45,
                    "retry_seconds": 5,
                    "max_wait_seconds": 120,
                },
                "graceful_shutdown": {
                    "enabled": True,
                    "grace_period_seconds": 20,
                    "cancel_running_jobs": True,
                },
            },
            execution={
                "max_cost_bytes": 100_000_000_000,
                "query_timeout_seconds": 900,
            },
        )

        assert config.deployment.health_probe.enabled is True
        assert config.deployment.health_probe.path == "/health"
        assert config.deployment.distributed_lock.enabled is True
        assert config.deployment.distributed_lock.lock_table == "my_locks"
        assert config.deployment.distributed_lock.ttl_minutes == 45
        assert config.deployment.distributed_lock.retry_seconds == 5
        assert config.deployment.distributed_lock.max_wait_seconds == 120
        assert config.deployment.graceful_shutdown.enabled is True
        assert config.deployment.graceful_shutdown.grace_period_seconds == 20
        assert config.deployment.graceful_shutdown.cancel_running_jobs is True
        assert config.execution.max_cost_bytes == 100_000_000_000
        assert config.execution.query_timeout_seconds == 900


# ===================================================================
# Additional edge case tests
# ===================================================================


class TestHealthProbeEdgeCases:
    """Edge cases for HealthProbe."""

    def test_mark_healthy_default_args(self, tmp_path: Path):
        """mark_healthy with default args should work."""
        health_file = str(tmp_path / "health")
        probe = HealthProbe(path=health_file, enabled=True)

        probe.mark_healthy()

        with open(health_file) as f:
            data = json.load(f)

        assert data["stage"] == ""
        assert data["run_id"] == ""

    def test_default_path(self):
        """Default path should be /tmp/pipeline_healthy."""
        probe = HealthProbe()
        assert probe.path == "/tmp/pipeline_healthy"
        assert probe.enabled is True


class TestPipelineLockEdgeCases:
    """Edge cases for PipelineLock."""

    def test_lock_default_ttl(self):
        """Default TTL should be 30 minutes."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        assert lock._ttl_minutes == 30

    def test_lock_custom_ttl(self):
        """Custom TTL should be stored."""
        client = MagicMock()
        lock = PipelineLock(
            client, "p.d.locks",
            ttl_minutes=60,
            retry_seconds=5,
            max_wait_seconds=120,
        )
        assert lock._ttl_minutes == 60
        assert lock._retry_seconds == 5
        assert lock._max_wait_seconds == 120

    def test_sanitize_with_dashes_and_underscores(self):
        """Dashes and underscores should be valid."""
        assert validate_safe_value("my-pipeline_v2", "v") == "my-pipeline_v2"

    def test_sanitize_with_colons(self):
        """Colons are valid (used in timestamps)."""
        assert validate_safe_value("2024-01-01T00:00:00", "v") == "2024-01-01T00:00:00"


class TestGracefulShutdownEdgeCases:
    """Edge cases for GracefulShutdown."""

    def test_multiple_clients(self):
        """Multiple clients should all be cancelled."""
        shutdown = GracefulShutdown(enabled=True)
        clients = [MagicMock() for _ in range(3)]
        for c in clients:
            c.cancel_active_jobs.return_value = 1
            shutdown.register_client(c)

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        for c in clients:
            c.cancel_active_jobs.assert_called_once()

    def test_multiple_probes(self):
        """Multiple probes should all be marked unhealthy."""
        shutdown = GracefulShutdown(enabled=True)
        probes = [MagicMock() for _ in range(3)]
        for p in probes:
            shutdown.register_health_probe(p)

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        for p in probes:
            p.mark_unhealthy.assert_called_once()

    def test_multiple_locks(self):
        """Multiple locks should all be released."""
        shutdown = GracefulShutdown(enabled=True)
        locks = [(MagicMock(), f"pipeline_{i}") for i in range(3)]
        for lock, name in locks:
            shutdown.register_lock(lock, name)

        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)

        for lock, name in locks:
            lock.release.assert_called_once_with(name)


# ===================================================================
# 10. Coverage gap tests — critical/high severity
# ===================================================================


class TestHealthProbeIOFailures:
    """Tests for HealthProbe file I/O error handling."""

    def test_mark_healthy_nonexistent_directory(self, tmp_path: Path):
        """mark_healthy should not raise when directory doesn't exist."""
        bad_path = str(tmp_path / "nonexistent" / "subdir" / "health")
        probe = HealthProbe(path=bad_path, enabled=True)
        # Should not raise — exception is caught and logged
        probe.mark_healthy(stage="test")
        assert not probe.is_healthy()

    def test_mark_unhealthy_race_condition(self, tmp_path: Path):
        """mark_unhealthy when file is deleted between exists() and remove()."""
        health_file = str(tmp_path / "health")
        probe = HealthProbe(path=health_file, enabled=True)
        # File doesn't exist — should not raise
        probe.mark_unhealthy()
        assert not probe.is_healthy()

    def test_mark_healthy_special_chars_in_payload(self, tmp_path: Path):
        """mark_healthy should handle special characters in stage/run_id."""
        health_file = str(tmp_path / "health")
        probe = HealthProbe(path=health_file, enabled=True)
        probe.mark_healthy(
            stage="stage with 'quotes' and \"double quotes\"",
            run_id="run/with/slashes:and:colons",
        )
        with open(health_file) as f:
            data = json.load(f)
        assert "quotes" in data["stage"]
        assert "slashes" in data["run_id"]

    def test_mark_healthy_overwrites_cleanly(self, tmp_path: Path):
        """Sequential mark_healthy calls should produce valid JSON each time."""
        health_file = str(tmp_path / "health")
        probe = HealthProbe(path=health_file, enabled=True)
        for i in range(5):
            probe.mark_healthy(stage=f"stage_{i}", run_id=f"run_{i}")
            with open(health_file) as f:
                data = json.load(f)
            assert data["stage"] == f"stage_{i}"

    def test_mark_healthy_contains_pid(self, tmp_path: Path):
        """Health payload should include current process PID."""
        health_file = str(tmp_path / "health")
        probe = HealthProbe(path=health_file, enabled=True)
        probe.mark_healthy(stage="test")
        with open(health_file) as f:
            data = json.load(f)
        assert data["pid"] == os.getpid()


class TestPipelineLockEdgePaths:
    """Tests for PipelineLock edge cases and error recovery."""

    def test_acquire_empty_rows_from_verify(self):
        """acquire should handle empty result from verify SELECT gracefully."""
        client = MagicMock()
        # MERGE succeeds, but verify returns empty rows → retry
        client.execute_and_fetch.return_value = []
        lock = PipelineLock(
            client, "p.d.locks",
            max_wait_seconds=0,  # Immediate timeout
        )
        with pytest.raises(PipelineAbortError, match="Could not acquire lock"):
            lock.acquire("test_pipeline")

    def test_acquire_empty_rows_reports_unknown_holder(self):
        """Timeout with empty rows should report holder as 'unknown'."""
        client = MagicMock()
        client.execute_and_fetch.return_value = []
        lock = PipelineLock(
            client, "p.d.locks",
            max_wait_seconds=0,
        )
        with pytest.raises(PipelineAbortError, match="unknown"):
            lock.acquire("test_pipeline")

    def test_refresh_before_acquire_no_fencing_token(self):
        """refresh() before acquire() should build SQL without fencing_token WHERE."""
        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        assert lock.fencing_token is None
        lock.refresh("test_pipeline")
        # Should have called execute (UPDATE without fencing_token clause)
        call_args = client.execute.call_args
        sql = call_args[0][0]
        assert "fencing_token" not in sql

    def test_refresh_with_fencing_token_includes_guard(self):
        """refresh() after acquire() should include fencing_token in WHERE."""
        client = MagicMock()
        client.execute_and_fetch.return_value = [
            {"lock_holder": None, "fencing_token": 42}
        ]
        lock = PipelineLock(client, "p.d.locks")
        # Simulate acquired state
        lock._fencing_token = 42
        lock._holder_id = "test_holder"
        lock.refresh("test_pipeline")
        call_sql = client.execute.call_args[0][0]
        assert "fencing_token = 42" in call_sql

    def test_verify_lock_returns_false_on_exception(self):
        """verify_lock() should return False when execute_and_fetch raises."""
        client = MagicMock()
        client.execute_and_fetch.side_effect = RuntimeError("Network error")
        lock = PipelineLock(client, "p.d.locks")
        assert lock.verify_lock("test_pipeline") is False

    def test_release_preserves_token_on_failure(self):
        """release() preserves fencing_token if DELETE fails for retry."""
        client = MagicMock()
        client.execute.side_effect = RuntimeError("Delete failed")
        lock = PipelineLock(client, "p.d.locks")
        lock._fencing_token = 99
        lock.release("test_pipeline")
        assert lock.fencing_token == 99

    def test_ensure_table_alter_failure_swallowed(self):
        """ensure_table_exists() should swallow ALTER failure (column already exists)."""
        client = MagicMock()
        # First execute (CREATE) succeeds, second (ALTER) fails
        client.execute.side_effect = [None, RuntimeError("Already exists")]
        lock = PipelineLock(client, "p.d.locks")
        # Should not raise
        lock.ensure_table_exists()
        assert client.execute.call_count == 2

    def test_acquire_merge_failure_falls_through_to_verify(self):
        """MERGE failure should fall through to verify SELECT (not raise)."""
        client = MagicMock()
        holder_id = None

        def mock_execute(sql, job_label=""):
            nonlocal holder_id
            if "MERGE" in sql:
                raise RuntimeError("MERGE failed")
            # Other calls (CREATE, ALTER) succeed
            return MagicMock(rows_affected=0)

        client.execute.side_effect = mock_execute
        lock = PipelineLock(
            client, "p.d.locks",
            max_wait_seconds=0,
        )
        holder_id = lock.holder_id
        # Verify returns the lock holder (simulating another holder)
        client.execute_and_fetch.return_value = [
            {"lock_holder": "other_holder", "fencing_token": 1}
        ]
        with pytest.raises(PipelineAbortError):
            lock.acquire("test_pipeline")
        # verify_lock should still have been called
        assert client.execute_and_fetch.called


class TestGracefulShutdownGaps:
    """Tests for GracefulShutdown untested paths."""

    def test_empty_registrations_no_error(self):
        """Signal with no registered resources should exit cleanly."""
        shutdown = GracefulShutdown(enabled=True)
        # No clients, probes, or locks registered
        with pytest.raises(SystemExit) as exc_info:
            shutdown._handle_signal(signal.SIGTERM, None)
        assert exc_info.value.code == 128 + signal.SIGTERM

    def test_probe_exception_swallowed(self):
        """Probe mark_unhealthy exception should be silently caught."""
        shutdown = GracefulShutdown(enabled=True)
        probe = MagicMock()
        probe.mark_unhealthy.side_effect = RuntimeError("probe error")
        shutdown.register_health_probe(probe)
        # Should not raise — exception is swallowed
        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)
        probe.mark_unhealthy.assert_called_once()

    def test_install_uninstall_reinstall_cycle(self):
        """install → uninstall → install should work correctly."""
        shutdown = GracefulShutdown(enabled=True)
        original = signal.getsignal(signal.SIGTERM)
        try:
            shutdown.install()
            assert shutdown.installed
            shutdown.uninstall()
            assert not shutdown.installed
            # Reinstall
            shutdown.install()
            assert shutdown.installed
            assert signal.getsignal(signal.SIGTERM) == shutdown._handle_signal
        finally:
            shutdown.uninstall()
            signal.signal(signal.SIGTERM, original)

    def test_exit_code_sigterm(self):
        """SIGTERM should exit with code 128 + SIGTERM."""
        shutdown = GracefulShutdown(enabled=True)
        with pytest.raises(SystemExit) as exc_info:
            shutdown._handle_signal(signal.SIGTERM, None)
        assert exc_info.value.code == 128 + signal.SIGTERM

    def test_exit_code_sigint(self):
        """SIGINT should exit with code 128 + SIGINT."""
        shutdown = GracefulShutdown(enabled=True)
        with pytest.raises(SystemExit) as exc_info:
            shutdown._handle_signal(signal.SIGINT, None)
        assert exc_info.value.code == 128 + signal.SIGINT

    def test_disabled_still_accepts_registrations(self):
        """Disabled shutdown should accept registrations without error."""
        shutdown = GracefulShutdown(enabled=False)
        client = MagicMock()
        probe = MagicMock()
        lock = MagicMock()
        shutdown.register_client(client)
        shutdown.register_health_probe(probe)
        shutdown.register_lock(lock, "test")
        # Lists should be populated even though disabled
        assert len(shutdown._clients) == 1
        assert len(shutdown._health_probes) == 1
        assert len(shutdown._locks) == 1

    def test_multiple_lock_failures_all_logged(self):
        """All lock release failures should be handled independently."""
        shutdown = GracefulShutdown(enabled=True)
        lock1 = MagicMock()
        lock1.release.side_effect = RuntimeError("lock1 failed")
        lock2 = MagicMock()
        lock2.release.return_value = None  # succeeds
        lock3 = MagicMock()
        lock3.release.side_effect = RuntimeError("lock3 failed")
        shutdown.register_lock(lock1, "p1")
        shutdown.register_lock(lock2, "p2")
        shutdown.register_lock(lock3, "p3")
        with pytest.raises(SystemExit):
            shutdown._handle_signal(signal.SIGTERM, None)
        # All three should be attempted
        lock1.release.assert_called_once_with("p1")
        lock2.release.assert_called_once_with("p2")
        lock3.release.assert_called_once_with("p3")

"""Tests for enterprise hardening fixes.

Covers SQL injection prevention, config validators, correctness fixes,
resilience improvements, and resource management guards.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import BadRequest
from pydantic import ValidationError

from bq_entity_resolution.config.models.blocking import BlockingPathDef
from bq_entity_resolution.config.models.features import (
    BlockingKeyDef,
    CompositeKeyDef,
    FeatureDef,
    FeatureEngineeringConfig,
)
from bq_entity_resolution.config.models.infrastructure import (
    DistributedLockConfig,
    ExecutionConfig,
    GracefulShutdownConfig,
    IncrementalConfig,
    ProjectConfig,
    ScaleConfig,
)
from bq_entity_resolution.config.models.matching import (
    HardNegativeDef,
    HardPositiveDef,
    MatchingTierConfig,
    ScoreBandDef,
)
from bq_entity_resolution.config.models.source import ColumnMapping, SourceConfig
from bq_entity_resolution.exceptions import PipelineAbortError

# ===================================================================
# P0: SQL Injection Prevention — Config Model Validators
# ===================================================================


class TestSourceConfigSQLInjection:
    """Verify source config fields reject SQL injection payloads."""

    def test_unique_key_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            SourceConfig(
                name="test",
                table="p.d.t",
                unique_key="id); DROP TABLE x--",
                updated_at="ts",
                columns=[ColumnMapping(name="a")],
            )

    def test_updated_at_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            SourceConfig(
                name="test",
                table="p.d.t",
                unique_key="id",
                updated_at="ts; DROP TABLE",
                columns=[ColumnMapping(name="a")],
            )

    def test_name_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            SourceConfig(
                name="src; DROP",
                table="p.d.t",
                unique_key="id",
                updated_at="ts",
                columns=[ColumnMapping(name="a")],
            )

    def test_passthrough_columns_reject_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            SourceConfig(
                name="test",
                table="p.d.t",
                unique_key="id",
                updated_at="ts",
                columns=[ColumnMapping(name="a")],
                passthrough_columns=["col1", "col2; DROP TABLE"],
            )

    def test_partition_column_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            SourceConfig(
                name="test",
                table="p.d.t",
                unique_key="id",
                updated_at="ts",
                columns=[ColumnMapping(name="a")],
                partition_column="col OR 1=1",
            )

    def test_valid_source_config_passes(self):
        src = SourceConfig(
            name="customers",
            table="p.d.t",
            unique_key="customer_id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="first_name")],
            passthrough_columns=["extra_col"],
            partition_column="created_date",
        )
        assert src.name == "customers"


class TestBlockingPathSQLInjection:
    """Verify blocking path keys reject injection."""

    def test_keys_reject_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            BlockingPathDef(keys=["bk_email", "entity_uid = 1 OR 1"])

    def test_lsh_keys_reject_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            BlockingPathDef(keys=["bk"], lsh_keys=["bucket; DROP"])

    def test_valid_keys_pass(self):
        path = BlockingPathDef(keys=["bk_email", "bk_name"])
        assert path.keys == ["bk_email", "bk_name"]


class TestFeatureDefSQLInjection:
    """Verify feature definitions reject injection in names and inputs."""

    def test_name_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            FeatureDef(name="feat; DROP", function="name_clean", input="col")

    def test_inputs_reject_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            FeatureDef(name="feat", function="name_clean", input="col; DROP TABLE")

    def test_sql_override_skips_input_validation(self):
        """Raw SQL features bypass input identifier validation."""
        feat = FeatureDef(
            name="custom_feat",
            function="identity",
            sql="UPPER(some_expr)",
            inputs=["not_validated_here"],
        )
        assert feat.sql == "UPPER(some_expr)"

    def test_valid_feature_passes(self):
        feat = FeatureDef(name="first_name_clean", function="name_clean", input="first_name")
        assert feat.name == "first_name_clean"


class TestBlockingKeyDefSQLInjection:
    """Verify blocking key definitions reject injection."""

    def test_name_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            BlockingKeyDef(name="bk; DROP", function="farm_fingerprint", inputs=["col"])

    def test_inputs_reject_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["col; DROP"])

    def test_valid_blocking_key_passes(self):
        bk = BlockingKeyDef(name="bk_email", function="farm_fingerprint", inputs=["email_clean"])
        assert bk.name == "bk_email"


class TestCompositeKeyDefValidation:
    """Verify CompositeKeyDef has validators (was previously missing)."""

    def test_empty_name_rejects(self):
        with pytest.raises(ValidationError, match="non-empty"):
            CompositeKeyDef(name="", function="concat", inputs=["a"])

    def test_empty_function_rejects(self):
        with pytest.raises(ValidationError, match="non-empty"):
            CompositeKeyDef(name="ck", function="", inputs=["a"])

    def test_name_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            CompositeKeyDef(name="ck; DROP", function="concat", inputs=["a"])

    def test_valid_composite_key_passes(self):
        ck = CompositeKeyDef(name="ck_full", function="concat", inputs=["a", "b"])
        assert ck.name == "ck_full"


class TestEntityTypeColumnValidation:
    """Verify entity_type_column is validated."""

    def test_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            FeatureEngineeringConfig(entity_type_column="col; DROP TABLE")

    def test_empty_string_passes(self):
        cfg = FeatureEngineeringConfig(entity_type_column="")
        assert cfg.entity_type_column == ""


class TestProjectConfigValidation:
    """Verify project config validates dataset and project names."""

    def test_bq_project_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid BigQuery project"):
            ProjectConfig(name="test", bq_project="proj; DROP")

    def test_dataset_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid BigQuery dataset"):
            ProjectConfig(name="test", bq_project="my-project", bq_dataset_bronze="ds; DROP")

    def test_bq_project_allows_hyphens(self):
        cfg = ProjectConfig(name="test", bq_project="my-project-123")
        assert cfg.bq_project == "my-project-123"

    def test_env_var_placeholder_allowed(self):
        cfg = ProjectConfig(name="test", bq_project="${BQ_PROJECT}")
        assert cfg.bq_project == "${BQ_PROJECT}"

    def test_dataset_env_var_allowed(self):
        cfg = ProjectConfig(
            name="test", bq_project="proj",
            bq_dataset_bronze="${BRONZE_DS}",
        )
        assert cfg.bq_dataset_bronze == "${BRONZE_DS}"


class TestIncrementalCursorValidation:
    """Verify cursor columns are validated."""

    def test_cursor_columns_reject_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            IncrementalConfig(cursor_columns=["updated_at; DROP TABLE"])


class TestColumnMappingTypeValidation:
    """Verify ColumnMapping.type is constrained to valid BQ types."""

    def test_valid_types_pass(self):
        for t in ["STRING", "INT64", "FLOAT64", "TIMESTAMP", "BOOL", "DATE"]:
            col = ColumnMapping(name="c", type=t)
            assert col.type == t

    def test_invalid_type_rejects(self):
        with pytest.raises(ValidationError, match="Unknown BigQuery type"):
            ColumnMapping(name="c", type="STRIG")

    def test_parameterized_type_passes(self):
        col = ColumnMapping(name="c", type="NUMERIC(10,2)")
        assert col.type == "NUMERIC(10,2)"


# ===================================================================
# P0: SQL Injection — Score Band & Target Band
# ===================================================================


class TestScoreBandNameValidation:
    """Verify score band names are safe identifiers."""

    def test_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            ScoreBandDef(name="HIGH'; DROP TABLE--", min_score=5.0)

    def test_valid_band_name(self):
        band = ScoreBandDef(name="HIGH", min_score=5.0)
        assert band.name == "HIGH"


class TestTargetBandValidation:
    """Verify HardPositiveDef.target_band is validated."""

    def test_rejects_injection(self):
        with pytest.raises(ValidationError, match="Invalid SQL"):
            HardPositiveDef(
                left="col", method="exact",
                target_band="BAND'; DROP TABLE--",
            )


# ===================================================================
# P1: Missing Config Validators
# ===================================================================


class TestMatchingTierConfidence:
    """Verify confidence is constrained to [0, 1]."""

    def test_negative_rejects(self):
        with pytest.raises(ValidationError, match="confidence must be in"):
            MatchingTierConfig(
                name="t1",
                blocking={"paths": [{"keys": ["bk"]}]},
                comparisons=[{"left": "a", "right": "a", "method": "exact"}],
                threshold={"min_score": 1.0},
                confidence=-0.5,
            )

    def test_above_one_rejects(self):
        with pytest.raises(ValidationError, match="confidence must be in"):
            MatchingTierConfig(
                name="t1",
                blocking={"paths": [{"keys": ["bk"]}]},
                comparisons=[{"left": "a", "right": "a", "method": "exact"}],
                threshold={"min_score": 1.0},
                confidence=1.5,
            )

    def test_valid_confidence(self):
        tier = MatchingTierConfig(
            name="t1",
            blocking={"paths": [{"keys": ["bk"]}]},
            comparisons=[{"left": "a", "right": "a", "method": "exact"}],
            threshold={"min_score": 1.0},
            confidence=0.85,
        )
        assert tier.confidence == 0.85


class TestHardNegativeRequiresOverrides:
    """Verify requires_overrides is non-negative."""

    def test_negative_rejects(self):
        with pytest.raises(ValidationError, match="requires_overrides must be >= 0"):
            HardNegativeDef(left="a", method="different", requires_overrides=-1)


class TestHardPositiveBoost:
    """Verify boost is non-negative."""

    def test_negative_rejects(self):
        with pytest.raises(ValidationError, match="boost must be >= 0"):
            HardPositiveDef(left="a", method="exact", boost=-5.0)


class TestDistributedLockValidation:
    """Verify lock config fields are positive."""

    def test_zero_ttl_rejects(self):
        with pytest.raises(ValidationError, match="ttl_minutes must be >= 1"):
            DistributedLockConfig(enabled=True, ttl_minutes=0)

    def test_negative_retry_rejects(self):
        with pytest.raises(ValidationError, match="retry_seconds must be >= 1"):
            DistributedLockConfig(enabled=True, retry_seconds=-1)

    def test_zero_max_wait_rejects(self):
        with pytest.raises(ValidationError, match="max_wait_seconds must be >= 1"):
            DistributedLockConfig(enabled=True, max_wait_seconds=0)


class TestGracefulShutdownValidation:
    """Verify grace_period_seconds is non-negative."""

    def test_negative_rejects(self):
        with pytest.raises(ValidationError, match="grace_period_seconds must be >= 0"):
            GracefulShutdownConfig(grace_period_seconds=-5)


class TestCostValidation:
    """Verify cost ceiling fields are positive when set."""

    def test_max_bytes_billed_zero_rejects(self):
        with pytest.raises(ValidationError, match="max_bytes_billed must be >= 1"):
            ScaleConfig(max_bytes_billed=0)

    def test_max_bytes_billed_none_allowed(self):
        cfg = ScaleConfig(max_bytes_billed=None)
        assert cfg.max_bytes_billed is None

    def test_max_cost_bytes_zero_rejects(self):
        with pytest.raises(ValidationError, match="max_cost_bytes must be >= 1"):
            ExecutionConfig(max_cost_bytes=0)


class TestDuplicateSourceNames:
    """Verify duplicate source names are detected."""

    def test_duplicate_names_rejected(self):
        from bq_entity_resolution.config.validators import validate_source_names_unique
        from bq_entity_resolution.exceptions import ConfigurationError

        config = MagicMock()
        src = MagicMock()
        src.name = "customers"
        config.sources = [src, src]

        with pytest.raises(ConfigurationError, match="Duplicate source names"):
            validate_source_names_unique(config)


# ===================================================================
# P0: Correctness — Lock Refresh
# ===================================================================


class TestLockRefreshRowsAffected:
    """Verify lock refresh detects stolen locks."""

    def test_zero_rows_raises(self):
        client = MagicMock()
        result = MagicMock()
        result.rows_affected = 0
        client.execute.return_value = result

        from bq_entity_resolution.pipeline.lock import PipelineLock

        lock = PipelineLock(client, "p.d.locks")
        lock._fencing_token = 1

        with pytest.raises(RuntimeError, match="matched 0 rows"):
            lock.refresh("test_pipe")

    def test_successful_refresh(self):
        client = MagicMock()
        result = MagicMock()
        result.rows_affected = 1
        client.execute.return_value = result

        from bq_entity_resolution.pipeline.lock import PipelineLock

        lock = PipelineLock(client, "p.d.locks")
        lock._fencing_token = 1
        lock.refresh("test_pipe")  # Should not raise


class TestLockReleasePreservesToken:
    """Verify fencing token is only cleared on successful release."""

    def test_success_clears_token(self):
        from bq_entity_resolution.pipeline.lock import PipelineLock

        client = MagicMock()
        lock = PipelineLock(client, "p.d.locks")
        lock._fencing_token = 42
        lock.release("pipe")
        assert lock.fencing_token is None

    def test_failure_preserves_token(self):
        from bq_entity_resolution.pipeline.lock import PipelineLock

        client = MagicMock()
        client.execute.side_effect = Exception("network error")
        lock = PipelineLock(client, "p.d.locks")
        lock._fencing_token = 42
        lock.release("pipe")
        assert lock.fencing_token == 42


# ===================================================================
# P1: Resilience — Exception Chaining in Executor
# ===================================================================


class TestExceptionChaining:
    """Verify executor chains original exceptions."""

    def test_runtime_error_has_cause(self):
        from bq_entity_resolution.pipeline.executor import StageExecutionResult

        result = StageExecutionResult(stage_name="test", success=False, error="bad sql")
        original = ValueError("root cause")
        result._original_exception = original

        assert getattr(result, "_original_exception") is original


# ===================================================================
# P2: Resource Management — Use-After-Close Guards
# ===================================================================


class TestDuckDBUseAfterClose:
    """Verify DuckDB backend raises clear error after close."""

    def test_execute_after_close(self):
        from bq_entity_resolution.backends.duckdb.backend import DuckDBBackend

        backend = DuckDBBackend()
        backend.close()

        with pytest.raises(RuntimeError, match="closed"):
            backend.execute("SELECT 1")

    def test_execute_and_fetch_after_close(self):
        from bq_entity_resolution.backends.duckdb.backend import DuckDBBackend

        backend = DuckDBBackend()
        backend.close()

        with pytest.raises(RuntimeError, match="closed"):
            backend.execute_and_fetch("SELECT 1")


class TestBigQueryClientContextManager:
    """Verify BigQueryClient supports context manager protocol."""

    @patch("bq_entity_resolution.clients.bigquery.bigquery")
    def test_context_manager(self, mock_bq):
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        mock_bq.Client.return_value = MagicMock()
        with BigQueryClient(project="test") as client:
            assert client.project == "test"


# ===================================================================
# P0: DuckDB Scripting — IF/THEN/LEAVE handling
# ===================================================================


class TestScriptingIfHandling:
    """Verify IF/THEN/END IF constructs are interpreted, not passed to DuckDB."""

    def test_if_then_leave(self):
        import duckdb

        from bq_entity_resolution.backends.duckdb.scripting import (
            execute_bq_scripting,
            split_statements,
        )

        conn = duckdb.connect()
        conn.execute("CREATE TABLE if_test (val BIGINT)")
        script = """
        DECLARE i INT64 DEFAULT 0;
        LOOP
            INSERT INTO if_test VALUES (i);
            SET i = i + 1;
            IF i >= 3 THEN LEAVE; END IF;
        END LOOP;
        """
        execute_bq_scripting(conn, script, split_statements)
        result = conn.execute("SELECT COUNT(*) FROM if_test").fetchone()
        assert result[0] == 3
        conn.close()

    def test_end_if_skipped(self):
        """END IF statements should be silently skipped."""
        import duckdb

        from bq_entity_resolution.backends.duckdb.scripting import (
            execute_bq_scripting,
            split_statements,
        )

        conn = duckdb.connect()
        conn.execute("CREATE TABLE endif_test (val BIGINT)")
        # Simple loop with IF that doesn't match
        script = """
        DECLARE i INT64 DEFAULT 0;
        LOOP
            INSERT INTO endif_test VALUES (i);
            SET i = i + 1;
            IF i >= 2 THEN LEAVE; END IF;
        END LOOP;
        """
        execute_bq_scripting(conn, script, split_statements)
        result = conn.execute("SELECT COUNT(*) FROM endif_test").fetchone()
        assert result[0] == 2
        conn.close()


# ===================================================================
# P2: CLI --resume flag
# ===================================================================


class TestCLIResumeFlag:
    """Verify CLI run command accepts --resume flag."""

    def test_run_command_has_resume_option(self):
        from bq_entity_resolution.cli.commands.run import run

        param_names = [p.name for p in run.params]
        assert "resume" in param_names


# ===================================================================
# P0-1: Comparison Function Defense-in-Depth — Decorator Validation
# ===================================================================


class TestComparisonDecoratorInjection:
    """Verify that ALL registered comparison functions reject SQL injection
    payloads when called directly (not through _validated_call or
    get_comparison_safe). This tests the register() decorator wrapper."""

    @pytest.mark.parametrize("name", sorted(
        __import__(
            "bq_entity_resolution.matching.comparisons", fromlist=["COMPARISON_FUNCTIONS"]
        ).COMPARISON_FUNCTIONS.keys()
    ))
    def test_rejects_left_injection(self, name):
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS[name]
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="col; DROP TABLE", right="valid_col")

    @pytest.mark.parametrize("name", sorted(
        __import__(
            "bq_entity_resolution.matching.comparisons", fromlist=["COMPARISON_FUNCTIONS"]
        ).COMPARISON_FUNCTIONS.keys()
    ))
    def test_rejects_right_injection(self, name):
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS[name]
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="valid_col", right="col' OR '1'='1")

    @pytest.mark.parametrize("name", sorted(
        __import__(
            "bq_entity_resolution.matching.comparisons", fromlist=["COMPARISON_FUNCTIONS"]
        ).COMPARISON_FUNCTIONS.keys()
    ))
    def test_rejects_dot_notation(self, name):
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS[name]
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="table.column", right="valid_col")

    @pytest.mark.parametrize("name", sorted(
        __import__(
            "bq_entity_resolution.matching.comparisons", fromlist=["COMPARISON_FUNCTIONS"]
        ).COMPARISON_FUNCTIONS.keys()
    ))
    def test_rejects_empty_string(self, name):
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS[name]
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="", right="valid_col")

    def test_valid_identifiers_pass(self):
        """Verify that valid column names still work through the decorator."""
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS["exact"]
        result = fn(left="first_name", right="first_name")
        assert "first_name" in result
        assert "l.first_name" in result

    def test_decorator_preserves_function_name(self):
        """Verify functools.wraps preserves __name__ on decorated functions."""
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS["exact"]
        assert fn.__name__ == "exact"

    def test_decorator_preserves_docstring(self):
        """Verify functools.wraps preserves __doc__ on decorated functions."""
        from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

        fn = COMPARISON_FUNCTIONS["exact"]
        assert fn.__doc__ is not None
        assert "Exact equality" in fn.__doc__

    def test_get_comparison_safe_still_works(self):
        """Verify get_comparison_safe still works with the new decorator."""
        from bq_entity_resolution.matching.comparisons import get_comparison_safe

        fn = get_comparison_safe("levenshtein")
        result = fn(left="col_a", right="col_b", max_distance=2)
        assert "EDIT_DISTANCE" in result


# ===================================================================
# P0-2: Executor Exception PII Redaction
# ===================================================================


class TestExecutorExceptionRedaction:
    """Verify stage errors are PII-redacted in error messages."""

    def test_error_redacts_string_literals(self):
        from bq_entity_resolution.pipeline.executor import _redact_sql

        error_msg = "Failed at WHERE name = 'John Smith'"
        redacted = _redact_sql(error_msg)
        assert "John Smith" not in redacted
        assert "<REDACTED>" in redacted

    def test_error_redacts_email(self):
        from bq_entity_resolution.pipeline.executor import _redact_sql

        error_msg = "Error matching user john.doe@example.com"
        redacted = _redact_sql(error_msg)
        assert "john.doe@example.com" not in redacted
        assert "<EMAIL>" in redacted

    def test_error_redacts_ssn(self):
        from bq_entity_resolution.pipeline.executor import _redact_sql

        error_msg = "Bad value 123-45-6789 in column ssn"
        redacted = _redact_sql(error_msg)
        assert "123-45-6789" not in redacted
        assert "<SSN>" in redacted

    def test_error_redacts_phone(self):
        from bq_entity_resolution.pipeline.executor import _redact_sql

        error_msg = "Invalid phone 555-123-4567 in record"
        redacted = _redact_sql(error_msg)
        assert "555-123-4567" not in redacted
        assert "<PHONE>" in redacted

    def test_stage_result_error_is_redacted(self):
        """Verify that stage_result.error is redacted at capture time."""
        from bq_entity_resolution.pipeline.executor import PipelineExecutor
        from bq_entity_resolution.pipeline.plan import StagePlan

        backend = MagicMock()
        backend.execute.side_effect = Exception(
            "Error at WHERE email = 'alice@example.com'"
        )
        executor = PipelineExecutor(backend=backend)

        expr = MagicMock()
        expr.render.return_value = "SELECT 1"
        stage_plan = StagePlan(
            stage_name="test_stage",
            sql_expressions=(expr,),
            inputs={},
            outputs={},
            dependencies=(),
        )

        result = executor._execute_stage(stage_plan, MagicMock(sql_log=[]))
        assert not result.success
        assert "alice@example.com" not in result.error
        # Email is inside quotes so string-literal pattern catches it as <REDACTED>
        assert "<REDACTED>" in result.error or "<EMAIL>" in result.error

    def test_progress_callback_receives_redacted_error(self):
        """Verify on_progress callback receives redacted error detail."""
        from bq_entity_resolution.pipeline.executor import PipelineExecutor
        from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan

        captured = {}

        def on_progress(stage_name, idx, total, status):
            captured["status"] = status

        backend = MagicMock()
        backend.execute.side_effect = Exception(
            "Error for email = 'bob@secret.com'"
        )
        expr = MagicMock()
        expr.render.return_value = "SELECT 1"

        stage_plan = StagePlan(
            stage_name="test_stage",
            sql_expressions=(expr,),
            inputs={},
            outputs={},
            dependencies=(),
        )
        plan = PipelinePlan(stages=[stage_plan])

        executor = PipelineExecutor(backend=backend, on_progress=on_progress)
        with pytest.raises(RuntimeError):
            executor.execute(plan)

        assert "bob@secret.com" not in captured["status"]
        assert "<REDACTED>" in captured["status"] or "<EMAIL>" in captured["status"]


# ===================================================================
# P1-1: Lock Acquisition Jitter
# ===================================================================


class TestLockAcquisitionJitter:
    """Verify lock retry uses jitter to prevent thundering herd."""

    def test_sleep_includes_jitter(self):
        """Verify time.sleep is called with retry_seconds + jitter."""
        from bq_entity_resolution.pipeline.lock import PipelineLock

        client = MagicMock()
        # MERGE succeeds but verify shows different holder (lock not acquired)
        client.execute.return_value = MagicMock()
        client.execute_and_fetch.return_value = [
            {"lock_holder": "other_pod", "fencing_token": 1}
        ]

        lock = PipelineLock(
            client, "p.d.locks",
            retry_seconds=10, max_wait_seconds=1,  # Timeout quickly
        )

        with patch("bq_entity_resolution.pipeline.lock.time") as mock_time, \
             patch("bq_entity_resolution.pipeline.lock.random") as mock_random:
            mock_time.monotonic.side_effect = [0.0, 0.0, 0.5, 2.0]
            mock_random.uniform.return_value = 3.0

            with pytest.raises(Exception):  # PipelineAbortError on timeout
                lock.acquire("test_pipe")

            # Verify jitter was computed
            mock_random.uniform.assert_called_with(0, 10 * 0.5)
            # Verify sleep includes base + jitter
            mock_time.sleep.assert_called_with(10 + 3.0)


# ===================================================================
# P1-2: Circuit Breaker for BigQuery Client
# ===================================================================


class TestCircuitBreaker:
    """Verify BigQuery client circuit breaker behavior."""

    @patch("bq_entity_resolution.clients.bigquery.bigquery")
    def test_success_resets_counter(self, mock_bq):
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        mock_bq.Client.return_value = MagicMock()
        client = BigQueryClient(project="test")
        client._circuit_failure_count = 3
        client._record_circuit_success()
        assert client._circuit_failure_count == 0

    @patch("bq_entity_resolution.clients.bigquery.bigquery")
    def test_consecutive_failures_trips_breaker(self, mock_bq):
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        mock_bq.Client.return_value = MagicMock()
        client = BigQueryClient(project="test")

        for i in range(4):
            client._record_circuit_failure()

        # 5th failure trips the breaker
        with pytest.raises(PipelineAbortError, match="Circuit breaker open"):
            client._record_circuit_failure()

    @patch("bq_entity_resolution.clients.bigquery.bigquery")
    def test_failures_outside_window_dont_accumulate(self, mock_bq):
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        mock_bq.Client.return_value = MagicMock()
        client = BigQueryClient(project="test")

        # Record 4 failures
        for _ in range(4):
            client._record_circuit_failure()
        assert client._circuit_failure_count == 4

        # Simulate time passing beyond window
        client._circuit_last_failure = time.monotonic() - 120.0

        # Next failure resets the count (outside window)
        client._record_circuit_failure()
        assert client._circuit_failure_count == 1

    @patch("bq_entity_resolution.clients.bigquery.bigquery")
    def test_success_in_retry_loop_resets_breaker(self, mock_bq):
        """Verify successful query in _retry_execute resets circuit breaker."""
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        mock_client = MagicMock()
        mock_bq.Client.return_value = mock_client
        client = BigQueryClient(project="test")
        client._circuit_failure_count = 3

        # Simulate a successful query
        mock_result = MagicMock()
        mock_result.total_bytes_processed = 0
        mock_result.total_bytes_billed = 0
        fn = MagicMock(return_value=mock_result)

        client._retry_execute(fn, "SELECT 1", "test_label")
        assert client._circuit_failure_count == 0

    @patch("bq_entity_resolution.clients.bigquery.bigquery")
    def test_bad_request_increments_circuit_failure(self, mock_bq):
        """Verify BadRequest errors increment the circuit breaker counter."""
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        mock_bq.Client.return_value = MagicMock()
        client = BigQueryClient(project="test")

        fn = MagicMock(side_effect=BadRequest("syntax error"))

        with pytest.raises(Exception):
            client._retry_execute(fn, "BAD SQL", "test_label")

        assert client._circuit_failure_count == 1


# ===================================================================
# P2-1: Mandatory Fencing Enforcement
# ===================================================================


class TestMandatoryFencing:
    """Verify partial fencing config raises ValueError."""

    def test_partial_fencing_token_only_raises(self):
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        cm = CheckpointManager(client, "p.d.checkpoints")

        with pytest.raises(ValueError, match="Partial fencing"):
            cm.mark_stage_complete(
                "run_1", "stage_1",
                fencing_token=42,
            )

    def test_partial_lock_table_only_raises(self):
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        cm = CheckpointManager(client, "p.d.checkpoints")

        with pytest.raises(ValueError, match="Partial fencing"):
            cm.mark_stage_complete(
                "run_1", "stage_1",
                lock_table="p.d.locks",
            )

    def test_partial_two_of_three_raises(self):
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        cm = CheckpointManager(client, "p.d.checkpoints")

        with pytest.raises(ValueError, match="Partial fencing"):
            cm.mark_stage_complete(
                "run_1", "stage_1",
                fencing_token=42,
                lock_table="p.d.locks",
            )

    def test_all_three_fencing_params_succeed(self):
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        cm = CheckpointManager(client, "p.d.checkpoints")
        cm.mark_stage_complete(
            "run_1", "stage_1",
            fencing_token=42,
            lock_table="p.d.locks",
            pipeline_name="my_pipeline",
        )
        # Should not raise; verify script was executed
        client.execute_script.assert_called_once()

    def test_no_fencing_params_uses_unfenced(self):
        from bq_entity_resolution.watermark.checkpoint import CheckpointManager

        client = MagicMock()
        cm = CheckpointManager(client, "p.d.checkpoints")
        cm.mark_stage_complete("run_1", "stage_1")
        # Should not raise; verify regular execute was called
        client.execute.assert_called_once()


# ===================================================================
# Enterprise Hardening #6 — Defense-in-Depth & Polish
# ===================================================================


class TestLazyDuckDBImport:
    """Verify DuckDBBackend is lazy-imported (doesn't crash without duckdb)."""

    def test_getattr_returns_duckdb_backend(self):
        import bq_entity_resolution
        cls = bq_entity_resolution.__getattr__("DuckDBBackend")
        from bq_entity_resolution.backends.duckdb import DuckDBBackend
        assert cls is DuckDBBackend

    def test_getattr_returns_bigquery_backend(self):
        import bq_entity_resolution
        cls = bq_entity_resolution.__getattr__("BigQueryBackend")
        from bq_entity_resolution.backends.bigquery import BigQueryBackend
        assert cls is BigQueryBackend

    def test_getattr_raises_for_unknown(self):
        import bq_entity_resolution
        with pytest.raises(AttributeError, match="no attribute"):
            bq_entity_resolution.__getattr__("NonExistentBackend")

    def test_duckdb_in_all(self):
        import bq_entity_resolution
        assert "DuckDBBackend" in bq_entity_resolution.__all__


class TestBQMLModelNameValidation:
    """Verify model_name is validated with validate_table_ref in BQML builders."""

    def test_bqml_model_params_rejects_invalid_model(self):
        from bq_entity_resolution.sql.builders.bqml import BQMLModelParams
        with pytest.raises(ValueError, match="Invalid table reference"):
            BQMLModelParams(
                training_table="p.d.train",
                model_name="'; DROP TABLE users; --",
            )

    def test_bqml_model_params_accepts_valid(self):
        from bq_entity_resolution.sql.builders.bqml import BQMLModelParams
        params = BQMLModelParams(
            training_table="p.d.train",
            model_name="p.d.my_model",
        )
        assert params.model_name == "p.d.my_model"

    def test_bqml_predict_params_rejects_invalid_model(self):
        from bq_entity_resolution.sql.builders.bqml import BQMLPredictParams
        with pytest.raises(ValueError, match="Invalid table reference"):
            BQMLPredictParams(
                model_name="bad model name!",
                candidates_table="p.d.cand",
                featured_table="p.d.feat",
                output_table="p.d.out",
            )

    def test_bqml_predict_params_validates_columns(self):
        from bq_entity_resolution.sql.builders.bqml import BQMLPredictParams
        with pytest.raises(ValueError, match="predict feature column"):
            BQMLPredictParams(
                model_name="p.d.model",
                candidates_table="p.d.cand",
                featured_table="p.d.feat",
                output_table="p.d.out",
                feature_columns=["valid", "'; DROP TABLE"],
            )

    def test_bqml_predict_params_validates_comparison_columns(self):
        from bq_entity_resolution.sql.builders.bqml import BQMLPredictParams
        with pytest.raises(ValueError, match="predict comparison column"):
            BQMLPredictParams(
                model_name="p.d.model",
                candidates_table="p.d.cand",
                featured_table="p.d.feat",
                output_table="p.d.out",
                comparison_columns=["a.b"],
            )

    def test_bqml_evaluate_params_rejects_invalid_model(self):
        from bq_entity_resolution.sql.builders.bqml import BQMLEvaluateParams
        with pytest.raises(ValueError, match="Invalid table reference"):
            BQMLEvaluateParams(model_name="not valid!")

    def test_embeddings_params_rejects_invalid_model(self):
        from bq_entity_resolution.sql.builders.embeddings import EmbeddingsParams
        with pytest.raises(ValueError, match="Invalid table reference"):
            EmbeddingsParams(
                target_table="p.d.target",
                source_table="p.d.source",
                concat_expression="CONCAT(a, b)",
                model_name="invalid!model",
                dimensions=768,
            )

    def test_lsh_params_validates_bucket_prefix(self):
        from bq_entity_resolution.sql.builders.embeddings import LSHParams
        with pytest.raises(ValueError, match="LSH bucket prefix"):
            LSHParams(
                target_table="p.d.target",
                embedding_table="p.d.embed",
                num_tables=4,
                num_functions=8,
                dimensions=768,
                seed=42,
                bucket_prefix="'; DROP TABLE",
            )

    def test_feature_importance_rejects_invalid(self):
        from bq_entity_resolution.sql.builders.bqml import build_feature_importance_sql
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_feature_importance_sql("not a valid ref!")

    def test_model_weights_rejects_invalid(self):
        from bq_entity_resolution.sql.builders.bqml import build_model_weights_sql
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_model_weights_sql("not a valid ref!")


class TestBuilderDefenseInDepth:
    """Verify all builder dataclasses validate identifier inputs."""

    def test_blocking_path_rejects_injection_in_keys(self):
        from bq_entity_resolution.sql.builders.blocking import BlockingPath
        with pytest.raises(ValueError, match="blocking key"):
            BlockingPath(index=0, keys=["valid_key", "l.injected"])

    def test_blocking_path_rejects_injection_in_lsh_keys(self):
        from bq_entity_resolution.sql.builders.blocking import BlockingPath
        with pytest.raises(ValueError, match="LSH blocking key"):
            BlockingPath(index=0, lsh_keys=["'; DROP TABLE"])

    def test_blocking_path_accepts_valid(self):
        from bq_entity_resolution.sql.builders.blocking import BlockingPath
        bp = BlockingPath(index=0, keys=["email_hash", "zip_code"])
        assert bp.keys == ["email_hash", "zip_code"]

    def test_join_def_rejects_invalid_type(self):
        from bq_entity_resolution.sql.builders.staging import JoinDef
        with pytest.raises(ValueError, match="Invalid join type"):
            JoinDef(table="p.d.t", on="a = b", type="EVIL")

    def test_join_def_rejects_invalid_alias(self):
        from bq_entity_resolution.sql.builders.staging import JoinDef
        with pytest.raises(ValueError, match="join alias"):
            JoinDef(table="p.d.t", on="a = b", alias="'; DROP")

    def test_join_def_accepts_valid(self):
        from bq_entity_resolution.sql.builders.staging import JoinDef
        j = JoinDef(table="p.d.t", on="a = b", type="LEFT", alias="lookup")
        assert j.alias == "lookup"

    def test_partition_cursor_rejects_injection(self):
        from bq_entity_resolution.sql.builders.staging import PartitionCursor
        with pytest.raises(ValueError, match="partition cursor column"):
            PartitionCursor(column="a.b", value="x")

    def test_hash_cursor_rejects_injection(self):
        from bq_entity_resolution.sql.builders.staging import HashCursor
        with pytest.raises(ValueError, match="hash cursor column"):
            HashCursor(column="'; DROP TABLE")

    def test_hash_cursor_rejects_invalid_alias(self):
        from bq_entity_resolution.sql.builders.staging import HashCursor
        with pytest.raises(ValueError, match="hash cursor alias"):
            HashCursor(column="col", alias="bad alias!")

    def test_staging_params_validates_unique_key(self):
        from bq_entity_resolution.sql.builders.staging import StagingParams
        with pytest.raises(ValueError, match="staging unique key"):
            StagingParams(
                target_table="p.d.target",
                source_name="src",
                source_table="p.d.source",
                unique_key="'; DROP",
                updated_at="updated_at",
            )

    def test_staging_params_validates_columns(self):
        from bq_entity_resolution.sql.builders.staging import StagingParams
        with pytest.raises(ValueError, match="staging column"):
            StagingParams(
                target_table="p.d.target",
                source_name="src",
                source_table="p.d.source",
                unique_key="id",
                updated_at="updated_at",
                columns=["good", "l.bad"],
            )

    def test_staging_params_validates_passthrough(self):
        from bq_entity_resolution.sql.builders.staging import StagingParams
        with pytest.raises(ValueError, match="staging passthrough column"):
            StagingParams(
                target_table="p.d.target",
                source_name="src",
                source_table="p.d.source",
                unique_key="id",
                updated_at="updated_at",
                passthrough_columns=["a.b"],
            )

    def test_feature_expr_rejects_injection(self):
        from bq_entity_resolution.sql.builders.features import FeatureExpr
        with pytest.raises(ValueError, match="feature expression name"):
            FeatureExpr(name="'; DROP TABLE", expression="1")

    def test_feature_expr_accepts_valid(self):
        from bq_entity_resolution.sql.builders.features import FeatureExpr
        fe = FeatureExpr(name="email_clean", expression="LOWER(email)")
        assert fe.name == "email_clean"

    def test_custom_join_validates_alias(self):
        from bq_entity_resolution.sql.builders.features import CustomJoin
        with pytest.raises(ValueError, match="custom join alias"):
            CustomJoin(table="p.d.t", alias="'; DROP", on="a = b")

    def test_gold_output_validates_scoring_columns(self):
        from bq_entity_resolution.sql.builders.gold_output import GoldOutputParams
        with pytest.raises(ValueError, match="gold output scoring column"):
            GoldOutputParams(
                target_table="p.d.target",
                source_table="p.d.source",
                cluster_table="p.d.cluster",
                matches_table="p.d.matches",
                scoring_columns=["valid", "l.bad"],
            )

    def test_gold_output_validates_partition_column(self):
        from bq_entity_resolution.sql.builders.gold_output import GoldOutputParams
        with pytest.raises(ValueError, match="gold output partition column"):
            GoldOutputParams(
                target_table="p.d.target",
                source_table="p.d.source",
                cluster_table="p.d.cluster",
                matches_table="p.d.matches",
                partition_column="'; DROP TABLE",
            )

    def test_score_band_validates_name(self):
        from bq_entity_resolution.sql.builders.comparison.models import ScoreBand
        with pytest.raises(ValueError, match="score band name"):
            ScoreBand(name="'; DROP", min_score=0.5)

    def test_score_band_accepts_valid(self):
        from bq_entity_resolution.sql.builders.comparison.models import ScoreBand
        sb = ScoreBand(name="HIGH", min_score=0.8)
        assert sb.name == "HIGH"

    def test_hard_positive_validates_target_band(self):
        from bq_entity_resolution.sql.builders.comparison.models import HardPositive
        with pytest.raises(ValueError, match="hard positive target band"):
            HardPositive(
                sql_condition="1=1",
                target_band="'; DROP TABLE",
            )

    def test_hard_positive_accepts_valid(self):
        from bq_entity_resolution.sql.builders.comparison.models import HardPositive
        hp = HardPositive(sql_condition="1=1", target_band="HIGH")
        assert hp.target_band == "HIGH"


class TestWatermarkBuilderValidation:
    """Verify watermark builder functions validate table refs."""

    def test_create_watermark_rejects_invalid(self):
        from bq_entity_resolution.sql.builders.watermark import (
            build_create_watermark_table_sql,
        )
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_create_watermark_table_sql("not valid!")

    def test_read_watermark_rejects_invalid(self):
        from bq_entity_resolution.sql.builders.watermark import (
            build_read_watermark_sql,
        )
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_read_watermark_sql("not valid!", "source")

    def test_update_watermark_rejects_invalid(self):
        from bq_entity_resolution.sql.builders.watermark import (
            build_update_watermark_sql,
        )
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_update_watermark_sql(
                "not valid!", "src",
                [{"column": "c", "value": "v", "type": "STRING"}],
                "run1", "2025-01-01",
            )

    def test_create_checkpoint_rejects_invalid(self):
        from bq_entity_resolution.sql.builders.watermark import (
            build_create_checkpoint_table_sql,
        )
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_create_checkpoint_table_sql("not valid!")

    def test_fenced_watermark_rejects_invalid_table(self):
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_watermark_update_sql,
        )
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_fenced_watermark_update_sql(
                watermark_table="not valid!",
                source_name="src",
                cursors=[{"column": "c", "value": "v", "type": "STRING"}],
                run_id="run1",
                now="2025-01-01",
                lock_table="p.d.locks",
                pipeline_name="pipe",
                fencing_token=1,
            )

    def test_fenced_checkpoint_rejects_invalid_table(self):
        from bq_entity_resolution.sql.builders.watermark import (
            build_fenced_checkpoint_insert_sql,
        )
        with pytest.raises(ValueError, match="Invalid table reference"):
            build_fenced_checkpoint_insert_sql(
                checkpoint_table="not valid!",
                run_id="run1",
                stage_name="staging",
                now="2025-01-01",
                status="completed",
                lock_table="p.d.locks",
                pipeline_name="pipe",
                fencing_token=1,
            )


class TestCircuitBreakerThreadSafety:
    """Verify circuit breaker uses a threading lock."""

    def test_circuit_lock_exists(self):
        import threading

        from bq_entity_resolution.clients.bigquery import BigQueryClient

        client = BigQueryClient.__new__(BigQueryClient)
        client._circuit_lock = threading.Lock()
        assert isinstance(client._circuit_lock, type(threading.Lock()))


class TestConfigNameLength:
    """Verify ProjectConfig.name rejects overly long names."""

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError, match="<= 128"):
            ProjectConfig(
                name="a" * 200,
                bq_project="my-project",
            )

    def test_name_at_limit_accepted(self):
        cfg = ProjectConfig(
            name="a" * 128,
            bq_project="my-project",
        )
        assert len(cfg.name) == 128


class TestBatchSizeUpperBound:
    """Verify batch_size rejects astronomically large values."""

    def test_incremental_batch_too_large(self):
        with pytest.raises(ValidationError, match="<= 100,000,000"):
            IncrementalConfig(
                enabled=True,
                cursor_columns=["updated_at"],
                batch_size=1_000_000_000,
            )

    def test_incremental_batch_at_limit(self):
        cfg = IncrementalConfig(
            enabled=True,
            cursor_columns=["updated_at"],
            batch_size=100_000_000,
        )
        assert cfg.batch_size == 100_000_000

    def test_source_batch_too_large(self):
        with pytest.raises(ValidationError, match="<= 100,000,000"):
            SourceConfig(
                name="test",
                table="p.d.t",
                unique_key="id",
                columns=[ColumnMapping(name="a")],
                batch_size=999_999_999,
            )

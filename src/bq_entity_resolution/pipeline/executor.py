"""Pipeline executor: runs a PipelinePlan against a Backend.

Separates execution from planning. Handles:
1. Running SQL in dependency order
2. Quality gate checks after each stage
3. Checkpoint/resume via CheckpointManager
4. Metrics collection
5. Error handling with diagnostics
6. Progress callbacks
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from bq_entity_resolution.backends.protocol import Backend
from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
from bq_entity_resolution.sql.builders.job_tracking import (
    JobDetail,
    build_create_job_tracking_table_sql,
    build_insert_job_details_sql,
    compute_sql_hash,
)

logger = logging.getLogger(__name__)


# Patterns for PII redaction in SQL audit logs.
# Order matters: more specific patterns must come before generic ones
# so that e.g. TIMESTAMP('...') is replaced before the generic string
# literal pattern can consume the inner quotes.
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Timestamps (must precede generic string literal pattern)
    (re.compile(r"TIMESTAMP\('[^']*'\)"), "TIMESTAMP('<REDACTED>')"),
    # SSN: 123-45-6789 (must precede phone to avoid partial overlap)
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
    # Phone numbers: (555) 123-4567, 555-123-4567, 5551234567
    (re.compile(r"\b\d{3}[-.)]\s*\d{3}[-.]?\d{4}\b"), "<PHONE>"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    # String literals: 'value' → '<REDACTED>' (generic catch-all, last)
    (re.compile(r"'[^']*'"), "'<REDACTED>'"),
]


def _redact_sql(sql: str) -> str:
    """Redact potential PII from SQL for audit logging.

    Replaces string literals and timestamp values with <REDACTED>
    to prevent PII from appearing in logs while keeping SQL structure
    readable for debugging.
    """
    result = sql
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _is_script_block(sql: str) -> bool:
    """Detect whether SQL is a BigQuery scripting block.

    Uses line-start anchoring to avoid false positives from keywords
    appearing inside comments, string literals, or column names.
    """
    upper = sql.upper()
    return bool(
        re.search(r'^\s*DECLARE\b', upper, re.MULTILINE)
        or re.search(r'^\s*BEGIN\b', upper, re.MULTILINE)
        or re.search(r'^\s*WHILE\b', upper, re.MULTILINE)
        or re.search(r'^\s*SET\s+\w+\s*=', sql, re.IGNORECASE | re.MULTILINE)
    )


class ProgressCallback(Protocol):
    """Protocol for pipeline progress reporting."""

    def __call__(
        self,
        stage_name: str,
        stage_index: int,
        total_stages: int,
        status: str,
    ) -> None: ...


@dataclass
class StageExecutionResult:
    """Result of executing a single stage."""

    stage_name: str
    success: bool = True
    error: str | None = None
    sql_count: int = 0
    duration_seconds: float = 0.0
    rows_affected: int = 0
    skipped: bool = False
    _original_exception: Exception | None = field(default=None, repr=False)


@dataclass
class PipelineResult:
    """Result of executing a complete pipeline."""

    run_id: str
    started_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    finished_at: datetime | None = None
    status: str = "running"
    error: str | None = None
    stage_results: list[StageExecutionResult] = field(default_factory=list)
    sql_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status == "success"

    @property
    def duration_seconds(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    @property
    def completed_stages(self) -> list[str]:
        return [
            r.stage_name
            for r in self.stage_results
            if r.success and not r.skipped
        ]

    @property
    def total_sql_duration_seconds(self) -> float:
        """Sum of per-query durations across all SQL log entries."""
        return float(sum(
            entry.get("duration_seconds", 0.0)
            for entry in self.sql_log
        ))

    @property
    def total_bytes_billed(self) -> int:
        """Sum of bytes billed across all SQL log entries."""
        return sum(
            entry.get("bytes_billed", 0)
            for entry in self.sql_log
        )


class CheckpointManagerProtocol(Protocol):
    """Protocol for checkpoint persistence (avoids circular import)."""

    def ensure_table_exists(self) -> None: ...
    def load_completed_stages(self, run_id: str) -> set[str]: ...
    def find_resumable_run(self) -> str | None: ...
    def mark_stage_complete(
        self, run_id: str, stage_name: str, **kwargs: Any
    ) -> None: ...
    def mark_run_complete(self, run_id: str, **kwargs: Any) -> None: ...


class PipelineExecutor:
    """Executes a PipelinePlan against a Backend.

    Handles the plan/execute split: all SQL is pre-generated,
    and the executor runs it in order with error handling,
    quality gates, checkpoint persistence, and metrics collection.

    Production features:
    - Pipeline-level cost ceiling (abort if cumulative bytes exceed limit)
    - Health probe updates on each stage completion
    - Retry strategy delegated to backend (BigQueryClient handles retries)

    Retry strategy: The executor does NOT implement its own retry logic
    for transient errors (503 ServiceUnavailable, 429 TooManyRequests,
    500 InternalServerError). Retries are the responsibility of the
    backend implementation. The BigQueryClient in clients/bigquery.py
    provides exponential-backoff retries with jitter. DuckDB operations
    are local and do not need network retries.
    """

    def __init__(
        self,
        backend: Backend,
        quality_gates: list[Any] | None = None,
        checkpoint_manager: CheckpointManagerProtocol | None = None,
        on_progress: ProgressCallback | None = None,
        max_cost_bytes: int | None = None,
        health_probe: Any | None = None,
        fencing_kwargs: dict[str, Any] | None = None,
        redact_sql_logs: bool = True,
        job_tracking_table: str | None = None,
        job_tracking_enabled: bool = False,
        cost_alert_threshold_bytes: int | None = None,
        cost_abort_threshold_bytes: int | None = None,
    ):
        self.backend = backend
        self.quality_gates = quality_gates or []
        self._checkpoint = checkpoint_manager
        self._on_progress = on_progress
        self._max_cost_bytes = max_cost_bytes
        self._health_probe = health_probe
        self._fencing_kwargs = fencing_kwargs or {}
        # PII redaction is always enabled for SQL audit log entries.
        # The parameter is kept for backward-compatible signatures but
        # has no effect: _redact_sql() is applied unconditionally.
        self._redact_sql_logs = redact_sql_logs
        self._checkpoint_failures = 0
        self._job_tracking_table = job_tracking_table
        self._job_tracking_enabled = job_tracking_enabled
        self._job_details: list[JobDetail] = []
        # Per-run cumulative cost budget guards
        self._cost_alert_threshold = cost_alert_threshold_bytes
        self._cost_abort_threshold = cost_abort_threshold_bytes
        self._cumulative_bytes_billed: int = 0
        self._cost_alert_fired: bool = False

    def execute(
        self,
        plan: PipelinePlan,
        run_id: str | None = None,
        skip_stages: set[str] | None = None,
        resume: bool = False,
    ) -> PipelineResult:
        """Execute a pipeline plan.

        Args:
            plan: The immutable pipeline plan to execute.
            run_id: Optional run identifier. Auto-generated if not provided.
            skip_stages: Stage names to skip (for checkpoint/resume).
            resume: If True and checkpoint_manager is set, auto-detect
                resumable run and skip completed stages.
        """
        skip_stages = set(skip_stages) if skip_stages else set()

        # Auto-resume from checkpoint if requested
        if resume and self._checkpoint:
            try:
                self._checkpoint.ensure_table_exists()
                resumable_run_id = self._checkpoint.find_resumable_run()
                if resumable_run_id:
                    completed = self._checkpoint.load_completed_stages(
                        resumable_run_id
                    )
                    skip_stages |= completed
                    run_id = resumable_run_id
                    logger.info(
                        "Resuming run '%s' — skipping %d completed stages: %s",
                        run_id, len(completed), sorted(completed),
                    )
            except Exception:
                logger.warning(
                    "Failed to load checkpoint state; starting fresh",
                    exc_info=True,
                )

        run_id = run_id or self._generate_run_id()
        result = PipelineResult(run_id=run_id)
        total_stages = len(plan.stages)
        logger.info("Pipeline execution started: %s (%d stages)", run_id, total_stages)

        try:
            for idx, stage_plan in enumerate(plan.stages):
                if stage_plan.stage_name in skip_stages:
                    result.stage_results.append(StageExecutionResult(
                        stage_name=stage_plan.stage_name,
                        skipped=True,
                    ))
                    logger.info(
                        "Skipping stage '%s' (checkpoint resume)",
                        stage_plan.stage_name,
                    )
                    self._notify_progress(
                        stage_plan.stage_name, idx, total_stages, "skipped"
                    )
                    continue

                self._notify_progress(
                    stage_plan.stage_name, idx, total_stages, "running"
                )
                stage_result = self._execute_stage(stage_plan, result)
                result.stage_results.append(stage_result)

                if not stage_result.success:
                    fail_detail = (
                        f"failed after {stage_result.duration_seconds:.1f}s"
                        f": {stage_result.error}"
                    )
                    self._notify_progress(
                        stage_plan.stage_name, idx, total_stages, fail_detail
                    )
                    original = getattr(stage_result, "_original_exception", None)
                    raise RuntimeError(
                        f"Stage '{stage_plan.stage_name}' failed: "
                        f"{stage_result.error}"
                    ) from original

                # Check pipeline-level cost ceiling (per-query)
                if self._max_cost_bytes and hasattr(self.backend, "check_cost_ceiling"):
                    self.backend.check_cost_ceiling(self._max_cost_bytes)

                # Per-run cumulative cost budget guards
                if (
                    self._cost_abort_threshold
                    and self._cumulative_bytes_billed > self._cost_abort_threshold
                ):
                    from bq_entity_resolution.exceptions import (
                        PipelineCostExceededError,
                    )
                    raise PipelineCostExceededError(
                        f"Pipeline cumulative bytes_billed "
                        f"({self._cumulative_bytes_billed:,}) exceeds abort "
                        f"threshold ({self._cost_abort_threshold:,})"
                    )
                if (
                    self._cost_alert_threshold
                    and not self._cost_alert_fired
                    and self._cumulative_bytes_billed > self._cost_alert_threshold
                ):
                    self._cost_alert_fired = True
                    logger.warning(
                        "Cost alert: cumulative bytes_billed %d exceeds "
                        "threshold %d",
                        self._cumulative_bytes_billed,
                        self._cost_alert_threshold,
                    )

                # Run quality gates BEFORE checkpoint (so failed gates
                # are not persisted as completed on resume)
                self._check_gates(stage_plan, result)

                # Update health probe after stage success
                if self._health_probe:
                    try:
                        self._health_probe.mark_healthy(
                            stage=stage_plan.stage_name,
                            run_id=run_id,
                        )
                    except Exception:
                        logger.warning(
                            "Health probe update failed for stage '%s'",
                            stage_plan.stage_name, exc_info=True,
                        )

                # Persist checkpoint after successful stage + gates
                if self._checkpoint:
                    try:
                        self._checkpoint.mark_stage_complete(
                            run_id, stage_plan.stage_name,
                            **self._fencing_kwargs,
                        )
                        self._checkpoint_failures = 0  # Reset on success
                    except Exception:
                        self._checkpoint_failures += 1
                        logger.error(
                            "Failed to persist checkpoint for stage '%s' in run '%s' "
                            "(consecutive failures: %d). "
                            "Stage completed successfully but checkpoint was NOT saved — "
                            "this stage may re-execute on resume.",
                            stage_plan.stage_name,
                            run_id,
                            self._checkpoint_failures,
                            exc_info=True,
                        )
                        if self._checkpoint_failures >= 3:
                            raise RuntimeError(
                                f"Aborting: {self._checkpoint_failures} consecutive "
                                f"checkpoint write failures. The checkpoint backend "
                                f"may be unavailable."
                            )

                self._notify_progress(
                    stage_plan.stage_name, idx, total_stages, "completed"
                )

            result.status = "success"

            # Persist job tracking details
            self._persist_job_details(run_id)

            # Mark entire run as complete in checkpoint
            if self._checkpoint:
                try:
                    self._checkpoint.mark_run_complete(
                        run_id, **self._fencing_kwargs
                    )
                except Exception:
                    logger.error(
                        "Failed to mark run '%s' as complete in checkpoint. "
                        "Pipeline finished successfully but may appear incomplete on resume.",
                        run_id,
                        exc_info=True,
                    )

            logger.info(
                "Pipeline completed: %s (%.1fs, %d queries, "
                "sql_time=%.1fs, bytes_billed=%d)",
                run_id,
                result.duration_seconds,
                len(result.sql_log),
                result.total_sql_duration_seconds,
                result.total_bytes_billed,
            )

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.exception("Pipeline failed: %s", run_id)
            raise

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    def _execute_stage(
        self,
        stage_plan: StagePlan,
        pipeline_result: PipelineResult,
    ) -> StageExecutionResult:
        """Execute a single stage's SQL statements."""
        stage_result = StageExecutionResult(
            stage_name=stage_plan.stage_name,
            sql_count=stage_plan.sql_count,
        )

        if stage_plan.sql_count == 0:
            logger.info(
                "Stage '%s': no SQL to execute", stage_plan.stage_name
            )
            return stage_result

        start = time.monotonic()
        logger.info(
            "Executing stage '%s' (%d SQL statement(s))",
            stage_plan.stage_name,
            stage_plan.sql_count,
        )

        try:
            for expr in stage_plan.sql_expressions:
                sql = expr.render()

                # Always redact PII in SQL audit log entries to prevent
                # sensitive data from leaking into persisted logs.
                logged_sql = _redact_sql(sql)
                log_entry: dict[str, Any] = {
                    "stage": stage_plan.stage_name,
                    "sql": logged_sql,
                    "timestamp": datetime.now(UTC).isoformat(),
                }

                # Track per-query execution time
                query_start = time.monotonic()

                # Use execute_script for BQ scripting blocks
                if _is_script_block(sql):
                    query_result = self.backend.execute_script(
                        sql, label=stage_plan.stage_name
                    )
                else:
                    query_result = self.backend.execute(
                        sql, label=stage_plan.stage_name
                    )

                query_duration = time.monotonic() - query_start
                log_entry["duration_seconds"] = round(query_duration, 4)
                log_entry["bytes_billed"] = query_result.bytes_billed

                pipeline_result.sql_log.append(log_entry)

                # Collect job detail for job tracking persistence
                if self._job_tracking_enabled:
                    self._job_details.append(JobDetail(
                        stage_name=stage_plan.stage_name,
                        query_index=len(self._job_details),
                        job_id=getattr(query_result, "job_id", "") or "",
                        bytes_billed=query_result.bytes_billed,
                        total_bytes_processed=getattr(
                            query_result, "total_bytes_processed", 0
                        ),
                        slot_milliseconds=getattr(
                            query_result, "slot_milliseconds", 0
                        ),
                        duration_seconds=round(query_duration, 4),
                        rows_affected=query_result.rows_affected,
                        started_at=log_entry["timestamp"],
                        sql_hash=compute_sql_hash(sql),
                    ))

                stage_result.rows_affected += query_result.rows_affected

                # Accumulate per-run cost for budget guards
                self._cumulative_bytes_billed += query_result.bytes_billed

                # Per-SQL health probe heartbeat so K8s doesn't
                # think a long-running stage is hung
                if self._health_probe:
                    try:
                        self._health_probe.mark_healthy(
                            stage=stage_plan.stage_name,
                            run_id=getattr(pipeline_result, "run_id", ""),
                        )
                    except Exception:
                        logger.warning(
                            "Health probe update failed for stage '%s'",
                            stage_plan.stage_name, exc_info=True,
                        )

        except Exception as e:
            stage_result.success = False
            stage_result.error = _redact_sql(str(e))
            stage_result._original_exception = e  # Preserve for chaining
            logger.error(
                "Stage '%s' failed: %s",
                stage_plan.stage_name,
                stage_result.error,
            )

        finally:
            stage_result.duration_seconds = time.monotonic() - start

        return stage_result

    def _check_gates(
        self,
        stage_plan: StagePlan,
        pipeline_result: PipelineResult,
    ) -> None:
        """Run quality gates for a completed stage."""
        for gate in self.quality_gates:
            if gate.applies_to(stage_plan.stage_name):
                gate_result = gate.check(
                    stage_name=stage_plan.stage_name,
                    backend=self.backend,
                    outputs=stage_plan.outputs,
                )
                if not gate_result.passed:
                    if gate_result.severity == "error":
                        raise RuntimeError(
                            f"Quality gate failed for "
                            f"'{stage_plan.stage_name}': "
                            f"{gate_result.message}"
                        )
                    else:
                        logger.warning(
                            "Quality gate warning for '%s': %s",
                            stage_plan.stage_name,
                            gate_result.message,
                        )

    def _notify_progress(
        self,
        stage_name: str,
        stage_index: int,
        total_stages: int,
        status: str,
    ) -> None:
        """Send progress notification if a callback is registered."""
        if self._on_progress:
            try:
                self._on_progress(stage_name, stage_index, total_stages, status)
            except Exception:
                logger.warning(
                    "Progress callback failed for stage '%s'",
                    stage_name, exc_info=True,
                )

    def _persist_job_details(self, run_id: str) -> None:
        """Persist collected job details to tracking table.

        Wrapped in try/except so tracking failure doesn't crash the pipeline.
        """
        if not self._job_tracking_enabled or not self._job_details:
            return
        if not self._job_tracking_table:
            logger.warning(
                "Job tracking enabled but no table configured — skipping"
            )
            return

        try:
            # Create table if not exists
            create_sql = build_create_job_tracking_table_sql(
                self._job_tracking_table
            )
            self.backend.execute(
                create_sql.render(), label="job_tracking_create"
            )

            # Insert all collected details
            insert_sql = build_insert_job_details_sql(
                self._job_tracking_table, run_id, self._job_details
            )
            self.backend.execute(
                insert_sql.render(), label="job_tracking_insert"
            )

            logger.info(
                "Persisted %d job details to %s",
                len(self._job_details),
                self._job_tracking_table,
            )
        except Exception:
            logger.warning(
                "Failed to persist job tracking details — pipeline "
                "completed successfully but job metadata was not saved",
                exc_info=True,
            )

    @staticmethod
    def _generate_run_id() -> str:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"er_run_{ts}"

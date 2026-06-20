"""
BigQuery client wrapper with retry logic, structured logging, and dry-run support.

Production features:
- Automatic retries with jitter for transient errors
- Job tracking for graceful shutdown (SIGTERM cancellation)
- Cumulative cost tracking with pipeline-level ceiling
- Job cancellation on timeout (prevents orphaned BQ jobs)
- Cost controls (max_bytes_billed) on all query methods
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any

from google.api_core.exceptions import (
    BadRequest,
    InternalServerError,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud import bigquery

from bq_entity_resolution.exceptions import PipelineAbortError, SQLExecutionError

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (ServiceUnavailable, InternalServerError, TooManyRequests)
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


@dataclass
class QueryResult:
    """Result metadata from a BigQuery query execution."""

    job_id: str = ""
    total_bytes_processed: int = 0
    rows_affected: int = 0
    bytes_billed: int = 0
    duration_seconds: float = 0.0
    slot_milliseconds: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)


class BigQueryClient:
    """
    Wrapper around google.cloud.bigquery.Client.

    Features:
    - Automatic retries with jitter for transient errors
    - Job labeling for cost tracking
    - Structured logging of query metrics
    - Dry-run support for cost estimation
    - Job tracking for graceful shutdown (SIGTERM cancellation)
    - Cumulative cost tracking with pipeline-level cost ceiling
    - Job cancellation on timeout (prevents orphaned BQ jobs)
    """

    def __init__(
        self,
        project: str,
        location: str = "US",
        dry_run: bool = False,
        max_bytes_billed: int | None = None,
        default_timeout: int = 600,
    ):
        self.project = project
        self.location = location
        self.dry_run = dry_run
        self.max_bytes_billed = max_bytes_billed
        self.default_timeout = default_timeout
        self._client = bigquery.Client(project=project, location=location)
        self._active_jobs: list[bigquery.QueryJob] = []
        self._jobs_lock = threading.Lock()
        self._cost_lock = threading.Lock()
        self._total_bytes_billed: int = 0
        # Circuit breaker: track consecutive non-retryable failures
        self._circuit_lock = threading.Lock()
        self._circuit_failure_count: int = 0
        self._circuit_last_failure: float = 0.0
        self._circuit_failure_threshold: int = 5
        self._circuit_window_seconds: float = 60.0

    @property
    def total_bytes_billed(self) -> int:
        """Cumulative bytes billed across all queries in this client's lifetime."""
        with self._cost_lock:
            return self._total_bytes_billed

    def check_cost_ceiling(self, ceiling: int | None) -> None:
        """Raise PipelineAbortError if cumulative bytes billed exceeds ceiling."""
        with self._cost_lock:
            current = self._total_bytes_billed
        if ceiling is not None and current > ceiling:
            raise PipelineAbortError(
                f"Pipeline cost ceiling exceeded: {current:,} bytes "
                f"billed > {ceiling:,} byte ceiling. Aborting to prevent runaway costs."
            )

    def _record_circuit_success(self) -> None:
        """Reset circuit breaker on successful query."""
        with self._circuit_lock:
            self._circuit_failure_count = 0

    def _record_circuit_failure(self) -> None:
        """Record a non-retryable failure and trip breaker if threshold exceeded."""
        with self._circuit_lock:
            now = time.monotonic()
            if now - self._circuit_last_failure > self._circuit_window_seconds:
                self._circuit_failure_count = 0
            self._circuit_failure_count += 1
            self._circuit_last_failure = now
            if self._circuit_failure_count >= self._circuit_failure_threshold:
                raise PipelineAbortError(
                    f"Circuit breaker open: {self._circuit_failure_count} consecutive "
                    f"non-retryable failures within {self._circuit_window_seconds}s. "
                    f"BigQuery backend may be unavailable or misconfigured."
                )

    def cancel_active_jobs(self) -> int:
        """Cancel all in-flight BigQuery jobs. Returns count of cancelled jobs.

        Called by graceful shutdown handlers (SIGTERM) to prevent orphaned
        BigQuery jobs from consuming slots after the Python process exits.
        """
        cancelled = 0
        with self._jobs_lock:
            for job in self._active_jobs:
                try:
                    job.cancel()
                    cancelled += 1
                    logger.info("Cancelled BigQuery job: %s", job.job_id)
                except Exception:
                    logger.warning(
                        "Failed to cancel job %s", job.job_id, exc_info=True
                    )
            self._active_jobs.clear()
        return cancelled

    def close(self) -> None:
        """Cancel active jobs and close the underlying client."""
        self.cancel_active_jobs()
        if hasattr(self._client, "close"):
            self._client.close()  # type: ignore[no-untyped-call]

    def __enter__(self) -> BigQueryClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _track_job(self, job: bigquery.QueryJob) -> None:
        """Register a job for SIGTERM cancellation tracking."""
        with self._jobs_lock:
            self._active_jobs.append(job)

    def _untrack_job(self, job: bigquery.QueryJob) -> None:
        """Remove a completed job from tracking."""
        with self._jobs_lock:
            try:
                self._active_jobs.remove(job)
            except ValueError:
                pass  # Job already removed from list (e.g. concurrent untrack call)

    def _make_job_config(
        self, job_label: str, dry_run: bool = False,
    ) -> bigquery.QueryJobConfig:
        """Create a job config with cost controls applied."""
        config = bigquery.QueryJobConfig(
            labels={"pipeline_step": job_label[:63]} if job_label else {},
            dry_run=dry_run,
        )
        if self.max_bytes_billed is not None:
            config.maximum_bytes_billed = self.max_bytes_billed
        return config

    def _retry_execute(
        self,
        fn: Callable[[], Any],
        sql: str,
        job_label: str,
        context: str = "Query",
    ) -> Any:
        """Execute fn with retry + jitter for transient errors.

        Args:
            fn: Callable that receives no arguments and returns a result.
            sql: The SQL to execute (for error messages).
            job_label: BQ job label.
            context: Description for error messages (e.g. "Query", "Fetch", "Script").
        """
        attempt = 0
        while attempt <= MAX_RETRIES:
            try:
                result = fn()
                self._record_circuit_success()
                return result
            except RETRYABLE_ERRORS as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    self._record_circuit_failure()
                    raise SQLExecutionError(
                        f"{context} failed after {MAX_RETRIES} retries: {e}",
                        sql=sql,
                    ) from e
                base_wait = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                jitter = base_wait * random.random() * 0.5
                wait = base_wait + jitter
                logger.warning(
                    "Retryable error (attempt %d/%d), waiting %.1fs: %s",
                    attempt, MAX_RETRIES, wait, e,
                )
                time.sleep(wait)
            except BadRequest as e:
                from bq_entity_resolution.pipeline.executor import _redact_sql

                logger.error("SQL error in %s %s: %s", context.lower(), job_label, e)
                logger.error("SQL:\n%s", _redact_sql(sql))
                self._record_circuit_failure()
                raise SQLExecutionError(
                    f"SQL syntax/semantic error: {e}", sql=sql,
                ) from e

        raise SQLExecutionError(f"{context} failed: exceeded retry logic", sql=sql)

    def execute(
        self,
        sql: str,
        job_label: str = "",
        timeout: int | None = None,
    ) -> QueryResult:
        """Execute a SQL statement and return result metadata."""
        effective_timeout = timeout or self.default_timeout
        job_config = self._make_job_config(job_label, dry_run=self.dry_run)

        start = time.monotonic()

        def _do() -> QueryResult:
            logger.debug("Executing SQL (label=%s): %.200s...", job_label, sql)
            job = self._client.query(sql, job_config=job_config)

            if self.dry_run:
                return QueryResult(
                    job_id="dry_run",
                    total_bytes_processed=job.total_bytes_processed or 0,
                )

            self._track_job(job)
            try:
                result = job.result(timeout=effective_timeout)
            except FuturesTimeoutError:
                logger.error(
                    "Query timed out after %ds, cancelling job %s",
                    effective_timeout, job.job_id,
                )
                job.cancel()
                self._untrack_job(job)
                raise SQLExecutionError(
                    f"Query timed out after {effective_timeout}s "
                    f"(job {job.job_id} cancelled)",
                    sql=sql, job_id=job.job_id,
                )
            finally:
                self._untrack_job(job)

            duration = time.monotonic() - start
            bytes_billed = job.total_bytes_billed or 0
            with self._cost_lock:
                self._total_bytes_billed += bytes_billed

            qr = QueryResult(
                job_id=job.job_id,
                total_bytes_processed=job.total_bytes_processed or 0,
                rows_affected=result.total_rows if result else 0,
                bytes_billed=bytes_billed,
                duration_seconds=duration,
                slot_milliseconds=getattr(job, "slot_millis", 0) or 0,
            )

            logger.info(
                "Query complete: job=%s duration=%.1fs bytes_billed=%d label=%s",
                job.job_id, duration, qr.bytes_billed, job_label,
            )
            return qr

        result: QueryResult = self._retry_execute(_do, sql, job_label, context="Query")
        return result

    def execute_and_fetch(
        self,
        sql: str,
        job_label: str = "",
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        """Execute SQL and return rows as list of dicts.

        Includes retry logic with jitter, cost controls, and job
        cancellation on timeout.
        """
        effective_timeout = timeout or self.default_timeout
        job_config = self._make_job_config(job_label)

        def _do() -> list[dict[str, Any]]:
            job = self._client.query(sql, job_config=job_config)
            self._track_job(job)
            try:
                result = job.result(timeout=effective_timeout)
                rows = [dict(row) for row in result]
            except FuturesTimeoutError:
                logger.error(
                    "Fetch query timed out after %ds, cancelling job %s",
                    effective_timeout, job.job_id,
                )
                job.cancel()
                raise SQLExecutionError(
                    f"Fetch query timed out after {effective_timeout}s "
                    f"(job {job.job_id} cancelled)",
                    sql=sql, job_id=job.job_id,
                )
            finally:
                self._untrack_job(job)

            bytes_billed = job.total_bytes_billed or 0
            with self._cost_lock:
                self._total_bytes_billed += bytes_billed
            return rows

        rows: list[dict[str, Any]] = self._retry_execute(_do, sql, job_label, context="Fetch")
        return rows

    def execute_script_and_fetch(
        self,
        sql: str,
        job_label: str = "",
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a multi-statement SQL script and return the final result set.

        Includes retry logic with jitter, cost controls, and job
        cancellation on timeout.
        """
        effective_timeout = timeout or self.default_timeout
        job_config = self._make_job_config(job_label)

        def _do() -> list[dict[str, Any]]:
            logger.debug(
                "Executing script+fetch (label=%s): %.200s...", job_label, sql
            )
            job = self._client.query(sql, job_config=job_config)
            self._track_job(job)
            try:
                rows = [dict(row) for row in job.result(timeout=effective_timeout)]
            except FuturesTimeoutError:
                logger.error(
                    "Script timed out after %ds, cancelling job %s",
                    effective_timeout, job.job_id,
                )
                job.cancel()
                raise SQLExecutionError(
                    f"Script query timed out after {effective_timeout}s "
                    f"(job {job.job_id} cancelled)",
                    sql=sql, job_id=job.job_id,
                )
            finally:
                self._untrack_job(job)

            bytes_billed = job.total_bytes_billed or 0
            with self._cost_lock:
                self._total_bytes_billed += bytes_billed
            logger.info(
                "Script+fetch complete: job=%s rows=%d label=%s",
                job.job_id, len(rows), job_label,
            )
            return rows

        rows: list[dict[str, Any]] = self._retry_execute(_do, sql, job_label, context="Script")
        return rows

    def table_exists(self, table_ref: str) -> bool:
        """Check if a table exists.

        Only catches NotFound --- permission errors and network errors
        propagate so callers can handle them explicitly.
        """
        try:
            self._client.get_table(table_ref)
            return True
        except NotFound:
            return False

"""Distributed locking for concurrent pipeline safety.

Uses a BigQuery metadata table as a distributed lock to prevent
multiple K8s pods from running the same pipeline simultaneously.

Lock acquisition uses an atomic MERGE statement to eliminate
time-of-check-to-time-of-use (TOCTOU) race conditions. A fencing
token (monotonic integer) is assigned on acquisition and can be
verified before critical writes (e.g. watermark advancement).

Lock table schema::

    CREATE TABLE IF NOT EXISTS {lock_table} (
      pipeline_name STRING,
      lock_holder STRING,
      acquired_at TIMESTAMP,
      expires_at TIMESTAMP,
      heartbeat_at TIMESTAMP,
      fencing_token INT64
    )
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any
from uuid import uuid4

from bq_entity_resolution.exceptions import PipelineAbortError
from bq_entity_resolution.sql.utils import validate_safe_value

logger = logging.getLogger(__name__)


class PipelineLock:
    """Distributed lock backed by a BigQuery table.

    Prevents concurrent pipeline runs on the same config. Uses
    TTL-based expiry so locks are released even if the holder crashes.

    Lock acquisition is atomic via BigQuery MERGE — no TOCTOU race.
    A fencing token is assigned on acquisition and can be used to
    guard downstream writes (e.g. watermark advancement).

    Usage::

        lock = PipelineLock(bq_client, "project.dataset.pipeline_locks")
        lock.acquire("my_pipeline")
        try:
            # run pipeline, use lock.fencing_token for fenced writes
            ...
        finally:
            lock.release("my_pipeline")
    """

    def __init__(
        self,
        bq_client: Any,
        lock_table: str,
        ttl_minutes: int = 30,
        retry_seconds: int = 10,
        max_wait_seconds: int = 300,
    ):
        self._client = bq_client
        self._lock_table = lock_table
        self._ttl_minutes = ttl_minutes
        self._retry_seconds = retry_seconds
        self._max_wait_seconds = max_wait_seconds
        self._holder_id = f"{os.getpid()}_{uuid4().hex[:8]}"
        self._fencing_token: int | None = None

    @property
    def holder_id(self) -> str:
        return self._holder_id

    @property
    def fencing_token(self) -> int | None:
        """The fencing token for this lock holder, or None if not acquired."""
        return self._fencing_token

    def ensure_table_exists(self) -> None:
        """Create the lock table if it does not exist."""
        ddl = (
            f"CREATE TABLE IF NOT EXISTS `{self._lock_table}` (\n"
            f"  pipeline_name STRING,\n"
            f"  lock_holder STRING,\n"
            f"  acquired_at TIMESTAMP,\n"
            f"  expires_at TIMESTAMP,\n"
            f"  heartbeat_at TIMESTAMP,\n"
            f"  fencing_token INT64\n"
            f")"
        )
        self._client.execute(ddl, job_label="ensure_lock_table")
        # Migrate existing tables that lack fencing_token column
        alter_sql = (
            f"ALTER TABLE `{self._lock_table}` "
            f"ADD COLUMN IF NOT EXISTS fencing_token INT64"
        )
        try:
            self._client.execute(alter_sql, job_label="migrate_lock_table")
        except Exception as exc:
            # BadRequest indicates "column already exists" — safe to ignore.
            # Import inline to avoid hard dependency on google-cloud-bigquery.
            try:
                from google.api_core.exceptions import BadRequest
            except ImportError:
                BadRequest = None  # type: ignore[assignment,misc]  # noqa: N806
            if BadRequest is not None and isinstance(exc, BadRequest):
                pass  # Column already exists or table was just created with it
            else:
                logger.warning(
                    "Unexpected error during lock table migration: %s",
                    exc, exc_info=True,
                )

    def acquire(self, pipeline_name: str) -> bool:
        """Attempt to acquire the lock. Blocks up to max_wait_seconds.

        Uses an atomic MERGE statement to eliminate TOCTOU races:
        - No existing row → INSERT new lock
        - Expired row → UPDATE (take over)
        - Active row by another holder → no-op (retry)

        After MERGE, a verification SELECT confirms ownership.

        Returns True if acquired, raises PipelineAbortError if timed out.
        """
        self.ensure_table_exists()
        deadline = time.monotonic() + self._max_wait_seconds
        safe_name = validate_safe_value(pipeline_name, "pipeline_name")
        safe_holder = validate_safe_value(self._holder_id, "holder_id")

        while True:
            # Use BigQuery's CURRENT_TIMESTAMP() for all time comparisons
            # to avoid clock skew between the Python process and BQ server.
            ttl = self._ttl_minutes

            merge_sql = (
                f"MERGE `{self._lock_table}` AS T "
                f"USING (SELECT '{safe_name}' AS pipeline_name) AS S "
                f"ON T.pipeline_name = S.pipeline_name "
                f"WHEN MATCHED AND T.expires_at < CURRENT_TIMESTAMP() THEN "
                f"  UPDATE SET "
                f"    lock_holder = '{safe_holder}', "
                f"    acquired_at = CURRENT_TIMESTAMP(), "
                f"    expires_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {ttl} MINUTE), "
                f"    heartbeat_at = CURRENT_TIMESTAMP(), "
                f"    fencing_token = COALESCE(T.fencing_token, 0) + 1 "
                f"WHEN NOT MATCHED THEN "
                f"  INSERT (pipeline_name, lock_holder, acquired_at, "
                f"expires_at, heartbeat_at, fencing_token) "
                f"  VALUES ("
                f"    '{safe_name}', "
                f"    '{safe_holder}', "
                f"    CURRENT_TIMESTAMP(), "
                f"    TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {ttl} MINUTE), "
                f"    CURRENT_TIMESTAMP(), "
                f"    1"
                f"  )"
            )

            try:
                self._client.execute(merge_sql, job_label="acquire_lock")
            except Exception:
                logger.warning(
                    "Lock MERGE failed for '%s'; will verify ownership",
                    pipeline_name, exc_info=True,
                )

            # Verify we hold the lock (read-after-write consistency)
            verify_sql = (
                f"SELECT lock_holder, fencing_token "
                f"FROM `{self._lock_table}` "
                f"WHERE pipeline_name = '{safe_name}' "
                f"LIMIT 1"
            )
            rows = self._client.execute_and_fetch(
                verify_sql, job_label="verify_lock"
            )

            if rows and rows[0]["lock_holder"] == self._holder_id:
                self._fencing_token = rows[0].get("fencing_token")
                logger.info(
                    "Lock acquired for '%s' by %s (fencing_token=%s, ttl=%dm)",
                    pipeline_name,
                    self._holder_id,
                    self._fencing_token,
                    self._ttl_minutes,
                )
                return True

            if time.monotonic() >= deadline:
                holder = rows[0]["lock_holder"] if rows else "unknown"
                raise PipelineAbortError(
                    f"Could not acquire lock for '{pipeline_name}' after "
                    f"{self._max_wait_seconds}s. Currently held by: {holder}"
                )

            current_holder = rows[0]["lock_holder"] if rows else "unknown"
            logger.info(
                "Lock for '%s' held by %s, retrying in %ds",
                pipeline_name,
                current_holder,
                self._retry_seconds,
            )
            jitter = random.uniform(0, self._retry_seconds * 0.5)
            time.sleep(self._retry_seconds + jitter)

    def release(self, pipeline_name: str) -> None:
        """Release the lock held by this instance."""
        safe_name = validate_safe_value(pipeline_name, "pipeline_name")
        safe_holder = validate_safe_value(self._holder_id, "holder_id")
        delete_sql = (
            f"DELETE FROM `{self._lock_table}` "
            f"WHERE pipeline_name = '{safe_name}' "
            f"AND lock_holder = '{safe_holder}'"
        )
        try:
            self._client.execute(delete_sql, job_label="release_lock")
            logger.info("Lock released for '%s'", pipeline_name)
            self._fencing_token = None
        except Exception:
            logger.warning(
                "Failed to release lock for '%s'. "
                "Fencing token preserved for potential retry.",
                pipeline_name, exc_info=True,
            )

    def refresh(self, pipeline_name: str) -> None:
        """Extend the lock TTL (heartbeat).

        Uses CURRENT_TIMESTAMP() to avoid clock skew between Python
        and BigQuery. Includes fencing_token in WHERE clause to
        ensure we still hold the lock.
        """
        ttl = self._ttl_minutes
        safe_name = validate_safe_value(pipeline_name, "pipeline_name")
        safe_holder = validate_safe_value(self._holder_id, "holder_id")
        where_parts = (
            f"WHERE pipeline_name = '{safe_name}' "
            f"AND lock_holder = '{safe_holder}'"
        )
        if self._fencing_token is not None:
            where_parts += f" AND fencing_token = {self._fencing_token}"

        update_sql = (
            f"UPDATE `{self._lock_table}` "
            f"SET expires_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {ttl} MINUTE), "
            f"heartbeat_at = CURRENT_TIMESTAMP() "
            f"{where_parts}"
        )
        try:
            result = self._client.execute(update_sql, job_label="refresh_lock")
            # Check if the UPDATE actually matched our lock row
            rows_affected = getattr(result, "rows_affected", None)
            if rows_affected is not None and rows_affected == 0:
                raise RuntimeError(
                    f"Lock refresh for '{pipeline_name}' matched 0 rows. "
                    f"Lock may have been stolen by another process."
                )
            logger.debug("Lock refreshed for '%s'", pipeline_name)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to refresh lock for '{pipeline_name}'. "
                f"Lock may expire and allow concurrent execution."
            ) from exc

    def verify_lock(self, pipeline_name: str) -> bool:
        """Verify this instance still holds the lock."""
        safe_name = validate_safe_value(pipeline_name, "pipeline_name")
        safe_holder = validate_safe_value(self._holder_id, "holder_id")
        check_sql = (
            f"SELECT lock_holder "
            f"FROM `{self._lock_table}` "
            f"WHERE pipeline_name = '{safe_name}' "
            f"AND lock_holder = '{safe_holder}' "
            f"LIMIT 1"
        )
        try:
            rows = self._client.execute_and_fetch(
                check_sql, job_label="verify_lock"
            )
            return bool(rows)
        except Exception:
            logger.warning("Failed to verify lock", exc_info=True)
            return False

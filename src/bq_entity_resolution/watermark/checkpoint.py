"""
Checkpoint manager for crash-resilient pipeline execution.

Persists completed stage state to a BigQuery metadata table so that
a pipeline crash mid-run can resume from the last completed stage
instead of re-running everything from scratch.

Safety notes:
- All user-supplied values (run_id, stage_name) are validated against
  a strict allowlist of safe characters before being used in SQL.
- Stages use CREATE OR REPLACE TABLE, making re-execution idempotent.
  If a checkpoint write fails, the worst case is wasted compute on
  resume (the stage re-runs and overwrites its own output).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from bq_entity_resolution.sql.builders.watermark import (
    build_create_checkpoint_table_sql,
    build_fenced_checkpoint_insert_sql,
)
from bq_entity_resolution.sql.utils import validate_safe_value

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages pipeline checkpoint state in a BigQuery metadata table.

    Checkpoint writes are best-effort: if a write fails, the error is
    logged but does not crash the pipeline. This is safe because all
    pipeline stages use CREATE OR REPLACE TABLE, making re-execution
    idempotent — the worst case on resume is repeated work, not
    duplicate data.
    """

    def __init__(
        self,
        bq_client: Any,
        checkpoint_table: str,
    ):
        self._client = bq_client
        self._table = checkpoint_table

    def ensure_table_exists(self) -> None:
        """Create the checkpoint table if it doesn't exist."""
        expr = build_create_checkpoint_table_sql(self._table)
        self._client.execute(expr.render(), job_label="ensure_checkpoint_table")

    def load_completed_stages(self, run_id: str) -> set[str]:
        """Load completed stages for a given run_id."""
        safe_run_id = validate_safe_value(run_id, "run_id")
        sql = (
            f"SELECT stage_name FROM `{self._table}` "
            f"WHERE run_id = '{safe_run_id}' AND status = 'completed'"
        )
        rows = self._client.execute_and_fetch(sql)
        return {row["stage_name"] for row in rows}

    def find_resumable_run(self) -> str | None:
        """Find the most recent incomplete run_id that can be resumed.

        Returns None if no resumable run exists.
        """
        sql = (
            f"SELECT run_id, MAX(completed_at) AS last_checkpoint "
            f"FROM `{self._table}` "
            f"WHERE status = 'completed' AND stage_name != '__run_complete__' "
            f"GROUP BY run_id "
            f"HAVING run_id NOT IN ("
            f"  SELECT run_id FROM `{self._table}` "
            f"  WHERE stage_name = '__run_complete__'"
            f") "
            f"ORDER BY last_checkpoint DESC LIMIT 1"
        )
        rows = self._client.execute_and_fetch(sql)
        if rows:
            return str(rows[0]["run_id"])
        return None

    def mark_stage_complete(
        self,
        run_id: str,
        stage_name: str,
        *,
        fencing_token: int | None = None,
        lock_table: str | None = None,
        pipeline_name: str | None = None,
    ) -> None:
        """Record that a stage has completed for a run.

        When fencing parameters are provided, uses a fenced INSERT that
        verifies the caller still holds the distributed lock before
        writing the checkpoint. This prevents a stale pod from recording
        checkpoints after its lock expired.

        Args:
            run_id: Pipeline run identifier.
            stage_name: Name of the completed stage.
            fencing_token: Expected fencing token from lock acquisition.
            lock_table: Fully-qualified lock table name.
            pipeline_name: Pipeline name to look up in lock table.
        """
        safe_run_id = validate_safe_value(run_id, "run_id")
        safe_stage = validate_safe_value(stage_name, "stage_name")

        fencing_params = (fencing_token, lock_table, pipeline_name)
        fencing_provided = sum(1 for p in fencing_params if p is not None)
        if 0 < fencing_provided < 3:
            raise ValueError(
                f"Partial fencing config for checkpoint '{run_id}/{stage_name}': "
                f"fencing_token={fencing_token}, lock_table={lock_table}, "
                f"pipeline_name={pipeline_name}. "
                f"All three must be provided when distributed locking is enabled, "
                f"or omit all three for unfenced checkpoints."
            )

        if fencing_provided == 3:
            assert fencing_token is not None
            assert lock_table is not None
            assert pipeline_name is not None
            now = datetime.now(UTC).isoformat()
            expr = build_fenced_checkpoint_insert_sql(
                checkpoint_table=self._table,
                run_id=safe_run_id,
                stage_name=safe_stage,
                now=now,
                status="completed",
                lock_table=lock_table,
                pipeline_name=pipeline_name,
                fencing_token=fencing_token,
            )
            self._client.execute_script(
                expr.render(), job_label=f"fenced_checkpoint_{stage_name}"
            )
        else:
            sql = (
                f"INSERT INTO `{self._table}` "
                f"(run_id, stage_name, completed_at, status) "
                f"VALUES ('{safe_run_id}', '{safe_stage}', "
                f"CURRENT_TIMESTAMP(), 'completed')"
            )
            self._client.execute(sql, job_label=f"checkpoint_{stage_name}")

    def mark_run_complete(
        self,
        run_id: str,
        *,
        fencing_token: int | None = None,
        lock_table: str | None = None,
        pipeline_name: str | None = None,
    ) -> None:
        """Mark an entire run as complete (prevents future resume)."""
        self.mark_stage_complete(
            run_id,
            "__run_complete__",
            fencing_token=fencing_token,
            lock_table=lock_table,
            pipeline_name=pipeline_name,
        )

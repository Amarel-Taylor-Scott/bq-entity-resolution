"""
Pipeline metrics collection and reporting.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from bq_entity_resolution.sql.utils import sql_escape

if TYPE_CHECKING:
    from bq_entity_resolution.backends.protocol import Backend
    from bq_entity_resolution.config.schema import PipelineConfig
    from bq_entity_resolution.pipeline.executor import PipelineResult

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects and reports pipeline execution metrics.

    When ``destination="bigquery"``, call :meth:`set_backend` before
    :meth:`record_run` so metrics can be persisted.  If no backend is
    set, metrics are still logged but not written to BigQuery.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self._backend: Backend | None = None

    def set_backend(self, backend: Backend) -> None:
        """Provide a backend for BigQuery persistence."""
        self._backend = backend

    def record_run(self, result: PipelineResult) -> None:
        """Record metrics from a pipeline result."""
        metrics: dict[str, Any] = {
            "run_id": result.run_id,
            "status": result.status,
            "duration_seconds": result.duration_seconds,
            "stages_completed": len(result.completed_stages),
            "stages_total": len(result.stage_results),
        }

        # Per-stage metrics
        total_sql = 0
        for sr in result.stage_results:
            if sr.skipped:
                continue
            total_sql += sr.sql_count
            metrics[f"stage_{sr.stage_name}_sql_count"] = sr.sql_count
            metrics[f"stage_{sr.stage_name}_duration"] = sr.duration_seconds

        metrics["total_sql_statements"] = total_sql

        if result.error:
            metrics["error"] = result.error

        logger.info("Pipeline metrics: %s", metrics)

        # Write to BigQuery if enabled
        if (
            self.config.monitoring.metrics.enabled
            and self.config.monitoring.metrics.destination == "bigquery"
        ):
            self._write_to_bigquery(metrics)

    # ------------------------------------------------------------------
    # BigQuery persistence
    # ------------------------------------------------------------------

    def _metrics_table(self) -> str:
        """Fully-qualified metrics table name."""
        p = self.config.project
        return f"{p.bq_project}.{p.watermark_dataset}.pipeline_metrics"

    def _write_to_bigquery(self, metrics: dict[str, Any]) -> None:
        """Write metrics to the ``pipeline_metrics`` BigQuery table.

        The table is auto-created on first write.  Metrics are stored as
        a flat row with per-stage values serialised to a JSON column for
        flexibility (stage counts vary across runs).
        """
        if self._backend is None:
            logger.warning(
                "Metrics destination is 'bigquery' but no backend was set. "
                "Call MetricsCollector.set_backend() before record_run(). "
                "Metrics will only be logged, not persisted."
            )
            return

        table = self._metrics_table()
        now = datetime.now(UTC).isoformat()

        # Separate fixed columns from per-stage dynamic columns
        stage_data: dict[str, Any] = {}
        fixed: dict[str, Any] = {}
        for k, v in metrics.items():
            if k.startswith("stage_"):
                stage_data[k] = v
            else:
                fixed[k] = v

        # Ensure the table exists
        create_ddl = (
            f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
            f"  run_id STRING,\n"
            f"  recorded_at TIMESTAMP,\n"
            f"  status STRING,\n"
            f"  duration_seconds FLOAT64,\n"
            f"  stages_completed INT64,\n"
            f"  stages_total INT64,\n"
            f"  total_sql_statements INT64,\n"
            f"  error STRING,\n"
            f"  stage_details STRING\n"  # JSON blob
            f")"
        )

        # Sanitize string values to prevent SQL injection
        run_id_safe = sql_escape(str(fixed.get("run_id", "")))
        status_safe = sql_escape(str(fixed.get("status", "")))
        error_val = fixed.get("error")
        error_safe = "NULL" if not error_val else f"'{sql_escape(str(error_val))}'"
        stage_json_safe = sql_escape(json.dumps(stage_data))

        insert_sql = (
            f"INSERT INTO `{table}` "
            f"(run_id, recorded_at, status, duration_seconds, "
            f"stages_completed, stages_total, total_sql_statements, "
            f"error, stage_details) "
            f"VALUES ("
            f"'{run_id_safe}', "
            f"TIMESTAMP '{now}', "
            f"'{status_safe}', "
            f"{fixed.get('duration_seconds', 0)}, "
            f"{fixed.get('stages_completed', 0)}, "
            f"{fixed.get('stages_total', 0)}, "
            f"{fixed.get('total_sql_statements', 0)}, "
            f"{error_safe}, "
            f"'{stage_json_safe}'"
            f")"
        )

        try:
            self._backend.execute(create_ddl)
            self._backend.execute(insert_sql)
            logger.info("Metrics persisted to %s", table)
        except Exception:
            logger.error(
                "Failed to persist metrics to %s. "
                "Metrics were logged but not written to BigQuery.",
                table,
                exc_info=True,
            )

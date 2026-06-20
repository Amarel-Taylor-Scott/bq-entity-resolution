"""
SQL runner: wraps BigQuery client with pipeline-level concerns.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.clients.bigquery import BigQueryClient, QueryResult

logger = logging.getLogger(__name__)


class SQLRunner:
    """
    Thin wrapper around BigQueryClient that adds:
    - SQL execution logging
    - Execution history tracking
    - Dry-run propagation
    """

    def __init__(self, bq_client: BigQueryClient):
        self.bq_client = bq_client
        self.executed_queries: list[dict[str, Any]] = []

    def execute(self, sql: str, job_label: str = "") -> QueryResult:
        """Execute SQL and track it."""
        entry: dict[str, Any] = {
            "label": job_label,
            "sql_preview": sql[:500],
            "status": "executing",
        }
        self.executed_queries.append(entry)

        try:
            result = self.bq_client.execute(sql, job_label=job_label)
            entry["status"] = "success"
            entry["job_id"] = result.job_id
            entry["bytes_billed"] = result.bytes_billed
            entry["duration"] = result.duration_seconds
            return result
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            raise

    def execute_and_fetch(self, sql: str, job_label: str = "") -> list[dict[str, Any]]:
        """Execute SQL and return rows."""
        return self.bq_client.execute_and_fetch(sql, job_label=job_label)

    def execute_script(self, sql: str, job_label: str = "") -> QueryResult:
        """Execute a multi-statement SQL script (BigQuery scripting)."""
        return self.execute(sql, job_label=job_label)

    def execute_script_and_fetch(self, sql: str, job_label: str = "") -> list[dict[str, Any]]:
        """Execute a multi-statement SQL script and return the final result set."""
        entry: dict[str, Any] = {
            "label": job_label,
            "sql_preview": sql[:500],
            "status": "executing",
        }
        self.executed_queries.append(entry)

        try:
            rows = self.bq_client.execute_script_and_fetch(
                sql, job_label=job_label
            )
            entry["status"] = "success"
            entry["rows_returned"] = len(rows)
            return rows
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            raise

    @property
    def total_bytes_billed(self) -> int:
        """Sum of bytes billed across all executed queries."""
        return sum(
            q.get("bytes_billed", 0)
            for q in self.executed_queries
            if q["status"] == "success"
        )

    @property
    def execution_log(self) -> list[dict[str, Any]]:
        """Return all executed queries for audit."""
        return self.executed_queries

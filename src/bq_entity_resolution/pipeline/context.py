"""
Pipeline run context: carries state through pipeline execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.naming import all_matches_table as _all_matches_table


@dataclass
class PipelineContext:
    """Mutable context object passed through all pipeline stages."""

    run_id: str
    started_at: datetime
    config: PipelineConfig
    full_refresh: bool = False
    finished_at: datetime | None = None
    status: str = "running"
    error: str | None = None
    watermarks: dict[str, Any] = field(default_factory=dict)
    staged_sources: list[str] = field(default_factory=list)
    tier_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    sql_log: list[dict[str, Any]] = field(default_factory=list)
    cluster_quality: dict[str, Any] | None = None
    completed_stages: set[str] = field(default_factory=set)

    @property
    def all_matches_table(self) -> str:
        """Fully-qualified table for accumulated matched pairs."""
        return _all_matches_table(self.config)

    def log_sql(self, stage: str, step: str, sql: str) -> None:
        """Record executed SQL for debugging and audit."""
        self.sql_log.append({
            "stage": stage,
            "step": step,
            "sql": sql,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    @property
    def duration_seconds(self) -> float:
        """Total pipeline duration in seconds."""
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return (datetime.now(UTC) - self.started_at).total_seconds()

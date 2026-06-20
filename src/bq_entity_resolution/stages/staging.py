"""Staging stage: loads source data into bronze staging area.

Extracted from PipelineOrchestrator._stage_sources().
Uses the staging SQL builder for SQL generation.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig, SourceConfig
from bq_entity_resolution.naming import staged_table
from bq_entity_resolution.sql.builders.staging import (
    JoinDef,
    StagingParams,
    build_staging_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class StagingStage(Stage):
    """Load incremental source data into staging tables.

    One instance per source. Generates a CREATE TABLE AS SELECT
    with watermark filtering, joins, and entity UID generation.
    """

    def __init__(self, source: SourceConfig, config: PipelineConfig):
        self._source = source
        self._config = config

    @property
    def name(self) -> str:
        return f"staging_{self._source.name}"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "source": TableRef(
                name=self._source.name,
                fq_name=self._source.table,
                description=f"Raw source table: {self._source.table}",
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = staged_table(self._config, self._source.name)
        return {
            "staged": TableRef(
                name=f"staged_{self._source.name}",
                fq_name=target,
                description=f"Staged bronze data from {self._source.name}",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate staging SQL.

        kwargs:
            watermark: dict[str, Any] | None
            full_refresh: bool
        """
        logger.debug("Planning %s stage", self.__class__.__name__)
        watermark = kwargs.get("watermark")
        full_refresh = kwargs.get("full_refresh", False)
        source = self._source
        target = self.outputs["staged"].fq_name

        joins = [
            JoinDef(
                table=j.table,
                on=j.on,
                type=getattr(j, "type", "LEFT"),
                alias=getattr(j, "alias", ""),
            )
            for j in getattr(source, "joins", [])
        ]

        # Clustering from ScaleConfig
        cluster_by = list(
            getattr(
                getattr(self._config, "scale", None),
                "staging_clustering",
                ["entity_uid"],
            ) or []
        )

        params = StagingParams(
            target_table=target,
            source_name=source.name,
            source_table=source.table,
            unique_key=source.unique_key,
            updated_at=source.updated_at,
            columns=[c.name for c in source.columns],
            passthrough_columns=getattr(source, "passthrough_columns", []),
            joins=joins,
            filter=getattr(source, "filter", None),
            watermark=watermark,
            grace_period_hours=getattr(
                self._config.incremental, "grace_period_hours", 0
            ),
            full_refresh=full_refresh,
            partition_column=getattr(source, "partition_column", None),
            batch_size=getattr(source, "batch_size", None),
            cluster_by=cluster_by,
        )

        return [build_staging_sql(params)]

    def validate(self) -> list[str]:
        errors = []
        if not self._source.table:
            errors.append(f"Source '{self._source.name}' has no table defined")
        if not self._source.unique_key:
            errors.append(f"Source '{self._source.name}' has no unique_key")
        if not self._source.updated_at:
            errors.append(f"Source '{self._source.name}' has no updated_at")
        return errors

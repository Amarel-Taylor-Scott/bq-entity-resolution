"""Cluster quality stage: compute cluster quality metrics for monitoring."""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.naming import (
    all_matches_table,
)
from bq_entity_resolution.naming import (
    cluster_table as _cluster_table,
)
from bq_entity_resolution.sql.builders.clustering import (
    ClusterMetricsParams,
    build_cluster_quality_metrics_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class ClusterQualityStage(Stage):
    """Compute cluster quality metrics for monitoring."""

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "cluster_quality"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "clusters": TableRef(
                name="clusters",
                fq_name=_cluster_table(self._config),
            ),
            "all_matches": TableRef(
                name="all_matches",
                fq_name=all_matches_table(self._config),
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate cluster quality metrics SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        params = ClusterMetricsParams(
            cluster_table=self.inputs["clusters"].fq_name,
            matches_table=self.inputs["all_matches"].fq_name,
        )

        return [build_cluster_quality_metrics_sql(params)]

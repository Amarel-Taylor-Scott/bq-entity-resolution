"""Canonical index stages: init + populate for incremental processing.

The canonical_index table accumulates all entities across batches with
their cluster_ids, enabling cross-batch blocking and incremental clustering.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.naming import (
    canonical_index_table,
    featured_table,
)
from bq_entity_resolution.naming import (
    cluster_table as _cluster_table,
)
from bq_entity_resolution.sql.builders.clustering import (
    CanonicalIndexInitParams,
    PopulateCanonicalIndexParams,
    build_canonical_index_init_sql,
    build_populate_canonical_index_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class CanonicalIndexInitStage(Stage):
    """Create canonical_index table if it doesn't exist.

    Runs before clustering on every incremental run. Uses
    CREATE TABLE IF NOT EXISTS, so it's a no-op after the first run.
    The table mirrors the featured table schema plus a cluster_id column.
    """

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "canonical_index_init"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        return {
            "canonical_index": TableRef(
                name="canonical_index",
                fq_name=canonical_index_table(self._config),
                description="Canonical index (all entities across batches)",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate CREATE TABLE IF NOT EXISTS SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        scale = getattr(self._config, "scale", None)
        params = CanonicalIndexInitParams(
            canonical_table=self.outputs["canonical_index"].fq_name,
            source_table=self.inputs["featured"].fq_name,
            cluster_by=(
                getattr(scale, "canonical_index_clustering", ["entity_uid"])
                if scale else ["entity_uid"]
            ),
            partition_by=getattr(scale, "canonical_index_partition_by", None) if scale else None,
        )
        return [build_canonical_index_init_sql(params)]


class CanonicalIndexPopulateStage(Stage):
    """Upsert current batch into canonical_index after clustering.

    Updates cluster_ids for entities that were re-clustered (their
    cluster assignment changed due to new match edges), and inserts
    new entities from the current batch with their cluster_ids.

    Note: This stage modifies canonical_index in place (UPDATE + INSERT)
    rather than creating a new table. It does not declare canonical_index
    as an output to avoid creating a cycle in the DAG (ClusteringStage
    also reads canonical_index).
    """

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "canonical_index_populate"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
            "clusters": TableRef(
                name="clusters",
                fq_name=_cluster_table(self._config),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        return {}

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate canonical index upsert SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        params = PopulateCanonicalIndexParams(
            canonical_table=canonical_index_table(self._config),
            source_table=self.inputs["featured"].fq_name,
            cluster_table=self.inputs["clusters"].fq_name,
        )
        return [build_populate_canonical_index_sql(params)]

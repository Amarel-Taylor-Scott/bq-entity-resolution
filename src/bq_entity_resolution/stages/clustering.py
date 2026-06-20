"""Clustering stage: assign entity clusters using connected components.

Supports both full-refresh and incremental modes. In incremental mode,
initializes from canonical_index (prior entities) and adds new entities
as singletons before propagating minimum cluster_id through match edges.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.naming import (
    all_matches_table,
    canonical_index_table,
    featured_table,
)
from bq_entity_resolution.naming import (
    cluster_table as _cluster_table,
)
from bq_entity_resolution.sql.builders.clustering import (
    BestMatchClusteringParams,
    ClusteringParams,
    IncrementalClusteringParams,
    StarClusteringParams,
    build_best_match_cluster_sql,
    build_cluster_assignment_sql,
    build_incremental_cluster_sql,
    build_star_cluster_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class ClusteringStage(Stage):
    """Assign entity clusters using connected components.

    When incremental processing is enabled, uses incremental clustering
    that initializes from the canonical_index (prior entities with their
    cluster assignments) and adds new entities as singletons before
    propagating minimum cluster_id through match edges.
    """

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "clustering"

    @property
    def _is_incremental(self) -> bool:
        inc = getattr(self._config, "incremental", None)
        return bool(inc and getattr(inc, "enabled", False))

    @property
    def inputs(self) -> dict[str, TableRef]:
        refs = {
            "all_matches": TableRef(
                name="all_matches",
                fq_name=all_matches_table(self._config),
            ),
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
        }
        if self._is_incremental:
            refs["canonical_index"] = TableRef(
                name="canonical_index",
                fq_name=canonical_index_table(self._config),
            )
        return refs

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = _cluster_table(self._config)
        return {
            "clusters": TableRef(
                name="clusters",
                fq_name=target,
                description="Entity cluster assignments",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate cluster assignment SQL.

        Selects algorithm based on config:
        - connected_components: Iterative minimum-propagation (default).
        - star: Single-pass highest-score center election.
        - best_match: Each entity joins its single best match's cluster.

        Uses incremental clustering when incremental processing is enabled,
        which initializes from canonical_index + new singletons.
        """
        clustering_cfg = self._config.reconciliation.clustering
        method = getattr(clustering_cfg, "method", "connected_components")
        max_iter = getattr(clustering_cfg, "max_iterations", 20)

        logger.info(
            "Clustering match pairs using method '%s' (max_iterations=%d)",
            method,
            max_iter,
        )
        min_conf = getattr(clustering_cfg, "min_cluster_confidence", 0.0)

        matches_tbl = self.inputs["all_matches"].fq_name
        cluster_tbl = self.outputs["clusters"].fq_name
        source_tbl = self.inputs["featured"].fq_name

        # Incremental mode only supported for connected_components
        if self._is_incremental and method == "connected_components":
            params = IncrementalClusteringParams(
                all_matches_table=matches_tbl,
                cluster_table=cluster_tbl,
                source_table=source_tbl,
                canonical_table=self.inputs["canonical_index"].fq_name,
                max_iterations=max_iter,
            )
            return [build_incremental_cluster_sql(params)]

        if method == "star":
            params_star = StarClusteringParams(
                all_matches_table=matches_tbl,
                cluster_table=cluster_tbl,
                source_table=source_tbl,
                min_confidence=min_conf,
            )
            return [build_star_cluster_sql(params_star)]

        if method == "best_match":
            params_bm = BestMatchClusteringParams(
                all_matches_table=matches_tbl,
                cluster_table=cluster_tbl,
                source_table=source_tbl,
                min_confidence=min_conf,
            )
            return [build_best_match_cluster_sql(params_bm)]

        # Default: connected_components
        params_cc = ClusteringParams(
            all_matches_table=matches_tbl,
            cluster_table=cluster_tbl,
            source_table=source_tbl,
            max_iterations=max_iter,
        )
        return [build_cluster_assignment_sql(params_cc)]

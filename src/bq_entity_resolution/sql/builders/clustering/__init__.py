"""SQL builders for clustering (package).

Barrel re-exports for backward compatibility. All existing imports from
``bq_entity_resolution.sql.builders.clustering`` continue to work unchanged.

Sub-modules:
  - connected_components: Standard connected components algorithm
  - incremental: Incremental clustering and canonical index management
  - alternatives: Star clustering and best-match clustering
  - metrics: Cluster quality metrics and confidence shaping
"""

from bq_entity_resolution.sql.builders.clustering.alternatives import (
    BestMatchClusteringParams,
    StarClusteringParams,
    build_best_match_cluster_sql,
    build_star_cluster_sql,
)
from bq_entity_resolution.sql.builders.clustering.connected_components import (
    ClusteringParams,
    build_cluster_assignment_sql,
)
from bq_entity_resolution.sql.builders.clustering.incremental import (
    CanonicalIndexInitParams,
    IncrementalClusteringParams,
    PopulateCanonicalIndexParams,
    build_canonical_index_init_sql,
    build_incremental_cluster_sql,
    build_populate_canonical_index_sql,
)
from bq_entity_resolution.sql.builders.clustering.metrics import (
    ClusterMetricsParams,
    ClusterStabilityParams,
    ConfidenceShapingParams,
    build_cluster_quality_metrics_sql,
    build_cluster_stability_sql,
    build_confidence_shaping_sql,
)

__all__ = [
    # Connected components
    "ClusteringParams",
    "build_cluster_assignment_sql",
    # Incremental
    "CanonicalIndexInitParams",
    "IncrementalClusteringParams",
    "PopulateCanonicalIndexParams",
    "build_canonical_index_init_sql",
    "build_incremental_cluster_sql",
    "build_populate_canonical_index_sql",
    # Alternative strategies
    "BestMatchClusteringParams",
    "StarClusteringParams",
    "build_best_match_cluster_sql",
    "build_star_cluster_sql",
    # Metrics & confidence shaping
    "ClusterMetricsParams",
    "ClusterStabilityParams",
    "ConfidenceShapingParams",
    "build_cluster_quality_metrics_sql",
    "build_cluster_stability_sql",
    "build_confidence_shaping_sql",
]

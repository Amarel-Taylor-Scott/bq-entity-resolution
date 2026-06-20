"""
Clustering strategy implementations.

Provides different methods for assigning entity clusters from pairwise matches.
"""

from __future__ import annotations

from bq_entity_resolution.config.schema import ClusteringConfig


def get_clustering_description(config: ClusteringConfig) -> str:
    """Return a human-readable description of the clustering strategy."""
    descriptions = {
        "connected_components": (
            f"Connected components with max {config.max_iterations} iterations. "
            f"Propagates minimum entity_uid as cluster_id through match edges "
            f"until convergence."
        ),
        "star": (
            "Star clustering: each matched entity is assigned to the cluster "
            "of its highest-scoring match partner. Faster but may miss "
            "transitive relationships."
        ),
        "best_match": (
            "Best-match clustering: each entity joins the cluster of its "
            "single best match. No transitive closure."
        ),
    }
    return descriptions.get(config.method, f"Unknown method: {config.method}")

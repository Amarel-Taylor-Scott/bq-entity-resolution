"""Reconciliation: clustering strategies and canonical record selection."""

from bq_entity_resolution.reconciliation.clustering import get_clustering_description
from bq_entity_resolution.reconciliation.output import (
    canonical_selection_order,
    completeness_score_expr,
)

__all__ = [
    "canonical_selection_order",
    "completeness_score_expr",
    "get_clustering_description",
]

"""Reconciliation stages — backward-compatible re-exports.

The stage classes have been split into focused modules:
- clustering.py: ClusteringStage
- canonical_index.py: CanonicalIndexInitStage, CanonicalIndexPopulateStage
- gold_output.py: GoldOutputStage
- cluster_quality.py: ClusterQualityStage

This module re-exports all classes for backward compatibility.
"""

from bq_entity_resolution.stages.canonical_index import (
    CanonicalIndexInitStage,
    CanonicalIndexPopulateStage,
)
from bq_entity_resolution.stages.cluster_quality import ClusterQualityStage
from bq_entity_resolution.stages.clustering import ClusteringStage
from bq_entity_resolution.stages.gold_output import GoldOutputStage

__all__ = [
    "CanonicalIndexInitStage",
    "CanonicalIndexPopulateStage",
    "ClusterQualityStage",
    "ClusteringStage",
    "GoldOutputStage",
]

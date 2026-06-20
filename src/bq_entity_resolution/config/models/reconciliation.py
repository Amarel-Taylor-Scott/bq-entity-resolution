"""
Reconciliation and output configuration models.

Defines clustering, canonical selection, audit trail, output, and
reconciliation configuration for cross-tier entity resolution.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = [
    "ClusteringConfig",
    "FieldMergeStrategy",
    "CanonicalSelectionConfig",
    "ConfidenceShapingConfig",
    "AuditTrailConfig",
    "OutputConfig",
    "ReconciliationConfig",
]


class ClusteringConfig(BaseModel):
    """Clustering algorithm configuration.

    Available methods:
        connected_components (default): Iterative min-propagation that
            guarantees transitive closure. If A matches B and B matches C,
            all three end up in the same cluster. Best for deduplication
            where you want maximum recall. May create large clusters if
            blocking is too coarse.

        star: Single-pass hub-based clustering. Each entity picks its
            highest-scoring neighbor as hub. Does NOT guarantee transitive
            closure -- may split chains. Faster than connected_components
            but produces smaller, more conservative clusters. Use when
            precision matters more than recall.

        best_match: Greedy 1:1 matching. Maximum cluster size is 2.
            Use for record linkage between two distinct sources
            (not for deduplication within a single source).
    """

    method: Literal["connected_components", "star", "best_match"] = "connected_components"
    max_iterations: int = 20
    min_cluster_confidence: float = 0.0

    @field_validator("max_iterations")
    @classmethod
    def _positive_max_iter(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_iterations must be >= 1")
        return v

    @field_validator("min_cluster_confidence")
    @classmethod
    def _non_negative_confidence(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("min_cluster_confidence must be >= 0.0")
        return v


class FieldMergeStrategy(BaseModel):
    """Per-field strategy for golden record assembly.

    Used when canonical_selection.method = 'field_merge'.
    Each field can independently choose which record's value to pick.

    Strategies:
        most_complete:    Value from the record with the most non-null fields.
        most_recent:      Value from the most recently updated record.
        source_priority:  Value from the highest-priority source.
        most_common:      Most frequently occurring non-null value (majority vote).
        weighted_vote:    Value with the highest recency-weighted vote count.
                          Uses exponential time decay (configurable via decay_rate).
    """

    column: str
    strategy: Literal[
        "most_complete", "most_recent", "source_priority",
        "most_common", "weighted_vote",
    ] = "most_complete"
    source_priority: list[str] = Field(default_factory=list)
    decay_rate: float = 0.01  # Daily decay rate for weighted_vote strategy

    @field_validator("decay_rate")
    @classmethod
    def _non_negative_decay(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("decay_rate must be >= 0.0")
        return v


class CanonicalSelectionConfig(BaseModel):
    """How to elect the canonical record within a cluster."""

    method: Literal[
        "completeness", "recency", "source_priority", "field_merge"
    ] = "completeness"
    source_priority: list[str] = Field(default_factory=list)
    field_strategies: list[FieldMergeStrategy] = Field(default_factory=list)
    default_field_strategy: Literal[
        "most_complete", "most_recent", "source_priority",
        "most_common", "weighted_vote",
    ] = "most_complete"

    @model_validator(mode="after")
    def _validate_field_merge_strategies(self) -> Self:
        if self.method == "field_merge" and not self.field_strategies:
            raise ValueError(
                "CanonicalSelectionConfig with method='field_merge' requires "
                "at least one field_strategy. Define field_strategies to specify "
                "how each field should be merged (most_complete, most_recent, etc.)."
            )
        return self


class ConfidenceShapingConfig(BaseModel):
    """Post-clustering confidence adjustment.

    Adjusts match confidence based on cluster characteristics:
      - group_size_penalty: Penalizes confidence for abnormally large clusters.
      - hub_node_detection: Flags entities with too many connections.
    """

    group_size_penalty: bool = False
    group_size_threshold: int = 10  # cluster size above which penalty applies
    group_size_penalty_rate: float = 0.02  # per-member penalty above threshold
    hub_node_detection: bool = False
    hub_degree_threshold: int = 20  # max edges before node is flagged as hub

    @field_validator("group_size_threshold", "hub_degree_threshold")
    @classmethod
    def _positive_thresholds(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Threshold must be >= 1")
        return v

    @field_validator("group_size_penalty_rate")
    @classmethod
    def _non_negative_penalty_rate(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("group_size_penalty_rate must be >= 0.0")
        return v


class AuditTrailConfig(BaseModel):
    """Per-match audit trail for debugging and compliance.

    When enabled, each match row includes a JSON column with individual
    comparison scores/weights so you can see exactly why a pair matched.
    """

    enabled: bool = False
    include_individual_scores: bool = True


class OutputConfig(BaseModel):
    """Gold layer output configuration."""

    include_match_metadata: bool = True
    include_passthrough: bool = True
    entity_id_prefix: str = "ENT"

    @field_validator("entity_id_prefix")
    @classmethod
    def _validate_entity_id_prefix(cls, v: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9]{1,20}', v):
            raise ValueError(
                "entity_id_prefix must be alphanumeric only and at most 20 characters, "
                f"got '{v}'"
            )
        return v

    partition_column: str | None = None
    cluster_columns: list[str] = Field(default_factory=list)
    audit_trail: AuditTrailConfig = Field(default_factory=AuditTrailConfig)


class ReconciliationConfig(BaseModel):
    """Cross-tier reconciliation configuration."""

    strategy: Literal["tier_priority", "highest_score", "manual_review"] = "tier_priority"
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    canonical_selection: CanonicalSelectionConfig = Field(
        default_factory=CanonicalSelectionConfig
    )
    confidence_shaping: ConfidenceShapingConfig = Field(
        default_factory=ConfidenceShapingConfig
    )
    output: OutputConfig = Field(default_factory=OutputConfig)

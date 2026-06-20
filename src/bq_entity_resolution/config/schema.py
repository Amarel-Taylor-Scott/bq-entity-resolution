"""
Pydantic v2 models defining the complete YAML configuration schema.

Every pipeline behavior is driven by these models. Validated at load time
so configuration errors surface before any BigQuery SQL is generated.

Models are organized into domain-specific sub-modules under
``config.models``. This file re-exports everything for backwards
compatibility --- existing ``from bq_entity_resolution.config.schema import X``
imports continue to work unchanged.
"""

# Re-export all models from domain-specific sub-modules
# ruff: noqa: F405
from bq_entity_resolution.config.models.blocking import *  # noqa: F401,F403
from bq_entity_resolution.config.models.features import *  # noqa: F401,F403
from bq_entity_resolution.config.models.infrastructure import *  # noqa: F401,F403
from bq_entity_resolution.config.models.matching import *  # noqa: F401,F403
from bq_entity_resolution.config.models.pipeline import *  # noqa: F401,F403
from bq_entity_resolution.config.models.reconciliation import *  # noqa: F401,F403
from bq_entity_resolution.config.models.source import *  # noqa: F401,F403

__all__ = [
    # source
    "ColumnMapping",
    "JoinConfig",
    "SourceConfig",
    # features
    "FeatureDef",
    "FeatureGroupConfig",
    "BlockingKeyDef",
    "CompositeKeyDef",
    "EnrichmentJoinConfig",
    "CompoundDetectionConfig",
    "PlaceholderPatternDef",
    "PlaceholderConfig",
    "FeatureEngineeringConfig",
    # blocking
    "BlockingPathDef",
    "TierBlockingConfig",
    # matching
    "ComparisonLevelDef",
    "TermFrequencyConfig",
    "ComparisonDef",
    "ThresholdConfig",
    "HardNegativeDef",
    "HardPositiveDef",
    "SoftSignalDef",
    "ScoreBandDef",
    "ScoreBandingConfig",
    "TrainingConfig",
    "LabelFeedbackConfig",
    "ActiveLearningConfig",
    "MatchingTierConfig",
    # reconciliation
    "ClusteringConfig",
    "FieldMergeStrategy",
    "CanonicalSelectionConfig",
    "ConfidenceShapingConfig",
    "AuditTrailConfig",
    "OutputConfig",
    "ReconciliationConfig",
    # infrastructure
    "ProjectConfig",
    "LSHConfig",
    "EmbeddingConfig",
    "PartitionCursorConfig",
    "HashCursorConfig",
    "IncrementalConfig",
    "MetricsConfig",
    "ProfilingConfig",
    "BlockingMetricsConfig",
    "ClusterQualityConfig",
    "JobTrackingConfig",
    "PlaceholderTrackingConfig",
    "MonitoringConfig",
    "ScaleConfig",
    "ExecutionConfig",
    # pipeline (root)
    "PipelineConfig",
]

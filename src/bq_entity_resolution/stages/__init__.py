"""Pipeline stages: composable, testable units of pipeline work.

Each stage declares its inputs, outputs, and plan() method.
The plan() method returns SQL expressions without side effects.
The executor handles running the SQL and managing state.
"""

from bq_entity_resolution.stages.active_learning import ActiveLearningStage
from bq_entity_resolution.stages.base import Stage, StageResult, TableRef
from bq_entity_resolution.stages.blocking import BlockingStage
from bq_entity_resolution.stages.bqml_classification import (
    BQMLEvaluateStage,
    BQMLPredictStage,
    BQMLTrainingStage,
    FeatureMatrixExportStage,
)
from bq_entity_resolution.stages.canonical_index import (
    CanonicalIndexInitStage,
    CanonicalIndexPopulateStage,
)
from bq_entity_resolution.stages.cluster_quality import ClusterQualityStage
from bq_entity_resolution.stages.clustering import ClusteringStage
from bq_entity_resolution.stages.features import FeatureEngineeringStage, TermFrequencyStage
from bq_entity_resolution.stages.gold_output import GoldOutputStage
from bq_entity_resolution.stages.label_ingestion import LabelIngestionStage
from bq_entity_resolution.stages.match_accumulation import MatchAccumulationStage
from bq_entity_resolution.stages.matching import MatchingStage
from bq_entity_resolution.stages.placeholder_detection import PlaceholderDetectionStage
from bq_entity_resolution.stages.staging import StagingStage

__all__ = [
    "Stage",
    "TableRef",
    "StageResult",
    "StagingStage",
    "FeatureEngineeringStage",
    "TermFrequencyStage",
    "BlockingStage",
    "MatchingStage",
    "MatchAccumulationStage",
    "ClusteringStage",
    "CanonicalIndexInitStage",
    "CanonicalIndexPopulateStage",
    "GoldOutputStage",
    "ClusterQualityStage",
    "ActiveLearningStage",
    "LabelIngestionStage",
    "FeatureMatrixExportStage",
    "BQMLTrainingStage",
    "BQMLPredictStage",
    "BQMLEvaluateStage",
    "PlaceholderDetectionStage",
]

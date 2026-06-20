"""BigQuery Entity Resolution Pipeline -- configurable multi-tier matching.

Quick start::

    from bq_entity_resolution import Pipeline, quick_config

    config = quick_config(
        bq_project="my-gcp-project",
        source_table="my-gcp-project.raw.customers",
        columns=["first_name", "last_name", "email", "phone"],
    )
    pipeline = Pipeline(config)
    plan = pipeline.plan()
    print(plan.preview())

Extending the pipeline::

    from bq_entity_resolution import (
        Pipeline, Stage, TableRef, StageDAG, build_pipeline_dag,
        register_feature, register_comparison,
    )

    # Register custom feature/comparison functions
    @register_feature("my_custom_feature")
    def my_custom_feature(inputs: list[str], **_: Any) -> str:
        return f"UPPER(TRIM({inputs[0]}))"

    # Replace or inject stages
    pipeline = Pipeline(config, stage_overrides={"clustering": MyStage(config)})

    # Or build a fully custom DAG
    pipeline = Pipeline.from_stages(config, stages=[...], explicit_edges={...})
"""

from typing import Any

from bq_entity_resolution.backends.protocol import Backend, QueryResult
from bq_entity_resolution.config.entity_types import (
    ENTITY_TYPE_TEMPLATES,
    EntityTypeTemplate,
    get_entity_type,
    list_entity_types,
    register_entity_type,
)
from bq_entity_resolution.config.loader import load_config
from bq_entity_resolution.config.presets import (
    business_dedup_preset,
    education_student_preset,
    financial_transaction_preset,
    healthcare_patient_preset,
    identity_fraud_preset,
    insurance_dedup_preset,
    logistics_carrier_preset,
    person_dedup_preset,
    person_linkage_preset,
    public_sector_preset,
    quick_config,
    real_estate_property_preset,
    retail_customer_preset,
    telecom_subscriber_preset,
    travel_guest_preset,
    vendor_master_preset,
)
from bq_entity_resolution.config.roles import (
    blocking_keys_for_role,
    comparisons_for_role,
    detect_role,
    features_for_role,
)
from bq_entity_resolution.config.schema import PipelineConfig, SourceConfig
from bq_entity_resolution.exceptions import (
    ConfigurationError,
    EntityResolutionError,
    PipelineAbortError,
    PipelineCostExceededError,
    SQLExecutionError,
)

# Registries (for custom extensions)
from bq_entity_resolution.features.registry import (
    FEATURE_FUNCTIONS,
)
from bq_entity_resolution.features.registry import (
    register as register_feature,
)
from bq_entity_resolution.matching.comparisons import (
    COMPARISON_COSTS,
    COMPARISON_FUNCTIONS,
)
from bq_entity_resolution.matching.comparisons import (
    register as register_comparison,
)
from bq_entity_resolution.monitoring.data_quality import DataQualityScore, DataQualityScorer
from bq_entity_resolution.pipeline.dag import StageDAG, build_pipeline_dag
from bq_entity_resolution.pipeline.executor import (
    CheckpointManagerProtocol,
    PipelineExecutor,
    PipelineResult,
    ProgressCallback,
)
from bq_entity_resolution.pipeline.gates import (
    ClusterSizeGate,
    DataQualityGate,
    DataQualityScoreGate,
    GateResult,
    OutputNotEmptyGate,
)
from bq_entity_resolution.pipeline.health import HealthProbe
from bq_entity_resolution.pipeline.pipeline import CostEstimate, Pipeline
from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan
from bq_entity_resolution.pipeline.shutdown import GracefulShutdown
from bq_entity_resolution.pipeline.validator import ContractViolation
from bq_entity_resolution.profiling.placeholder_profiler import PlaceholderProfiler
from bq_entity_resolution.sql.builders.blocking_effectiveness import (
    BlockingEffectivenessParams,
    TierEffectivenessParams,
)
from bq_entity_resolution.sql.builders.job_tracking import RunComparisonParams
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, StageResult, TableRef

# BQML classification (supervised match prediction)
from bq_entity_resolution.stages.bqml_classification import (
    BQMLEvaluateStage,
    BQMLPredictStage,
    BQMLTrainingStage,
    FeatureMatrixExportStage,
)
from bq_entity_resolution.version import __version__
from bq_entity_resolution.watermark.checkpoint import CheckpointManager
from bq_entity_resolution.watermark.manager import WatermarkManager


# Lazy imports for backends with optional dependencies
def __getattr__(name: str) -> Any:
    if name == "BigQueryBackend":
        from bq_entity_resolution.backends.bigquery import BigQueryBackend
        return BigQueryBackend
    if name == "DuckDBBackend":
        from bq_entity_resolution.backends.duckdb import DuckDBBackend
        return DuckDBBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "__version__",
    # Core
    "Pipeline",
    "PipelineConfig",
    "SourceConfig",
    "load_config",
    # Presets
    "quick_config",
    "person_dedup_preset",
    "person_linkage_preset",
    "business_dedup_preset",
    "insurance_dedup_preset",
    "financial_transaction_preset",
    "healthcare_patient_preset",
    "telecom_subscriber_preset",
    "logistics_carrier_preset",
    "retail_customer_preset",
    "real_estate_property_preset",
    "public_sector_preset",
    "education_student_preset",
    "travel_guest_preset",
    "vendor_master_preset",
    "identity_fraud_preset",
    # Registries
    "FEATURE_FUNCTIONS",
    "COMPARISON_FUNCTIONS",
    "COMPARISON_COSTS",
    "register_feature",
    "register_comparison",
    # Extensibility: stages
    "Stage",
    "TableRef",
    "StageResult",
    "SQLExpression",
    # Extensibility: DAG
    "StageDAG",
    "build_pipeline_dag",
    # Extensibility: plan + executor
    "PipelinePlan",
    "StagePlan",
    "PipelineExecutor",
    "PipelineResult",
    "ProgressCallback",
    "CheckpointManagerProtocol",
    # Extensibility: gates + validation
    "DataQualityGate",
    "DataQualityScoreGate",
    "GateResult",
    "OutputNotEmptyGate",
    "ClusterSizeGate",
    "ContractViolation",
    # SQL builders
    "RunComparisonParams",
    "BlockingEffectivenessParams",
    "TierEffectivenessParams",
    # Monitoring & profiling
    "DataQualityScore",
    "DataQualityScorer",
    "PlaceholderProfiler",
    # Backends
    "Backend",
    "QueryResult",
    "DuckDBBackend",
    "BigQueryBackend",
    # Role utilities
    "detect_role",
    "features_for_role",
    "blocking_keys_for_role",
    "comparisons_for_role",
    # Entity type templates
    "EntityTypeTemplate",
    "ENTITY_TYPE_TEMPLATES",
    "register_entity_type",
    "get_entity_type",
    "list_entity_types",
    # BQML classification
    "FeatureMatrixExportStage",
    "BQMLTrainingStage",
    "BQMLPredictStage",
    "BQMLEvaluateStage",
    # Production deployment
    "HealthProbe",
    "GracefulShutdown",
    "CheckpointManager",
    "WatermarkManager",
    # Cost estimation
    "CostEstimate",
    # Exceptions
    "EntityResolutionError",
    "ConfigurationError",
    "PipelineAbortError",
    "PipelineCostExceededError",
    "SQLExecutionError",
]

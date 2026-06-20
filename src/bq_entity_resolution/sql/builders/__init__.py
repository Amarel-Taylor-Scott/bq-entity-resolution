"""SQL builders: composable, testable SQL generation replacing Jinja2 templates.

Each builder module corresponds to a pipeline stage and contains:
- Frozen dataclass parameter definitions (type-safe inputs)
- Builder functions that return SQLExpression objects
- Full dialect support (bigquery, duckdb) via SQLExpression.render()
"""

from bq_entity_resolution.sql.builders.active_learning import (
    ActiveLearningParams,
    IngestLabelsParams,
    build_active_learning_sql,
    build_ingest_labels_sql,
)
from bq_entity_resolution.sql.builders.blocking import (
    BlockingMetricsParams,
    BlockingParams,
    build_blocking_metrics_sql,
    build_blocking_sql,
)
from bq_entity_resolution.sql.builders.blocking_effectiveness import (
    BlockingEffectivenessParams,
    TierEffectivenessParams,
    build_blocking_effectiveness_sql,
)
from bq_entity_resolution.sql.builders.clustering import (
    ClusteringParams,
    ClusterMetricsParams,
    IncrementalClusteringParams,
    PopulateCanonicalIndexParams,
    build_cluster_assignment_sql,
    build_cluster_quality_metrics_sql,
    build_incremental_cluster_sql,
    build_populate_canonical_index_sql,
)
from bq_entity_resolution.sql.builders.comparison import (
    FellegiSunterParams,
    SumScoringParams,
    build_fellegi_sunter_sql,
    build_sum_scoring_sql,
)
from bq_entity_resolution.sql.builders.em import (
    EMParams,
    LabelEstimationParams,
    build_em_estimation_sql,
    build_estimate_from_labels_sql,
)
from bq_entity_resolution.sql.builders.embeddings import (
    EmbeddingsParams,
    LSHParams,
    build_embeddings_sql,
    build_lsh_buckets_sql,
)
from bq_entity_resolution.sql.builders.features import (
    FeatureParams,
    build_features_sql,
    build_term_frequencies_sql,
)
from bq_entity_resolution.sql.builders.gold_output import (
    GoldOutputParams,
    build_gold_output_sql,
)
from bq_entity_resolution.sql.builders.golden_record import (
    FieldStrategy,
    GoldenRecordParams,
    build_golden_record_cte,
)
from bq_entity_resolution.sql.builders.job_tracking import (
    JobDetail,
    RunComparisonParams,
    build_create_job_tracking_table_sql,
    build_insert_job_details_sql,
    build_run_comparison_sql,
    compute_sql_hash,
)
from bq_entity_resolution.sql.builders.monitoring import build_persist_sql_log_sql
from bq_entity_resolution.sql.builders.placeholder_tracking import (
    PlaceholderScanColumn,
    PlaceholderScanParams,
    build_create_placeholder_table_sql,
    build_placeholder_scan_sql,
)
from bq_entity_resolution.sql.builders.staging import StagingParams, build_staging_sql
from bq_entity_resolution.sql.builders.udf import build_jaro_winkler_udf_sql
from bq_entity_resolution.sql.builders.watermark import (
    build_create_checkpoint_table_sql,
    build_create_watermark_table_sql,
    build_read_watermark_sql,
    build_update_watermark_sql,
)

__all__ = [
    # Staging
    "build_staging_sql",
    "StagingParams",
    # Features
    "build_features_sql",
    "build_term_frequencies_sql",
    "FeatureParams",
    # Blocking
    "build_blocking_sql",
    "build_blocking_metrics_sql",
    "build_blocking_effectiveness_sql",
    "BlockingParams",
    "BlockingMetricsParams",
    "BlockingEffectivenessParams",
    "TierEffectivenessParams",
    # Comparison / Scoring
    "build_sum_scoring_sql",
    "build_fellegi_sunter_sql",
    "SumScoringParams",
    "FellegiSunterParams",
    # Clustering
    "build_cluster_assignment_sql",
    "build_cluster_quality_metrics_sql",
    "build_incremental_cluster_sql",
    "build_populate_canonical_index_sql",
    "ClusteringParams",
    "ClusterMetricsParams",
    "IncrementalClusteringParams",
    "PopulateCanonicalIndexParams",
    # Gold Output
    "build_gold_output_sql",
    "GoldOutputParams",
    "build_golden_record_cte",
    "GoldenRecordParams",
    "FieldStrategy",
    # EM / Parameter Estimation
    "build_em_estimation_sql",
    "build_estimate_from_labels_sql",
    "EMParams",
    "LabelEstimationParams",
    # Embeddings
    "build_embeddings_sql",
    "build_lsh_buckets_sql",
    "EmbeddingsParams",
    "LSHParams",
    # Active Learning
    "build_active_learning_sql",
    "build_ingest_labels_sql",
    "ActiveLearningParams",
    "IngestLabelsParams",
    # Watermark / Checkpoint
    "build_create_watermark_table_sql",
    "build_read_watermark_sql",
    "build_update_watermark_sql",
    "build_create_checkpoint_table_sql",
    # UDF
    "build_jaro_winkler_udf_sql",
    # Monitoring
    "build_persist_sql_log_sql",
    # Job Tracking
    "build_create_job_tracking_table_sql",
    "build_insert_job_details_sql",
    "build_run_comparison_sql",
    "compute_sql_hash",
    "JobDetail",
    "RunComparisonParams",
    # Placeholder Tracking
    "build_create_placeholder_table_sql",
    "build_placeholder_scan_sql",
    "PlaceholderScanColumn",
    "PlaceholderScanParams",
]

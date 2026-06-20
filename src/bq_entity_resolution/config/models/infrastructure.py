"""
Infrastructure configuration models.

Defines BigQuery project/environment settings, embeddings/LSH,
incremental processing, monitoring, and scale configuration.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = [
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
    "HealthProbeConfig",
    "DistributedLockConfig",
    "GracefulShutdownConfig",
    "DeploymentConfig",
]


# ---------------------------------------------------------------------------
# Project & environment
# ---------------------------------------------------------------------------

_VALID_BQ_PROJECT = re.compile(r'^[a-zA-Z0-9_-]+$')
_VALID_BQ_DATASET = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


class ProjectConfig(BaseModel):
    """BigQuery project and dataset routing."""

    name: str
    description: str = ""
    bq_project: str
    bq_dataset_bronze: str = "er_bronze"
    bq_dataset_silver: str = "er_silver"
    bq_dataset_gold: str = "er_gold"
    bq_location: str = "US"
    watermark_dataset: str = "er_meta"
    udf_dataset: str = "er_udfs"

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        if len(v) > 128:
            raise ValueError(
                f"pipeline name must be <= 128 characters, got {len(v)}"
            )
        return v

    @field_validator("bq_project")
    @classmethod
    def _validate_bq_project(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        # Allow env var placeholders
        if "${" in v:
            return v
        if not _VALID_BQ_PROJECT.match(v):
            raise ValueError(
                f"Invalid BigQuery project ID: {v!r}. "
                f"Must contain only letters, digits, underscores, and hyphens."
            )
        return v

    @field_validator(
        "bq_dataset_bronze", "bq_dataset_silver", "bq_dataset_gold",
        "watermark_dataset", "udf_dataset",
    )
    @classmethod
    def _validate_dataset_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        if "${" in v:
            return v  # Allow env var placeholders
        if not _VALID_BQ_DATASET.match(v):
            raise ValueError(
                f"Invalid BigQuery dataset name: {v!r}. "
                f"Must start with a letter or underscore, contain only "
                f"letters, digits, and underscores."
            )
        return v


# ---------------------------------------------------------------------------
# Embeddings & LSH
# ---------------------------------------------------------------------------

class LSHConfig(BaseModel):
    """Locality-Sensitive Hashing configuration for embedding-based blocking."""

    num_hash_tables: int = 20
    num_hash_functions_per_table: int = 8
    bucket_column_prefix: str = "lsh_bucket"
    projection_seed: int = 42

    @field_validator("num_hash_tables", "num_hash_functions_per_table")
    @classmethod
    def _positive_lsh_params(cls, v: int) -> int:
        if v < 1:
            raise ValueError("LSH parameters must be >= 1")
        return v


class EmbeddingConfig(BaseModel):
    """Embedding computation and storage configuration."""

    enabled: bool = False
    model: str = "text-embedding-004"
    source_columns: list[str] = Field(default_factory=list)
    concat_separator: str = " | "
    dimensions: int = 768
    batch_size: int = 5000
    lsh: LSHConfig = Field(default_factory=LSHConfig)

    @field_validator("dimensions", "batch_size")
    @classmethod
    def _positive_embedding_params(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Embedding parameters must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Incremental processing
# ---------------------------------------------------------------------------

class PartitionCursorConfig(BaseModel):
    """A partition-aware cursor dimension for scan optimization.

    When sources are partitioned by columns beyond the timestamp (e.g.
    state, policy_id, region), adding them as partition cursors generates
    AND predicates in the staging WHERE clause. BigQuery uses these for
    partition pruning, dramatically reducing bytes scanned.

    Example config::

        incremental:
          partition_cursors:
            - column: state
              strategy: range      # >= last processed value
            - column: policy_year
              strategy: equality   # = current year

    This generates::

        WHERE updated_at > WATERMARK_TS
          AND state >= 'last_processed_state'
          AND policy_year = 2024
    """

    column: str
    strategy: Literal["range", "equality", "in_list"] = "range"
    value: str | int | float | None = None  # Static value for equality strategy

    @field_validator("column")
    @classmethod
    def _validate_column_identifier(cls, v: str) -> str:
        from bq_entity_resolution.sql.utils import validate_identifier
        validate_identifier(v, context="partition cursor column")
        return v

    @model_validator(mode="after")
    def _equality_requires_value(self) -> Self:
        if self.strategy == "equality" and self.value is None:
            import warnings
            warnings.warn(
                f"PartitionCursorConfig for column '{self.column}' uses "
                f"strategy='equality' but has no value set. "
                f"This cursor will have no effect without a value.",
                UserWarning,
                stacklevel=2,
            )
        return self


class HashCursorConfig(BaseModel):
    """Hash-based virtual cursor for tables without a natural secondary column.

    When source tables lack a secondary column suitable for ordered cursor
    delineation (e.g., no policy_id or sequence number), a hash cursor
    generates a deterministic virtual partition column:

        FARM_FINGERPRINT(unique_key) MOD 1000 AS _hash_partition

    This creates a numeric dimension (0-999) that, combined with the
    primary timestamp cursor, enables clean batch boundaries.

    Cost note: hash cursors add a FARM_FINGERPRINT computation per row.
    Prefer natural columns (cheaper) when they exist.

    Example config::

        incremental:
          hash_cursor:
            column: policy_id
            modulus: 1000
            alias: _hash_partition
    """

    column: str = "entity_uid"
    modulus: int = 1000
    alias: str = "_hash_partition"

    @field_validator("column", "alias")
    @classmethod
    def _validate_column_identifier(cls, v: str) -> str:
        from bq_entity_resolution.sql.utils import validate_identifier
        validate_identifier(v, context="hash cursor column")
        return v

    @field_validator("modulus")
    @classmethod
    def _positive_modulus(cls, v: int) -> int:
        if v < 1:
            raise ValueError("modulus must be >= 1 (MOD 0 is undefined)")
        return v


class IncrementalConfig(BaseModel):
    """Incremental processing and watermark configuration.

    Supports two cursor modes for composite watermarks:

    - ``independent`` (legacy): Each cursor column is compared independently
      with OR logic. Simple but can re-process or skip records when cursor
      dimensions are not monotonically aligned.

    - ``ordered`` (recommended): Cursor columns are compared as an ordered
      tuple: ``(col1, col2) > (wm1, wm2)``. This expands to::

          col1 > wm1 OR (col1 = wm1 AND col2 > wm2)

      This ensures no records are skipped or re-processed, even when
      a single primary cursor value spans millions of records.

    Drain mode auto-loops through batches until all unprocessed records
    are consumed, advancing the watermark after each successful batch.
    """

    enabled: bool = True
    grace_period_hours: int = 48
    cursor_columns: list[str] = Field(default_factory=lambda: ["updated_at"])
    cursor_mode: Literal["independent", "ordered"] = "ordered"
    partition_cursors: list[PartitionCursorConfig] = Field(default_factory=list)
    hash_cursor: HashCursorConfig | None = None
    batch_size: int = 2_000_000
    full_refresh_on_schema_change: bool = True
    drain_mode: bool = False
    drain_max_iterations: int = 100

    @field_validator("cursor_columns")
    @classmethod
    def _non_empty_cursor_columns(cls, v: list[str]) -> list[str]:
        from bq_entity_resolution.sql.utils import validate_identifier
        if not v:
            raise ValueError(
                "cursor_columns must not be empty when incremental processing is enabled"
            )
        for col in v:
            validate_identifier(col, context="cursor column")
        return v

    @field_validator("grace_period_hours")
    @classmethod
    def _non_negative_grace(cls, v: int) -> int:
        if v < 0:
            raise ValueError("grace_period_hours must be >= 0")
        return v

    @field_validator("batch_size")
    @classmethod
    def _positive_batch_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("batch_size must be >= 1")
        if v > 100_000_000:
            raise ValueError(
                f"batch_size must be <= 100,000,000, got {v:,}"
            )
        return v

    @field_validator("drain_max_iterations")
    @classmethod
    def _positive_drain_max(cls, v: int) -> int:
        if v < 1:
            raise ValueError("drain_max_iterations must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

class MetricsConfig(BaseModel):
    """Pipeline metrics collection configuration."""

    enabled: bool = True
    destination: Literal["bigquery", "stdout"] = "bigquery"


class ProfilingConfig(BaseModel):
    """Data quality profiling configuration."""

    enabled: bool = False
    sample_rate: float = 0.01

    @field_validator("sample_rate")
    @classmethod
    def _valid_sample_rate(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            raise ValueError("sample_rate must be in (0.0, 1.0]")
        return v


class BlockingMetricsConfig(BaseModel):
    """Blocking evaluation metrics to assess blocking strategy quality."""

    enabled: bool = False
    persist_to_table: bool = False


class ClusterQualityConfig(BaseModel):
    """Cluster quality metrics and alerts.

    Monitors cluster health to catch false positives that merge
    unrelated entities via transitivity.
    """

    enabled: bool = False
    persist_to_table: bool = False
    alert_max_cluster_size: int = 100
    alert_singleton_ratio: float = 0.95
    abort_on_explosion: bool = False  # Hard abort if max cluster exceeds threshold

    @field_validator("alert_max_cluster_size")
    @classmethod
    def _positive_cluster_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("alert_max_cluster_size must be >= 1")
        return v

    @field_validator("alert_singleton_ratio")
    @classmethod
    def _valid_ratio(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("alert_singleton_ratio must be in [0.0, 1.0]")
        return v


class JobTrackingConfig(BaseModel):
    """Per-query BigQuery job metadata tracking.

    When enabled, persists job details (bytes_billed, slot_milliseconds,
    duration, job_id) for every query executed by the pipeline to a
    ``pipeline_job_details`` table in the metadata dataset.

    Use for cost monitoring, performance analysis, and capacity planning.

    Cost thresholds provide per-run cumulative budget guards:
    - ``cost_alert_threshold_bytes``: log warning when exceeded
    - ``cost_abort_threshold_bytes``: abort pipeline when exceeded
    """

    enabled: bool = False
    cost_alert_threshold_bytes: int | None = None
    cost_abort_threshold_bytes: int | None = None

    @field_validator("cost_alert_threshold_bytes", "cost_abort_threshold_bytes")
    @classmethod
    def _positive_cost_thresholds(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("cost threshold must be >= 1 if set")
        return v


class PlaceholderTrackingConfig(BaseModel):
    """Placeholder value detection logging.

    When enabled, scans featured data for suspected placeholder values
    and logs them to a ``placeholder_detection_log`` table for data
    quality monitoring over time.

    ``min_count`` filters out rare values — only values appearing at
    least this many times are reported.
    """

    enabled: bool = False
    min_count: int = 2

    @field_validator("min_count")
    @classmethod
    def _positive_min_count(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_count must be >= 1")
        return v


class MonitoringConfig(BaseModel):
    """Observability configuration."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    profiling: ProfilingConfig = Field(default_factory=ProfilingConfig)
    blocking_metrics: BlockingMetricsConfig = Field(default_factory=BlockingMetricsConfig)
    cluster_quality: ClusterQualityConfig = Field(default_factory=ClusterQualityConfig)
    job_tracking: JobTrackingConfig = Field(default_factory=JobTrackingConfig)
    placeholder_tracking: PlaceholderTrackingConfig = Field(
        default_factory=PlaceholderTrackingConfig
    )
    persist_sql_log: bool = False  # Write sql_log to BQ table after run
    min_data_quality_score: int = 0  # 0 = disabled; 1-100 = gate threshold

    @field_validator("min_data_quality_score")
    @classmethod
    def _valid_quality_score(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError("min_data_quality_score must be in [0, 100]")
        return v


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------

class ScaleConfig(BaseModel):
    """Scale optimizations for high-volume processing (5-10M+ records/day).

    All fields are opt-in (off by default) to preserve backwards compatibility.

    **Partitioning** controls BigQuery PARTITION BY on generated tables.
    Good partition columns: date/timestamp columns with daily/monthly granularity.
    BigQuery limit: max 1 partition column per table, 4000 partitions.

    **Clustering** controls BigQuery CLUSTER BY on generated tables.
    Up to 4 columns per table. Put highest-cardinality filter columns first.

    Example config::

        scale:
          staging_partition_by: "DATE(source_updated_at)"
          staging_clustering: [entity_uid, source_name]
          candidates_clustering: [l_entity_uid]
          matches_partition_by: "DATE(matched_at)"
    """

    max_bytes_billed: int | None = None  # Per-query safety cap (on-demand pricing only)

    @field_validator("max_bytes_billed")
    @classmethod
    def _positive_max_bytes(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("max_bytes_billed must be >= 1 if set")
        return v

    # Staging tables
    staging_partition_by: str | None = None  # e.g. "DATE(source_updated_at)"
    staging_clustering: list[str] = Field(
        default_factory=lambda: ["entity_uid"]
    )

    # Featured tables
    featured_partition_by: str | None = None
    featured_table_clustering: list[str] = Field(default_factory=list)

    # Candidate pair tables
    candidates_partition_by: str | None = None
    candidates_clustering: list[str] = Field(
        default_factory=lambda: ["l_entity_uid"]
    )

    # Match result tables
    matches_partition_by: str | None = None  # e.g. "DATE(matched_at)"
    matches_clustering: list[str] = Field(
        default_factory=lambda: ["l_entity_uid", "r_entity_uid"]
    )

    # Canonical index
    canonical_index_partition_by: str | None = None
    canonical_index_clustering: list[str] = Field(
        default_factory=lambda: ["entity_uid"]
    )

    @field_validator(
        "staging_partition_by", "featured_partition_by", "candidates_partition_by",
        "matches_partition_by", "canonical_index_partition_by",
    )
    @classmethod
    def _validate_partition_by_safe(cls, v: str | None) -> str | None:
        if v is not None:
            import re
            _pattern = re.compile(
                r";\s*|--\s|/\*|\bDROP\b|\bALTER\b|\bCREATE\b|\bTRUNCATE\b|\bGRANT\b|\bREVOKE\b",
                re.IGNORECASE,
            )
            if _pattern.search(v):
                raise ValueError(
                    "partition_by expression contains disallowed SQL pattern "
                    "(semicolons, comments, or DDL keywords)"
                )
        return v

    checkpoint_enabled: bool = False
    table_expiration_days: int | None = None  # Optional TTL for generated tables

    @field_validator("table_expiration_days")
    @classmethod
    def _positive_expiration(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("table_expiration_days must be >= 1 if set")
        return v

    @field_validator(
        "staging_clustering", "featured_table_clustering", "candidates_clustering",
        "matches_clustering", "canonical_index_clustering",
    )
    @classmethod
    def _max_four_clustering_columns(cls, v: list[str]) -> list[str]:
        from bq_entity_resolution.sql.utils import validate_identifier
        if len(v) > 4:
            raise ValueError(
                f"BigQuery allows max 4 clustering columns, got {len(v)}"
            )
        for col in v:
            validate_identifier(col, context="clustering column")
        return v


# ---------------------------------------------------------------------------
# Execution control
# ---------------------------------------------------------------------------

class ExecutionConfig(BaseModel):
    """Pipeline execution control.

    ``allow_udfs`` — When False, the pipeline rejects comparison methods
    and feature functions that require BigQuery JavaScript UDFs (e.g.
    ``jaro_winkler``, ``metaphone``). Some BigQuery environments (shared
    tenants, CMEK-restricted projects, certain org policies) prohibit
    JS UDFs. Set this to False and use native alternatives like
    ``levenshtein_normalized`` instead.

    ``skip_stages`` — Stage names to exclude from the pipeline DAG.
    Equivalent to the Python API ``Pipeline(config, exclude_stages={...})``
    but configurable in YAML. Use with care: downstream stages that
    depend on a skipped stage's outputs will fail validation.

    ``query_timeout_seconds`` — Default timeout for each BigQuery query.
    Individual stages may run longer; this prevents runaway queries.
    Set to 0 to disable timeout entirely.

    ``max_cost_bytes`` — *Optional* pipeline-level cumulative cost ceiling
    in bytes billed. The pipeline aborts if total bytes billed across all
    queries exceeds this value. Disabled (``None``) by default.

    **Note:** Cost controls (``max_cost_bytes`` and ``scale.max_bytes_billed``)
    are only relevant for on-demand pricing. If you use flat-rate reservations
    or edition-based pricing with dedicated slots, leave these unset — there
    is no per-byte charge and the controls would just add overhead.

    Example YAML::

        execution:
          allow_udfs: false
          query_timeout_seconds: 900
          max_cost_bytes: 50000000000  # 50 GB pipeline total (on-demand only)
          skip_stages:
            - cluster_quality
            - term_frequencies
    """

    allow_udfs: bool = True
    skip_stages: list[str] = Field(default_factory=list)
    query_timeout_seconds: int = 600
    max_retries: int = 3
    retry_delay_seconds: int = 5
    max_cost_bytes: int | None = None  # Pipeline-level cost ceiling (on-demand pricing only)

    @field_validator("max_cost_bytes")
    @classmethod
    def _positive_max_cost(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("max_cost_bytes must be >= 1 if set")
        return v

    @field_validator("query_timeout_seconds")
    @classmethod
    def _non_negative_timeout(cls, v: int) -> int:
        if v < 0:
            raise ValueError("query_timeout_seconds must be >= 0")
        return v

    @field_validator("max_retries")
    @classmethod
    def _non_negative_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retries must be >= 0")
        return v

    @field_validator("retry_delay_seconds")
    @classmethod
    def _positive_retry_delay(cls, v: int) -> int:
        if v < 1:
            raise ValueError("retry_delay_seconds must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Deployment / K8s
# ---------------------------------------------------------------------------

class HealthProbeConfig(BaseModel):
    """File-based health probe for Kubernetes liveness/readiness checks.

    When enabled, the pipeline writes a heartbeat file at ``path`` on
    each stage completion. Configure a K8s ``exec`` liveness probe::

        livenessProbe:
          exec:
            command: [test, -f, /tmp/pipeline_healthy]
          initialDelaySeconds: 30
          periodSeconds: 10

    Example YAML::

        deployment:
          health_probe:
            enabled: true
            path: /tmp/pipeline_healthy
    """

    enabled: bool = False
    path: str = "/tmp/pipeline_healthy"


class DistributedLockConfig(BaseModel):
    """Distributed locking for concurrent pipeline safety.

    Prevents multiple K8s pods from running the same pipeline config
    simultaneously. Uses a BigQuery metadata table as a distributed lock.

    The lock is acquired at pipeline start and released on completion.
    If a pod dies without releasing, the TTL ensures eventual expiry.

    Example YAML::

        deployment:
          distributed_lock:
            enabled: true
            lock_table: "er_meta.pipeline_locks"
            ttl_minutes: 30
    """

    enabled: bool = False
    lock_table: str = "pipeline_locks"  # Table name within watermark_dataset
    ttl_minutes: int = 30
    retry_seconds: int = 10
    max_wait_seconds: int = 300
    fencing_enabled: bool = True  # Verify fencing token before watermark writes

    @field_validator("ttl_minutes")
    @classmethod
    def _positive_ttl(cls, v: int) -> int:
        if v < 1:
            raise ValueError("ttl_minutes must be >= 1")
        return v

    @field_validator("retry_seconds")
    @classmethod
    def _positive_retry(cls, v: int) -> int:
        if v < 1:
            raise ValueError("retry_seconds must be >= 1")
        return v

    @field_validator("max_wait_seconds")
    @classmethod
    def _positive_max_wait(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_wait_seconds must be >= 1")
        return v


class GracefulShutdownConfig(BaseModel):
    """Graceful shutdown configuration for SIGTERM handling.

    When enabled, the pipeline registers SIGTERM/SIGINT handlers that:
    1. Cancel in-flight BigQuery jobs
    2. Write the health probe as unhealthy
    3. Exit cleanly

    ``grace_period_seconds`` should be less than K8s
    ``terminationGracePeriodSeconds`` (default 30s) minus a safety
    margin for cleanup.

    Example YAML::

        deployment:
          graceful_shutdown:
            enabled: true
            grace_period_seconds: 25
    """

    enabled: bool = True
    grace_period_seconds: int = 25
    cancel_running_jobs: bool = True

    @field_validator("grace_period_seconds")
    @classmethod
    def _non_negative_grace(cls, v: int) -> int:
        if v < 0:
            raise ValueError("grace_period_seconds must be >= 0")
        return v


class DeploymentConfig(BaseModel):
    """Kubernetes and production deployment settings.

    Groups all deployment-related configuration under a single
    ``deployment:`` YAML key for clean separation from pipeline logic.

    Example YAML::

        deployment:
          health_probe:
            enabled: true
            path: /tmp/pipeline_healthy
          distributed_lock:
            enabled: true
            ttl_minutes: 30
          graceful_shutdown:
            enabled: true
            grace_period_seconds: 25
    """

    health_probe: HealthProbeConfig = Field(default_factory=HealthProbeConfig)
    distributed_lock: DistributedLockConfig = Field(default_factory=DistributedLockConfig)
    graceful_shutdown: GracefulShutdownConfig = Field(default_factory=GracefulShutdownConfig)

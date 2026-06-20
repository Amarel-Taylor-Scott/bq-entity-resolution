"""Centralized column naming standard for the entity resolution pipeline.

All system-generated column names are defined here as constants.
Import from this module instead of using string literals in SQL builders.

Column Categories and Prefixes
------------------------------
ENTITY IDENTITY (no prefix)
    Core pipeline identifiers: entity_uid, cluster_id, resolved_entity_id

SOURCE METADATA (source_ prefix)
    Describes data origin: source_name, source_updated_at

PIPELINE METADATA (pipeline_ prefix)
    Pipeline operation tracking: pipeline_loaded_at, pipeline_run_id

FINGERPRINT / HASH (fp_ prefix) — INT64 columns, optimal for JOINs
    FARM_FINGERPRINT or hash-based blocking keys: fp_policy_number, fp_lsh_bucket_0
    These are INT64 values produced by FARM_FINGERPRINT(). Equi-joins on
    fp_ columns are ~3-5x faster than on equivalent STRING columns because
    BQ compares 8 fixed bytes instead of variable-length byte arrays.
    Use fp_ columns as blocking keys wherever possible.

MATCH SCORING (match_ prefix)
    Matching step outputs: match_total_score, match_confidence, match_tier_name

BQML PREDICTED (bqml_predicted_ prefix)
    BigQuery ML model predictions: bqml_predicted_embedding

BLOCKING KEYS (bk_ prefix) — STRING or INT64, depends on the function
    Non-hash blocking keys: bk_first_soundex, bk_dob_year
    Some bk_ columns are STRING (soundex, email_domain) and some are INT64
    (dob_year, year_of_date). For large-scale performance, consider
    upgrading STRING bk_ keys to fp_ keys via FARM_FINGERPRINT wrapping.

TERM FREQUENCY (term_frequency_ prefix)
    TF statistics: term_frequency_column, term_frequency_ratio

FEATURE ({column}_{transform} pattern)
    User-defined derived features: first_name_cleaned, phone_standardized
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Prefix constants (for validation and documentation)
# ---------------------------------------------------------------------------

PREFIX_SOURCE = "source_"
PREFIX_PIPELINE = "pipeline_"
PREFIX_FINGERPRINT = "fp_"
PREFIX_MATCH = "match_"
PREFIX_BQML_PREDICTED = "bqml_predicted_"
PREFIX_BLOCKING_KEY = "bk_"
PREFIX_TERM_FREQUENCY = "term_frequency_"

# ---------------------------------------------------------------------------
# Entity Identity (no prefix — reserved names)
# ---------------------------------------------------------------------------

# INT64 — FARM_FINGERPRINT(CONCAT(source_name, '||', unique_key)). The universal
# join key for the entire pipeline. All blocking, matching, and clustering JOINs
# use this column. INT64 enables hash-join optimization throughout.
ENTITY_UID = "entity_uid"
# INT64 — initialized from entity_uid, propagated via MIN() in clustering loop.
# All clustering JOINs and aggregations operate on this INT64 column.
CLUSTER_ID = "cluster_id"
# INT64 — equal to cluster_id. Kept as INT64 for efficient JOINs; format as
# string with a prefix (e.g. "ENT_" || CAST(...)) only at presentation/export time.
RESOLVED_ENTITY_ID = "resolved_entity_id"
CANONICAL_ENTITY_UID = "canonical_entity_uid"
IS_CANONICAL = "is_canonical"

# ---------------------------------------------------------------------------
# Source Metadata (source_ prefix)
# ---------------------------------------------------------------------------

SOURCE_NAME = "source_name"
SOURCE_UPDATED_AT = "source_updated_at"

# ---------------------------------------------------------------------------
# Pipeline Metadata (pipeline_ prefix)
# ---------------------------------------------------------------------------

PIPELINE_LOADED_AT = "pipeline_loaded_at"
PIPELINE_RUN_ID = "pipeline_run_id"

# ---------------------------------------------------------------------------
# Blocking (pair columns)
# ---------------------------------------------------------------------------

# INT64 pair columns — candidate pairs and match results use these for JOINs.
# Both are entity_uid values, so all pair-level operations are INT64.
LEFT_ENTITY_UID = "left_entity_uid"
RIGHT_ENTITY_UID = "right_entity_uid"
BLOCKING_PATH = "blocking_path"

# ---------------------------------------------------------------------------
# Match Scoring (match_ prefix)
# ---------------------------------------------------------------------------

MATCH_TOTAL_SCORE = "match_total_score"
MATCH_CONFIDENCE = "match_confidence"
MATCH_TIER_NAME = "match_tier_name"
MATCH_TIER_PRIORITY = "match_tier_priority"
MATCH_DETAIL = "match_detail"
MATCHED_AT = "matched_at"
MATCH_UNCERTAINTY = "match_uncertainty"
MATCH_BAND = "match_band"
IS_AUTO_MATCH = "is_auto_match"
IS_HUB_NODE = "is_hub_node"

# ---------------------------------------------------------------------------
# Gold Output
# ---------------------------------------------------------------------------

CANONICAL_SCORE = "canonical_score"
COMPLETENESS_SCORE = "completeness_score"
SOURCE_RANK = "source_rank"
MATCHED_BY_TIER = "matched_by_tier"

# ---------------------------------------------------------------------------
# BQML Predicted (bqml_predicted_ prefix)
# ---------------------------------------------------------------------------

BQML_PREDICTED_EMBEDDING = "bqml_predicted_embedding"
EMBEDDING_INPUT_TEXT = "embedding_input_text"

# ---------------------------------------------------------------------------
# Term Frequency (term_frequency_ prefix)
# ---------------------------------------------------------------------------

TERM_FREQUENCY_COLUMN = "term_frequency_column"
TERM_FREQUENCY_VALUE = "term_frequency_value"
TERM_FREQUENCY_COUNT = "term_frequency_count"
TERM_FREQUENCY_RATIO = "term_frequency_ratio"

# ---------------------------------------------------------------------------
# Active Learning
# ---------------------------------------------------------------------------

HUMAN_LABEL = "human_label"
IS_MATCH = "is_match"
LABEL_SOURCE = "label_source"
QUEUED_AT = "queued_at"
INGESTED_AT = "ingested_at"

# ---------------------------------------------------------------------------
# EM Estimation
# ---------------------------------------------------------------------------

EM_COMPARISON_NAME = "comparison_name"
EM_LEVEL_LABEL = "level_label"
EM_M_PROBABILITY = "m_probability"
EM_U_PROBABILITY = "u_probability"
EM_MATCH_RATE = "match_rate"
EM_MATCH_WEIGHT = "match_weight"
EM_MATCH_PRIOR = "match_prior"
EM_ITERATIONS = "em_iterations"
EM_FINAL_LOG_LIKELIHOOD = "final_log_likelihood"

# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------

WATERMARK_SOURCE_NAME = "source_name"
WATERMARK_CURSOR_COLUMN = "cursor_column"
WATERMARK_CURSOR_VALUE = "cursor_value"
WATERMARK_CURSOR_TYPE = "cursor_type"
WATERMARK_UPDATED_AT = "updated_at"
WATERMARK_RUN_ID = "run_id"
WATERMARK_IS_CURRENT = "is_current"

# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

CHECKPOINT_RUN_ID = "run_id"
CHECKPOINT_STAGE_NAME = "stage_name"
CHECKPOINT_COMPLETED_AT = "completed_at"
CHECKPOINT_STATUS = "status"

# ---------------------------------------------------------------------------
# Monitoring / Audit
# ---------------------------------------------------------------------------

AUDIT_RUN_ID = "run_id"
AUDIT_STAGE = "stage"
AUDIT_STEP = "step"
AUDIT_SQL_TEXT = "sql_text"
AUDIT_EXECUTED_AT = "executed_at"

# ---------------------------------------------------------------------------
# Clustering (internal CTE columns)
# ---------------------------------------------------------------------------

CLUSTER_UID1 = "uid1"
CLUSTER_CID1 = "cid1"
CLUSTER_UID2 = "uid2"
CLUSTER_CID2 = "cid2"
CLUSTER_MIN_NEIGHBOR = "min_neighbor"

# Cluster quality metrics
CLUSTER_METRIC_COUNT = "cluster_count"
CLUSTER_METRIC_SINGLETON_COUNT = "singleton_count"
CLUSTER_METRIC_SINGLETON_RATIO = "singleton_ratio"
CLUSTER_METRIC_MAX_SIZE = "max_cluster_size"
CLUSTER_METRIC_AVG_SIZE = "avg_cluster_size"
CLUSTER_METRIC_MEDIAN_SIZE = "median_cluster_size"
CLUSTER_METRIC_AVG_SOURCE_DIVERSITY = "avg_source_diversity"
CLUSTER_METRIC_AVG_CONFIDENCE = "avg_match_confidence"
CLUSTER_METRIC_MIN_CONFIDENCE = "min_match_confidence"
CLUSTER_METRIC_COMPUTED_AT = "computed_at"

# Blocking metrics
BLOCKING_METRIC_TIER_NAME = "tier_name"
BLOCKING_METRIC_TOTAL_RECORDS = "total_records"
BLOCKING_METRIC_CANDIDATE_PAIRS = "candidate_pairs"
BLOCKING_METRIC_MATCHED_PAIRS = "matched_pairs"
BLOCKING_METRIC_PRECISION = "precision"
BLOCKING_METRIC_REDUCTION_RATIO = "reduction_ratio"
BLOCKING_METRIC_COMPUTED_AT = "computed_at"

# ---------------------------------------------------------------------------
# Dynamic column name constructors
# ---------------------------------------------------------------------------


def match_score_column(comparison_name: str) -> str:
    """Column name for an individual comparison score.

    Example: match_score_column("first_name_jw") -> "match_score_first_name_jw"
    """
    return f"{PREFIX_MATCH}score_{comparison_name}"


def match_log_weight_column(comparison_name: str) -> str:
    """Column name for a Fellegi-Sunter log weight.

    Example: match_log_weight_column("email_exact") -> "match_log_weight_email_exact"
    """
    return f"{PREFIX_MATCH}log_weight_{comparison_name}"


def fp_lsh_bucket_column(index: int) -> str:
    """Column name for an LSH bucket hash.

    Example: fp_lsh_bucket_column(0) -> "fp_lsh_bucket_0"
    """
    return f"{PREFIX_FINGERPRINT}lsh_bucket_{index}"


def blocking_key_column(suffix: str) -> str:
    """Column name for a non-fingerprint blocking key.

    Example: blocking_key_column("first_soundex") -> "bk_first_soundex"
    """
    return f"{PREFIX_BLOCKING_KEY}{suffix}"


def fingerprint_column(suffix: str) -> str:
    """Column name for a fingerprint-based blocking key.

    Example: fingerprint_column("policy_number") -> "fp_policy_number"
    """
    return f"{PREFIX_FINGERPRINT}{suffix}"


# ---------------------------------------------------------------------------
# Job Tracking
# ---------------------------------------------------------------------------

JOB_TRACKING_RUN_ID = "run_id"
JOB_TRACKING_STAGE_NAME = "stage_name"
JOB_TRACKING_QUERY_INDEX = "query_index"
JOB_TRACKING_JOB_ID = "job_id"
JOB_TRACKING_BYTES_BILLED = "bytes_billed"
JOB_TRACKING_TOTAL_BYTES_PROCESSED = "total_bytes_processed"
JOB_TRACKING_SLOT_MILLISECONDS = "slot_milliseconds"
JOB_TRACKING_DURATION_SECONDS = "duration_seconds"
JOB_TRACKING_ROWS_AFFECTED = "rows_affected"
JOB_TRACKING_STARTED_AT = "started_at"
JOB_TRACKING_SQL_HASH = "sql_hash"

# ---------------------------------------------------------------------------
# Placeholder Tracking
# ---------------------------------------------------------------------------

PLACEHOLDER_RUN_ID = "run_id"
PLACEHOLDER_SOURCE_NAME = "source_name"
PLACEHOLDER_COLUMN_NAME = "column_name"
PLACEHOLDER_VALUE = "placeholder_value"
PLACEHOLDER_MATCH_COUNT = "match_count"
PLACEHOLDER_PATTERN_TYPE = "pattern_type"
PLACEHOLDER_DETECTED_AT = "detected_at"

"""
Centralized table naming for the pipeline.

All BigQuery table name patterns are defined here to avoid scattering
string literals across engines. Import from this module instead of
constructing table names with f-strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bq_entity_resolution.config.schema import PipelineConfig


def staged_table(config: PipelineConfig, source_name: str) -> str:
    """Bronze layer staged table for a source."""
    return config.fq_table("bq_dataset_bronze", f"staged_{source_name}")


def featured_table(config: PipelineConfig) -> str:
    """Silver layer featured (enriched) table."""
    return config.fq_table("bq_dataset_silver", "featured")


def candidates_table(config: PipelineConfig, tier_name: str) -> str:
    """Silver layer candidate pairs table for a tier."""
    return config.fq_table("bq_dataset_silver", f"candidates_{tier_name}")


def matches_table(config: PipelineConfig, tier_name: str) -> str:
    """Silver layer matches table for a tier."""
    return config.fq_table("bq_dataset_silver", f"matches_{tier_name}")


def all_matches_table(config: PipelineConfig) -> str:
    """Silver layer accumulated matches table."""
    return config.fq_table("bq_dataset_silver", "all_matched_pairs")


def cluster_table(config: PipelineConfig) -> str:
    """Silver layer entity cluster assignments."""
    return config.fq_table("bq_dataset_silver", "entity_clusters")


def resolved_table(config: PipelineConfig) -> str:
    """Gold layer resolved entities output."""
    return config.fq_table("bq_dataset_gold", "resolved_entities")


def canonical_index_table(config: PipelineConfig) -> str:
    """Gold layer canonical entity index."""
    return config.fq_table("bq_dataset_gold", "canonical_index")


def embeddings_table(config: PipelineConfig) -> str:
    """Silver layer entity embeddings."""
    return config.fq_table("bq_dataset_silver", "entity_embeddings")


def lsh_buckets_table(config: PipelineConfig) -> str:
    """Silver layer LSH bucket assignments."""
    return config.fq_table("bq_dataset_silver", "lsh_buckets")


def udf_dataset(config: PipelineConfig) -> str:
    """Fully-qualified UDF dataset reference."""
    p = config.project
    return f"{p.bq_project}.{p.udf_dataset}"


def parameters_table(config: PipelineConfig, tier_name: str) -> str:
    """Silver layer estimated Fellegi-Sunter parameters for a tier."""
    return config.fq_table("bq_dataset_silver", f"fs_parameters_{tier_name}")


def review_queue_table(config: PipelineConfig, tier_name: str) -> str:
    """Silver layer active learning review queue for a tier."""
    return config.fq_table("bq_dataset_silver", f"al_review_queue_{tier_name}")


def labels_table(config: PipelineConfig) -> str:
    """Silver layer human-provided labels table."""
    return config.fq_table("bq_dataset_silver", "al_labels")


def term_frequency_table(config: PipelineConfig) -> str:
    """Silver layer term frequency statistics table."""
    return config.fq_table("bq_dataset_silver", "term_frequencies")


def sql_audit_table(config: PipelineConfig) -> str:
    """Meta layer pipeline SQL audit trail table."""
    p = config.project
    return f"{p.bq_project}.{p.watermark_dataset}.pipeline_sql_audit"


def checkpoint_table(config: PipelineConfig) -> str:
    """Meta layer pipeline checkpoint table."""
    p = config.project
    return f"{p.bq_project}.{p.watermark_dataset}.pipeline_checkpoints"


def job_tracking_table(config: PipelineConfig) -> str:
    """Meta layer pipeline job details tracking table."""
    p = config.project
    return f"{p.bq_project}.{p.watermark_dataset}.pipeline_job_details"


def placeholder_detection_table(config: PipelineConfig) -> str:
    """Meta layer placeholder detection log table."""
    p = config.project
    return f"{p.bq_project}.{p.watermark_dataset}.placeholder_detection_log"

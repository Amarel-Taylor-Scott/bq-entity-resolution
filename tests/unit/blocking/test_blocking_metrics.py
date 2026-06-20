"""Tests for blocking evaluation metrics."""

from bq_entity_resolution.config.schema import BlockingMetricsConfig
from bq_entity_resolution.sql.builders.blocking import (
    BlockingMetricsParams,
    build_blocking_metrics_sql,
)


def test_blocking_metrics_config_defaults():
    """Default blocking metrics config is disabled."""
    bm = BlockingMetricsConfig()
    assert not bm.enabled
    assert not bm.persist_to_table


def test_blocking_metrics_sql_generates():
    """Blocking metrics SQL renders successfully."""
    params = BlockingMetricsParams(
        candidates_table="proj.silver.candidates_exact",
        matches_table="proj.silver.matches_exact",
        source_table="proj.silver.featured",
        tier_name="exact",
    )
    sql = build_blocking_metrics_sql(params).render()
    assert "candidate_pairs" in sql
    assert "matched_pairs" in sql
    assert "precision" in sql
    assert "reduction_ratio" in sql
    assert "exact" in sql


def test_blocking_metrics_references_correct_tables():
    """Blocking metrics SQL references candidates and matches tables."""
    params = BlockingMetricsParams(
        candidates_table="proj.silver.candidates_fuzzy",
        matches_table="proj.silver.matches_fuzzy",
        source_table="proj.silver.featured",
        tier_name="fuzzy",
    )
    sql = build_blocking_metrics_sql(params).render()
    assert "candidates_fuzzy" in sql
    assert "matches_fuzzy" in sql


def test_blocking_metrics_includes_tier_name():
    """Metrics output includes the tier name."""
    params = BlockingMetricsParams(
        candidates_table="proj.silver.candidates_exact",
        matches_table="proj.silver.matches_exact",
        source_table="proj.silver.featured",
        tier_name="exact",
    )
    sql = build_blocking_metrics_sql(params).render()
    assert "'exact'" in sql


def test_blocking_metrics_includes_timestamp():
    """Metrics output includes a computed_at timestamp."""
    params = BlockingMetricsParams(
        candidates_table="proj.silver.candidates_exact",
        matches_table="proj.silver.matches_exact",
        source_table="proj.silver.featured",
        tier_name="exact",
    )
    sql = build_blocking_metrics_sql(params).render()
    assert "computed_at" in sql


def test_monitoring_config_includes_blocking_metrics(sample_config):
    """MonitoringConfig has blocking_metrics field."""
    assert hasattr(sample_config.monitoring, "blocking_metrics")
    assert not sample_config.monitoring.blocking_metrics.enabled

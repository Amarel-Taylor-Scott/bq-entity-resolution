"""Tests for the clustering SQL builder."""

from bq_entity_resolution.sql.builders.clustering import (
    ClusteringParams,
    ClusterMetricsParams,
    build_cluster_assignment_sql,
    build_cluster_quality_metrics_sql,
)


def test_cluster_assignment_basic():
    """Cluster assignment generates BQ scripting with WHILE loop."""
    params = ClusteringParams(
        all_matches_table="proj.ds.all_matches",
        cluster_table="proj.ds.clusters",
        source_table="proj.ds.featured",
        max_iterations=20,
    )
    expr = build_cluster_assignment_sql(params)
    sql = expr.render()

    assert "DECLARE iteration INT64 DEFAULT 0" in sql
    assert "DECLARE rows_updated INT64 DEFAULT 1" in sql
    assert "CREATE OR REPLACE TABLE" in sql
    assert "entity_uid AS cluster_id" in sql
    assert "WHILE rows_updated > 0 AND iteration < 20 DO" in sql
    assert "_edge_clusters" in sql
    assert "_new_clusters" in sql
    assert "LEAST(" in sql
    assert "END WHILE" in sql


def test_cluster_assignment_max_iterations():
    """Custom max iterations."""
    params = ClusteringParams(
        all_matches_table="p.d.matches",
        cluster_table="p.d.clusters",
        source_table="p.d.source",
        max_iterations=50,
    )
    expr = build_cluster_assignment_sql(params)
    sql = expr.render()

    assert "iteration < 50" in sql


def test_cluster_assignment_initializes_singletons():
    """All entities start as singleton clusters."""
    params = ClusteringParams(
        all_matches_table="p.d.matches",
        cluster_table="p.d.clusters",
        source_table="p.d.source",
    )
    expr = build_cluster_assignment_sql(params)
    sql = expr.render()

    assert "SELECT DISTINCT entity_uid, entity_uid AS cluster_id" in sql


def test_cluster_quality_metrics():
    """Quality metrics generates correct aggregations."""
    params = ClusterMetricsParams(
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
    )
    expr = build_cluster_quality_metrics_sql(params)
    sql = expr.render()

    assert "cluster_count" in sql
    assert "singleton_count" in sql
    assert "singleton_ratio" in sql
    assert "max_cluster_size" in sql
    assert "avg_cluster_size" in sql
    assert "avg_match_confidence" in sql
    assert "min_match_confidence" in sql
    assert "CROSS JOIN" in sql


def test_cluster_quality_metrics_uses_safe_divide():
    """Singleton ratio uses SAFE_DIVIDE."""
    params = ClusterMetricsParams(
        cluster_table="p.d.clusters",
        matches_table="p.d.matches",
    )
    expr = build_cluster_quality_metrics_sql(params)
    sql = expr.render()

    assert "SAFE_DIVIDE" in sql

"""Tests for cross-batch cluster merging (Issue 3)."""

from bq_entity_resolution.sql.builders.clustering import (
    ClusteringParams,
    IncrementalClusteringParams,
    PopulateCanonicalIndexParams,
    build_cluster_assignment_sql,
    build_incremental_cluster_sql,
    build_populate_canonical_index_sql,
)

# ---------------------------------------------------------------
# Standard clustering
# ---------------------------------------------------------------


def test_standard_cluster_sql():
    """Standard (non-cross-batch) clustering works correctly."""
    params = ClusteringParams(
        all_matches_table="proj.silver.all_matched_pairs",
        cluster_table="proj.silver.entity_clusters",
        source_table="proj.silver.featured",
    )
    sql = build_cluster_assignment_sql(params).render()

    # Should NOT reference canonical_index
    assert "canonical_index" not in sql
    # Standard initialization from featured only
    assert "entity_uid AS cluster_id" in sql
    assert "WHILE" in sql


# ---------------------------------------------------------------
# Incremental clustering
# ---------------------------------------------------------------


def test_incremental_cluster_sql_uses_canonical_table():
    """Incremental clustering initializes from canonical_index + new singletons."""
    params = IncrementalClusteringParams(
        all_matches_table="proj.silver.all_matched_pairs",
        cluster_table="proj.silver.entity_clusters",
        source_table="proj.silver.featured",
        canonical_table="proj.gold.canonical_index",
    )
    sql = build_incremental_cluster_sql(params).render()

    # Should reference canonical_index for initialization
    assert "canonical_index" in sql
    # Should UNION ALL with featured (new singletons)
    assert "UNION ALL" in sql
    # Should NOT IN to exclude prior entities
    assert "NOT IN" in sql
    # Standard cluster propagation
    assert "WHILE" in sql
    assert "_edge_clusters" in sql


# ---------------------------------------------------------------
# Canonical index population
# ---------------------------------------------------------------


def test_populate_canonical_index_sql():
    """Populate SQL uses atomic MERGE to upsert entities."""
    params = PopulateCanonicalIndexParams(
        canonical_table="proj.gold.canonical_index",
        source_table="proj.silver.featured",
        cluster_table="proj.silver.entity_clusters",
    )
    sql = build_populate_canonical_index_sql(params).render()

    # Should use atomic MERGE statement
    assert "MERGE INTO" in sql
    assert "canonical_index" in sql
    assert "cluster_id" in sql

    # Should UPDATE existing entities with changed cluster_id
    assert "WHEN MATCHED AND" in sql
    assert "UPDATE SET" in sql

    # Should INSERT new entities
    assert "WHEN NOT MATCHED THEN" in sql
    assert "INSERT ROW" in sql

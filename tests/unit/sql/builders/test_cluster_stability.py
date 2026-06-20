"""Tests for cluster stability SQL builder and canonical index population."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.clustering.incremental import (
    PopulateCanonicalIndexParams,
    build_populate_canonical_index_sql,
)
from bq_entity_resolution.sql.builders.clustering.metrics import (
    ClusterStabilityParams,
    build_cluster_stability_sql,
)


class TestBuildClusterStabilitySql:
    """Test build_cluster_stability_sql output."""

    def test_generates_full_outer_join(self):
        """Stability SQL uses FULL OUTER JOIN to detect new + reassigned entities."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical_index",
            output_table="proj.ds.stability_report",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "FULL OUTER JOIN" in sql

    def test_includes_new_entity_classification(self):
        """SQL classifies entities not in prior index as 'new_entity'."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical_index",
            output_table="proj.ds.stability_report",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "new_entity" in sql

    def test_includes_reassigned_classification(self):
        """SQL classifies changed cluster_id as 'reassigned'."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical_index",
            output_table="proj.ds.stability_report",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "reassigned" in sql

    def test_includes_stable_classification(self):
        """SQL classifies unchanged entities as 'stable'."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical_index",
            output_table="proj.ds.stability_report",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "stable" in sql

    def test_change_type_column(self):
        """SQL includes change_type column."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical_index",
            output_table="proj.ds.stability_report",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "change_type" in sql

    def test_uses_coalesce_for_entity_uid(self):
        """COALESCE handles entities in either table."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical_index",
            output_table="proj.ds.report",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "COALESCE(" in sql

    def test_creates_output_table(self):
        """SQL creates the output table."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical",
            output_table="proj.ds.stability_output",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.ds.stability_output" in sql

    def test_includes_prior_and_current_cluster_id(self):
        """SQL outputs both prior_cluster_id and current_cluster_id."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical",
            output_table="proj.ds.output",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "prior_cluster_id" in sql
        assert "current_cluster_id" in sql

    def test_includes_detected_at_timestamp(self):
        """SQL includes detected_at timestamp."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical",
            output_table="proj.ds.output",
        )
        sql = build_cluster_stability_sql(params).render()
        assert "detected_at" in sql
        assert "CURRENT_TIMESTAMP()" in sql


class TestClusterStabilityParamsValidation:
    """Test ClusterStabilityParams table reference validation."""

    def test_valid_table_refs(self):
        """Valid three-part table refs are accepted."""
        params = ClusterStabilityParams(
            current_cluster_table="proj.ds.clusters",
            prior_canonical_table="proj.ds.canonical",
            output_table="proj.ds.output",
        )
        assert params.current_cluster_table == "proj.ds.clusters"

    def test_invalid_current_cluster_table(self):
        """Invalid current_cluster_table is rejected."""
        with pytest.raises(ValueError, match="Invalid table reference"):
            ClusterStabilityParams(
                current_cluster_table="invalid",
                prior_canonical_table="proj.ds.canonical",
                output_table="proj.ds.output",
            )

    def test_invalid_prior_canonical_table(self):
        """Invalid prior_canonical_table is rejected."""
        with pytest.raises(ValueError, match="Invalid table reference"):
            ClusterStabilityParams(
                current_cluster_table="proj.ds.clusters",
                prior_canonical_table="not-a-ref",
                output_table="proj.ds.output",
            )

    def test_invalid_output_table(self):
        """Invalid output_table is rejected."""
        with pytest.raises(ValueError, match="Invalid table reference"):
            ClusterStabilityParams(
                current_cluster_table="proj.ds.clusters",
                prior_canonical_table="proj.ds.canonical",
                output_table="bad",
            )


class TestPopulateCanonicalIndexMerge:
    """Test build_populate_canonical_index_sql uses MERGE pattern."""

    def test_merge_pattern(self):
        """Canonical index population uses MERGE INTO for atomicity."""
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.ds.canonical_index",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        assert "MERGE INTO" in sql

    def test_merge_matched_update(self):
        """MERGE includes WHEN MATCHED THEN UPDATE for cluster_id changes."""
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.ds.canonical_index",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        assert "WHEN MATCHED" in sql
        assert "UPDATE SET" in sql

    def test_merge_not_matched_insert(self):
        """MERGE includes WHEN NOT MATCHED THEN INSERT for new entities."""
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.ds.canonical_index",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        assert "WHEN NOT MATCHED" in sql
        assert "INSERT ROW" in sql

    def test_merge_references_correct_tables(self):
        """MERGE joins source + cluster tables."""
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.ds.canonical_index",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        assert "proj.ds.canonical_index" in sql
        assert "proj.ds.featured" in sql
        assert "proj.ds.clusters" in sql

    def test_no_separate_update_and_insert(self):
        """MERGE replaces the old UPDATE+INSERT pattern."""
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.ds.canonical_index",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        # Should NOT have separate UPDATE and INSERT statements
        assert sql.count("MERGE INTO") == 1
        # Old pattern would have separate UPDATE ... WHERE
        assert "UPDATE `proj.ds.canonical_index`" not in sql

    def test_merge_uses_entity_uid_join(self):
        """MERGE joins on entity_uid."""
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.ds.canonical_index",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        assert "entity_uid" in sql
        assert "USING" in sql

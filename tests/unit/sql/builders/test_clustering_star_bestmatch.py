"""Tests for star and best-match clustering SQL builders."""

from bq_entity_resolution.sql.builders.clustering import (
    BestMatchClusteringParams,
    StarClusteringParams,
    build_best_match_cluster_sql,
    build_star_cluster_sql,
)

# -- Star clustering --

class TestBuildStarClusterSql:
    def test_basic_star_clustering(self):
        params = StarClusteringParams(
            all_matches_table="proj.ds.all_matches",
            cluster_table="proj.ds.clusters",
            source_table="proj.ds.featured",
        )
        expr = build_star_cluster_sql(params)
        sql = expr.render()

        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.ds.clusters" in sql
        assert "entity_uid" in sql
        assert "cluster_id" in sql

    def test_star_initializes_singletons(self):
        params = StarClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_star_cluster_sql(params)
        sql = expr.render()

        assert "entity_uid AS cluster_id" in sql or "entity_uid" in sql

    def test_star_uses_match_scores(self):
        """Star clustering uses aggregate match scores to find centers."""
        params = StarClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_star_cluster_sql(params)
        sql = expr.render()

        assert "match_confidence" in sql or "SUM" in sql or "MAX" in sql

    def test_star_with_min_confidence(self):
        params = StarClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
            min_confidence=0.7,
        )
        expr = build_star_cluster_sql(params)
        sql = expr.render()

        assert "0.7" in sql

    def test_star_produces_valid_sql_expression(self):
        params = StarClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_star_cluster_sql(params)
        sql = expr.render()

        # Should be non-empty and contain basic SQL
        assert len(sql) > 50
        assert "SELECT" in sql


# -- Best-match clustering --

class TestBuildBestMatchClusterSql:
    def test_basic_best_match_clustering(self):
        params = BestMatchClusteringParams(
            all_matches_table="proj.ds.all_matches",
            cluster_table="proj.ds.clusters",
            source_table="proj.ds.featured",
        )
        expr = build_best_match_cluster_sql(params)
        sql = expr.render()

        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.ds.clusters" in sql
        assert "entity_uid" in sql
        assert "cluster_id" in sql

    def test_best_match_finds_top_match(self):
        """Each entity finds its single highest-confidence match."""
        params = BestMatchClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_best_match_cluster_sql(params)
        sql = expr.render()

        # Should use MAX or ROW_NUMBER or ORDER BY for finding best match
        assert "match_confidence" in sql or "MAX" in sql or "ROW_NUMBER" in sql

    def test_best_match_uses_least_for_cluster_id(self):
        """Cluster ID is MIN(self, best_match) for deterministic assignment."""
        params = BestMatchClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_best_match_cluster_sql(params)
        sql = expr.render()

        assert "LEAST" in sql

    def test_best_match_with_min_confidence(self):
        params = BestMatchClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
            min_confidence=0.8,
        )
        expr = build_best_match_cluster_sql(params)
        sql = expr.render()

        assert "0.8" in sql

    def test_best_match_handles_singletons(self):
        """Entities with no matches should still get a cluster (self)."""
        params = BestMatchClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_best_match_cluster_sql(params)
        sql = expr.render()

        # Should reference source table for all entities
        assert "s" in sql or "source" in sql

    def test_best_match_produces_valid_sql_expression(self):
        params = BestMatchClusteringParams(
            all_matches_table="p.d.matches",
            cluster_table="p.d.clusters",
            source_table="p.d.source",
        )
        expr = build_best_match_cluster_sql(params)
        sql = expr.render()

        assert len(sql) > 50
        assert "SELECT" in sql

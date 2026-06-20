"""Tests for confidence shaping SQL builder."""
from __future__ import annotations

from bq_entity_resolution.sql.builders.clustering import (
    ConfidenceShapingParams,
    build_confidence_shaping_sql,
)


class TestConfidenceShapingSQL:
    """Tests for build_confidence_shaping_sql()."""
    def _make_params(self, **kwargs):
        defaults = dict(
            cluster_table="proj.silver.clusters",
            matches_table="proj.silver.all_matches",
        )
        defaults.update(kwargs)
        return ConfidenceShapingParams(**defaults)
    def test_group_size_penalty_generates_correct_sql(self):
        params = self._make_params(
            group_size_penalty=True,
            group_size_threshold=10,
            group_size_penalty_rate=0.02,
        )
        sql = build_confidence_shaping_sql(params).render()
        assert "cluster_size" in sql
        assert "10" in sql
        assert "0.02" in sql
        assert "GREATEST" in sql
        # adjusted value replaces match_confidence (not a separate column)
        assert "AS match_confidence" in sql
        assert "original_confidence" in sql
    def test_hub_node_detection_generates_degree_and_flag(self):
        params = self._make_params(hub_node_detection=True, hub_degree_threshold=20)
        sql = build_confidence_shaping_sql(params).render()
        assert "degree" in sql
        assert "20" in sql
        assert "is_hub_node" in sql
        assert "node_degrees" in sql
    def test_both_features_enabled(self):
        params = self._make_params(
            group_size_penalty=True,
            group_size_threshold=5,
            group_size_penalty_rate=0.05,
            hub_node_detection=True,
            hub_degree_threshold=15,
        )
        sql = build_confidence_shaping_sql(params).render()
        assert "cluster_size" in sql and "degree" in sql and "is_hub_node" in sql
    def test_neither_feature_enabled_passthrough(self):
        params = self._make_params(group_size_penalty=False, hub_node_detection=False)
        sql = build_confidence_shaping_sql(params).render()
        # When no penalty, match_confidence is passed through unchanged
        assert "m.match_confidence," in sql
        assert "original_confidence" in sql
        assert "FALSE AS is_hub_node" in sql
    def test_match_confidence_column_is_replaced_not_appended(self):
        """Verify that adjusted confidence overwrites match_confidence
        rather than being appended as a separate adjusted_confidence column."""
        params = self._make_params(group_size_penalty=True)
        sql = build_confidence_shaping_sql(params).render()
        # EXCEPT removes original match_confidence from m.*
        assert "EXCEPT(match_confidence)" in sql
        # adjusted value is written AS match_confidence
        assert "AS match_confidence" in sql
        # old column name 'adjusted_confidence' should NOT appear
        assert "adjusted_confidence" not in sql

    def test_correct_table_references(self):
        params = self._make_params(
            cluster_table="proj.silver.clusters",
            matches_table="proj.silver.all_matches",
            group_size_penalty=True,
            hub_node_detection=True,
            hub_degree_threshold=20,
        )
        sql = build_confidence_shaping_sql(params).render()
        assert "proj.silver.clusters" in sql and "proj.silver.all_matches" in sql

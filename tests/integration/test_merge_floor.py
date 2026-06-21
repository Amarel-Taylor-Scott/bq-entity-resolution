"""Merge-score floor stops a weak/false edge from collapsing two true clusters."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.clustering.connected_components import (
    ClusteringParams,
    build_cluster_assignment_sql,
)
from bq_entity_resolution.sql.builders.clustering.incremental import (
    IncrementalClusteringParams,
    build_incremental_cluster_sql,
)


class TestFilterGeneration:
    def test_cc_filter_present_only_when_set(self):
        base = dict(all_matches_table="p.d.m", cluster_table="p.d.c",
                    source_table="p.d.f")
        assert "WHERE m.match_total_score" not in build_cluster_assignment_sql(
            ClusteringParams(**base)).render()
        assert "WHERE m.match_total_score >= 2.0" in build_cluster_assignment_sql(
            ClusteringParams(**base, min_edge_score=2.0)).render()

    def test_incremental_filter_present_only_when_set(self):
        base = dict(all_matches_table="p.d.m", cluster_table="p.d.c",
                    source_table="p.d.f", canonical_table="p.d.ci")
        assert "WHERE m.match_total_score" not in build_incremental_cluster_sql(
            IncrementalClusteringParams(**base)).render()
        assert "WHERE m.match_total_score >= 0.97" in build_incremental_cluster_sql(
            IncrementalClusteringParams(**base, min_edge_score=0.97)).render()


def _cluster_count(floor: float) -> int:
    from bq_entity_resolution.backends.duckdb import DuckDBBackend
    from bq_entity_resolution.backends.duckdb.scripting import (
        execute_bq_scripting,
        split_statements,
    )
    from bq_entity_resolution.backends.duckdb.sql_adapter import adapt_sql

    db = DuckDBBackend(":memory:")
    db.execute("CREATE TABLE f (entity_uid BIGINT)")
    db.connection.execute("INSERT INTO f VALUES (1),(2),(3)")
    db.execute(
        "CREATE TABLE m (left_entity_uid BIGINT, right_entity_uid BIGINT, "
        "match_total_score DOUBLE)"
    )
    # Star around node 1 (single-iteration closure): strong 1-2, weak 1-3.
    db.connection.execute("INSERT INTO m VALUES (1,2,5.0),(1,3,1.0)")
    sql = build_cluster_assignment_sql(
        ClusteringParams(all_matches_table="p.d.m", cluster_table="p.d.c",
                         source_table="p.d.f", min_edge_score=floor)
    ).render()
    # The executor adapts BQ SQL (strip backticks, flatten 3-part names) then
    # hands procedural scripts to the interpreter — mirror that here.
    execute_bq_scripting(db.connection, adapt_sql(sql), split_statements)
    rows = db.execute_and_fetch("SELECT COUNT(DISTINCT cluster_id) AS n FROM c")
    return int(rows[0]["n"])


class TestPreventsOverMergeOnDuckDB:
    def test_no_floor_merges_everything(self):
        # Both edges accepted → 1,2,3 collapse to one cluster (legacy behaviour).
        assert _cluster_count(0.0) == 1

    def test_floor_drops_weak_edge(self):
        # Floor between the two edge scores → weak 1-3 edge dropped → {1,2}, {3}.
        assert _cluster_count(2.0) == 2

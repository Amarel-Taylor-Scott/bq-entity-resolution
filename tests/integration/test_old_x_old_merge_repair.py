"""old×old merge-repair persists into the canonical index (the headline path).

Two canonical entities that a single-pass pipeline left split are merged by an
old×old repair leaf; the merge must be written back to the persistent
canonical_index even though neither entity is in the current batch. This proves
the broad cluster-update step (`build_repair_cluster_update_sql`) closes the gap
where the batch-only MERGE would silently drop non-batch reassignments.
"""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.clustering import (
    PopulateCanonicalIndexParams,
    build_populate_canonical_index_sql,
    build_repair_cluster_update_sql,
)


class TestPopulateShape:
    def test_populate_has_broad_update_and_merge(self):
        params = PopulateCanonicalIndexParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
            cluster_table="proj.silver.entity_clusters",
        )
        sql = build_populate_canonical_index_sql(params).render()
        # Step 1: broad update over ALL existing canonicals (not just the batch).
        assert "UPDATE `proj.gold.canonical_index` ci" in sql
        assert "FROM `proj.silver.entity_clusters` cl" in sql
        assert "ci.cluster_id != cl.cluster_id" in sql
        # Step 2: MERGE still upserts the current batch (back-compat).
        assert "MERGE INTO" in sql
        assert "WHEN MATCHED AND" in sql
        assert "INSERT ROW" in sql


class TestMergeRepairPersistsOnDuckDB:
    def test_old_x_old_merge_written_back_to_canonical_index(self):
        from bq_entity_resolution.backends.duckdb import DuckDBBackend

        db = DuckDBBackend(":memory:")
        # Persistent canonical index: three separate entities/clusters.
        db.execute(
            "CREATE TABLE canonical_index (entity_uid BIGINT, cluster_id BIGINT)"
        )
        for uid, cid in [(101, 101), (102, 102), (103, 103)]:
            db.connection.execute(
                "INSERT INTO canonical_index VALUES (?,?)", [uid, cid]
            )
        # Post-clustering state from an old×old repair: 103 merged into 101.
        # NONE of these entities are in the current batch (a pure repair run).
        db.execute(
            "CREATE TABLE entity_clusters (entity_uid BIGINT, cluster_id BIGINT)"
        )
        for uid, cid in [(101, 101), (102, 102), (103, 101)]:
            db.connection.execute(
                "INSERT INTO entity_clusters VALUES (?,?)", [uid, cid]
            )

        db.execute(
            build_repair_cluster_update_sql(
                "p.d.canonical_index", "p.d.entity_clusters"
            ).render()
        )

        out = db.execute_and_fetch(
            "SELECT entity_uid, cluster_id FROM canonical_index ORDER BY entity_uid"
        )
        by_uid = {int(r["entity_uid"]): int(r["cluster_id"]) for r in out}
        # 103 now shares 101's cluster — the repair merge persisted.
        assert by_uid[101] == 101
        assert by_uid[103] == 101
        # 102 untouched.
        assert by_uid[102] == 102

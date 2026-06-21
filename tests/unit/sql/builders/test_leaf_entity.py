"""Tests for the canonical consensus aggregate builder (entity-level new×old)."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.leaf_entity import build_canonical_aggregate_sql


class TestStructure:
    def test_emits_per_column_vote_ctes_and_cluster_uid(self):
        sql = build_canonical_aggregate_sql(
            target="p.d.agg",
            source="p.d.canonical_index",
            value_columns=["email", "zip5"],
        ).render()
        assert "CREATE OR REPLACE TABLE `p.d.agg`" in sql
        assert "vote_email AS (" in sql
        assert "vote_zip5 AS (" in sql
        # Portable most-frequent: COUNT(*) + QUALIFY ROW_NUMBER().
        assert "QUALIFY ROW_NUMBER() OVER (" in sql
        assert "ORDER BY COUNT(*) DESC" in sql
        # entity_uid is the cluster id (a real entity uid) for graph linkage.
        assert "ids.cluster_id AS entity_uid" in sql

    def test_skips_group_and_uid_columns(self):
        sql = build_canonical_aggregate_sql(
            target="p.d.agg",
            source="p.d.canonical_index",
            value_columns=["cluster_id", "entity_uid", "name"],
        ).render()
        assert "vote_name AS (" in sql
        assert "vote_cluster_id AS (" not in sql
        assert "vote_entity_uid AS (" not in sql

    def test_rejects_bad_identifier(self):
        with pytest.raises(ValueError):
            build_canonical_aggregate_sql(
                target="p.d.agg", source="p.d.c", value_columns=["a; DROP TABLE x"]
            )


class TestExecutesOnDuckDB:
    def test_consensus_picks_majority_value_per_cluster(self):
        from bq_entity_resolution.backends.duckdb import DuckDBBackend

        db = DuckDBBackend(":memory:")
        db.execute(
            "CREATE TABLE canonical_index "
            "(entity_uid BIGINT, name VARCHAR, cluster_id BIGINT)"
        )
        rows = [
            (1, "John Smith", 1),
            (2, "John Smith", 1),
            (3, "Jon Smith", 1),  # minority — should lose
            (4, "Maria Gomez", 2),
        ]
        for r in rows:
            db.connection.execute("INSERT INTO canonical_index VALUES (?,?,?)", list(r))

        db.execute(
            build_canonical_aggregate_sql(
                target="p.d.canon_agg",
                source="p.d.canonical_index",
                value_columns=["name"],
            ).render()
        )
        out = db.execute_and_fetch(
            "SELECT entity_uid, cluster_id, name FROM canon_agg ORDER BY cluster_id"
        )
        assert len(out) == 2  # one consensus row per cluster
        by_cid = {int(r["cluster_id"]): r for r in out}
        assert by_cid[1]["name"] == "John Smith"  # majority of cluster 1
        assert int(by_cid[1]["entity_uid"]) == 1  # entity_uid == cluster_id
        assert by_cid[2]["name"] == "Maria Gomez"

"""Tests for per-leaf metrics SQL."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.leaf_metrics import (
    LeafMetricInput,
    build_leaf_metrics_sql,
)


def _inp(name, self_join=False):
    return LeafMetricInput(
        leaf_name=name,
        pairs_table=f"p.d.leaf_pairs_{name}",
        left_table="p.d.left",
        right_table="p.d.right",
        is_self_join=self_join,
    )


class TestStructure:
    def test_self_join_uses_pairwise_space(self):
        sql = build_leaf_metrics_sql("p.d.leaf_metrics", [_inp("nxn", True)]).render()
        assert "lr * (lr - 1) / 2" in sql
        assert "'nxn' AS leaf_name" in sql
        assert "reduction_ratio" in sql

    def test_cross_join_uses_product_space(self):
        sql = build_leaf_metrics_sql("p.d.leaf_metrics", [_inp("nxo", False)]).render()
        assert "lr * rr" in sql

    def test_unions_multiple_leaves(self):
        sql = build_leaf_metrics_sql(
            "p.d.leaf_metrics", [_inp("a"), _inp("b")]
        ).render()
        assert sql.count("UNION ALL") == 1
        assert "'a' AS leaf_name" in sql and "'b' AS leaf_name" in sql

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            build_leaf_metrics_sql("p.d.leaf_metrics", [])


class TestExecutesOnDuckDB:
    def test_reduction_ratio_computed(self):
        from bq_entity_resolution.backends.duckdb import DuckDBBackend

        db = DuckDBBackend(":memory:")
        # 4 left records, self-join → comparison space = 4*3/2 = 6.
        db.execute("CREATE TABLE l (entity_uid BIGINT)")
        for i in range(4):
            db.connection.execute("INSERT INTO l VALUES (?)", [i])
        # 2 candidate pairs produced.
        db.execute("CREATE TABLE pairs (left_entity_uid BIGINT, right_entity_uid BIGINT)")
        db.connection.execute("INSERT INTO pairs VALUES (0,1),(2,3)")

        inp = LeafMetricInput(
            leaf_name="nxn",
            pairs_table="p.d.pairs",
            left_table="p.d.l",
            right_table="p.d.l",
            is_self_join=True,
        )
        db.execute(build_leaf_metrics_sql("p.d.leaf_metrics", [inp]).render())
        rows = db.execute_and_fetch("SELECT * FROM leaf_metrics")
        assert len(rows) == 1
        r = rows[0]
        assert int(r["candidate_pairs"]) == 2
        assert int(r["comparison_space"]) == 6
        # reduction_ratio = 1 - 2/6 = 0.6667
        assert abs(float(r["reduction_ratio"]) - (1 - 2 / 6)) < 1e-6

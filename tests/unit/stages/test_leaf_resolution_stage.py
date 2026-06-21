"""Tests for the LeafResolutionStage planning."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef
from bq_entity_resolution.stages.leaf_resolution import LeafResolutionStage


@pytest.fixture
def cfg():
    c = quick_config(
        bq_project="test-proj",
        source_table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        column_roles={
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
        },
        project_name="leaf_stage_test",
    )
    c.leaves = [
        LeafDef(name="new_x_new", left="new", right="new"),
        LeafDef(name="new_x_old", left="new", right="old"),
    ]
    return c


class TestLeafResolutionStage:
    def test_name(self, cfg):
        assert LeafResolutionStage(cfg).name == "leaf_resolution"

    def test_outputs_all_matches(self, cfg):
        out = LeafResolutionStage(cfg).outputs
        assert "all_matches" in out
        assert out["all_matches"].fq_name.endswith("all_matched_pairs")

    def test_inputs_include_canonical_for_cross_partition(self, cfg):
        # new_x_old reads the canonical partition.
        ins = LeafResolutionStage(cfg).inputs
        assert "canonical_index" in ins

    def test_plan_emits_one_sql_per_leaf_plus_union(self, cfg):
        exprs = LeafResolutionStage(cfg).plan()
        # 2 leaves + 1 union into all_matches
        assert len(exprs) == 3
        rendered = [e.render("bigquery") for e in exprs]
        assert any("leaf_pairs_new_x_new" in s for s in rendered)
        assert any("leaf_pairs_new_x_old" in s for s in rendered)
        # Final union targets all_matches and tags by match_leaf.
        union = rendered[-1]
        assert "all_matched_pairs" in union
        assert "match_leaf" in union
        assert "UNION ALL" in union

    def test_new_x_old_short_circuits_on_canonical_keys(self, cfg):
        cfg.leaves = [
            LeafDef.model_validate(
                {
                    "name": "new_x_old",
                    "left": "new",
                    "right": "old",
                    "heuristics": {"exact_key_short_circuit": ["email"]},
                }
            )
        ]
        exprs = LeafResolutionStage(cfg).plan()
        sql = " ".join(e.render("bigquery") for e in exprs)
        assert "short_circuit" in sql
        assert "l.email = r.email" in sql

    def test_empty_when_no_runnable_leaves(self, cfg):
        cfg.leaves = [
            LeafDef(name="manual", left="new", right="new", schedule="manual"),
        ]
        assert LeafResolutionStage(cfg).plan() == []

    def test_self_join_guard_in_new_x_new(self, cfg):
        exprs = LeafResolutionStage(cfg).plan()
        nxn = next(
            e.render("bigquery")
            for e in exprs
            if "leaf_pairs_new_x_new" in e.render("bigquery")
        )
        assert "l.entity_uid < r.entity_uid" in nxn

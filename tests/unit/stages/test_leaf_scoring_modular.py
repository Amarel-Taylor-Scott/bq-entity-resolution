"""Tests for modular leaf scoring (scoring: greatest | sum | fellegi_sunter)."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef
from bq_entity_resolution.stages.leaf_resolution import LeafResolutionStage


@pytest.fixture
def cfg():
    return quick_config(
        bq_project="p",
        source_table="p.raw.cust",
        unique_key="id",
        updated_at="updated_at",
        column_roles={
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
        },
        project_name="modular_test",
    )


def _plan(cfg, leaf_name):
    stage = LeafResolutionStage(cfg, leaves=cfg.select_leaves(only=[leaf_name]))
    return [e.render() for e in stage.plan()]


class TestGreatestDefaultUnchanged:
    def test_default_scoring_is_greatest_single_statement(self, cfg):
        cfg.leaves = [LeafDef(name="new_x_new", left="new", right="new")]
        stmts = _plan(cfg, "new_x_new")
        # greatest path: one leaf SQL + one union = 2 statements, no candidates.
        assert len(stmts) == 2
        assert not any("leaf_candidates_" in s for s in stmts)
        assert any("GREATEST" in s for s in stmts)


class TestSumScoringLeaf:
    def test_emits_candidates_then_production_scoring(self, cfg):
        cfg.leaves = [LeafDef(name="new_x_old", left="new", right="old", scoring="sum")]
        stmts = _plan(cfg, "new_x_old")
        # candidates + scoring + union
        assert len(stmts) == 3
        assert any("leaf_candidates_new_x_old" in s for s in stmts)
        scoring = next(
            s for s in stmts
            if "leaf_pairs_new_x_old" in s and "leaf_candidates_new_x_old" in s
        )
        # Production sum scorer joins the leaf candidate table to the partition
        # source tables: featured (new/left) × canonical_index (old/right).
        assert "er_silver.featured` l" in scoring
        assert "er_gold.canonical_index` r" in scoring
        # Real scoring machinery present (per-comparison score columns, banding).
        assert "match_total_score" in scoring

    def test_no_greatest_in_sum_leaf(self, cfg):
        cfg.leaves = [LeafDef(name="nxo", left="new", right="old", scoring="sum")]
        scoring = next(
            s for s in _plan(cfg, "nxo") if "leaf_candidates_nxo" not in s
            and "leaf_pairs_nxo" in s
        )
        assert "GREATEST" not in scoring


class TestFellegiSunterLeaf:
    def test_fs_leaf_emits_candidates_and_scoring(self, cfg):
        cfg.leaves = [
            LeafDef(name="nn", left="new", right="new", scoring="fellegi_sunter")
        ]
        stmts = _plan(cfg, "nn")
        assert any("leaf_candidates_nn" in s for s in stmts)
        assert any("leaf_pairs_nn" in s for s in stmts)


class TestUnionNormalization:
    def test_union_uses_literal_leaf_and_compare_method_for_sum(self, cfg):
        cfg.leaves = [LeafDef(name="nxo", left="new", right="old", scoring="sum")]
        union = next(s for s in _plan(cfg, "nxo") if "all_matched_pairs" in s)
        # sum/F-S matches table has no match_method column → synthesised literal.
        assert "'nxo' AS match_leaf" in union
        assert "'compare' AS match_method" in union

    def test_union_preserves_method_column_for_greatest(self, cfg):
        cfg.leaves = [LeafDef(name="nxn", left="new", right="new")]
        union = next(s for s in _plan(cfg, "nxn") if "all_matched_pairs" in s)
        # greatest table carries match_method (e.g. short_circuit) → read it.
        assert "match_method AS match_method" in union
        assert "'nxn' AS match_leaf" in union

"""Tests for entity_level (consensus new×old) wiring in LeafResolutionStage."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.models.leaves import LeafHeuristics
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
        project_name="el_test",
    )


def _plan(cfg, leaf_name):
    stage = LeafResolutionStage(cfg, leaves=cfg.select_leaves(only=[leaf_name]))
    return [e.render() for e in stage.plan()]


class TestEntityLevelWiring:
    def test_emits_aggregate_and_binds_canonical_side(self, cfg):
        cfg.leaves = [
            LeafDef(
                name="new_x_old", left="new", right="old", scoring="sum",
                heuristics=LeafHeuristics(entity_level=True),
            )
        ]
        stmts = _plan(cfg, "new_x_old")
        agg = next(
            (s for s in stmts
             if "CREATE OR REPLACE TABLE `p.er_silver.leaf_canonical_agg_new_x_old`" in s),
            None,
        )
        assert agg is not None, "aggregate table not emitted"
        # candidate generation's right side binds to the aggregate, not the raw index.
        cand = next(s for s in stmts if "leaf_candidates_new_x_old`" in s and "WITH" in s)
        assert "leaf_canonical_agg_new_x_old`)" in cand  # leaf_r reads the agg
        assert "er_gold.canonical_index" not in cand

    def test_greatest_entity_level_also_aggregates(self, cfg):
        cfg.leaves = [
            LeafDef(
                name="nxo", left="new", right="old",
                heuristics=LeafHeuristics(entity_level=True),
            )
        ]
        stmts = _plan(cfg, "nxo")
        assert any("leaf_canonical_agg_nxo`" in s for s in stmts)

    def test_no_aggregate_without_entity_level(self, cfg):
        cfg.leaves = [LeafDef(name="nxo", left="new", right="old", scoring="sum")]
        assert not any("leaf_canonical_agg" in s for s in _plan(cfg, "nxo"))

    def test_entity_level_ignored_when_no_canonical_side(self, cfg):
        # new×new: both sides are the batch — entity_level has nothing to aggregate.
        cfg.leaves = [
            LeafDef(
                name="nxn", left="new", right="new",
                heuristics=LeafHeuristics(entity_level=True),
            )
        ]
        assert not any("leaf_canonical_agg" in s for s in _plan(cfg, "nxn"))

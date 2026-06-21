"""Tests for touched_only + repair-watermark wiring in LeafResolutionStage."""

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
        project_name="touched_test",
    )


def _plan_sql(cfg, leaf_name):
    stage = LeafResolutionStage(cfg, leaves=cfg.select_leaves(only=[leaf_name]))
    return [e.render() for e in stage.plan()]


class TestTouchedOnlySelfJoin:
    def test_emits_ddl_floor_guard_and_advance(self, cfg):
        cfg.leaves = [
            LeafDef(
                name="old_x_old", left="old", right="old", schedule="cron",
                cron="0 3 * * 0",
                heuristics=LeafHeuristics(touched_only=True),
            )
        ]
        stmts = _plan_sql(cfg, "old_x_old")
        joined = "\n".join(stmts)
        # DDL prepended
        assert "CREATE TABLE IF NOT EXISTS" in stmts[0]
        assert "leaf_repair_watermarks" in stmts[0]
        # touched guard: at least one endpoint changed since last repair
        assert "l.pipeline_loaded_at >" in joined
        assert "r.pipeline_loaded_at >" in joined
        assert "COALESCE(MAX(last_repair_at)" in joined
        # advance INSERT appended
        assert "INSERT INTO" in stmts[-1]
        assert "old_x_old" in stmts[-1]

    def test_custom_touched_column(self, cfg):
        cfg.leaves = [
            LeafDef(
                name="oxo", left="old", right="old", schedule="manual",
                heuristics=LeafHeuristics(
                    touched_only=True, touched_column="source_updated_at"
                ),
            )
        ]
        joined = "\n".join(_plan_sql(cfg, "oxo"))
        assert "l.source_updated_at >" in joined
        assert "r.source_updated_at >" in joined


class TestTouchedOnlyCrossPartition:
    def test_restricts_canonical_side_only(self, cfg):
        cfg.leaves = [
            LeafDef(
                name="new_x_old", left="new", right="old",
                heuristics=LeafHeuristics(touched_only=True),
            )
        ]
        joined = "\n".join(_plan_sql(cfg, "new_x_old"))
        # The old (right/canonical) CTE is restricted; bare column ref in WHERE.
        assert "pipeline_loaded_at >" in joined
        # No l./r. aliased touched guard for a cross-partition leaf.
        assert "l.pipeline_loaded_at >" not in joined


class TestNoRepairWhenNotTouched:
    def test_every_run_leaf_has_no_repair_artifacts(self, cfg):
        cfg.leaves = [LeafDef(name="new_x_new", left="new", right="new")]
        stmts = _plan_sql(cfg, "new_x_new")
        joined = "\n".join(stmts)
        assert "leaf_repair_watermarks" not in joined
        assert "CREATE TABLE IF NOT EXISTS" not in joined

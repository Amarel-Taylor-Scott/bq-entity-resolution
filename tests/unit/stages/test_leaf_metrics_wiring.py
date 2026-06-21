"""Per-leaf metrics are emitted only when blocking metrics are enabled."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef
from bq_entity_resolution.stages.leaf_resolution import LeafResolutionStage


@pytest.fixture
def cfg():
    c = quick_config(
        bq_project="p",
        source_table="p.raw.cust",
        unique_key="id",
        updated_at="updated_at",
        column_roles={"first_name": "first_name", "last_name": "last_name",
                      "email": "email"},
        project_name="metrics_test",
    )
    c.leaves = [
        LeafDef(name="new_x_new", left="new", right="new"),
        LeafDef(name="new_x_old", left="new", right="old"),
    ]
    return c


def _plan(cfg):
    stage = LeafResolutionStage(cfg, leaves=cfg.select_leaves())
    return [e.render() for e in stage.plan()]


def test_no_metrics_by_default(cfg):
    assert not any("leaf_metrics" in s for s in _plan(cfg))


def test_metrics_emitted_when_enabled(cfg):
    cfg.monitoring.blocking_metrics.enabled = True
    stmts = _plan(cfg)
    metrics = [s for s in stmts if "leaf_metrics`" in s]
    assert len(metrics) == 1
    m = metrics[0]
    assert "'new_x_new' AS leaf_name" in m
    assert "'new_x_old' AS leaf_name" in m
    assert "reduction_ratio" in m

"""Tests for PipelineConfig.select_leaves() scheduling/repair semantics."""

from __future__ import annotations

from datetime import datetime

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef


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
        project_name="leaf_select_test",
    )
    c.leaves = [
        LeafDef(name="new_x_new", left="new", right="new"),
        LeafDef(name="new_x_old", left="new", right="old"),
        LeafDef(name="manual_repair", left="old", right="old", schedule="manual"),
        LeafDef(
            name="weekly_repair", left="old", right="old",
            schedule="cron", cron="0 3 * * 0",
        ),
        LeafDef(name="disabled", left="new", right="new", enabled=False),
    ]
    return c


def _names(leaves):
    return [lf.name for lf in leaves]


class TestSelectLeaves:
    def test_default_run_is_every_run_only(self, cfg):
        assert _names(cfg.select_leaves()) == ["new_x_new", "new_x_old"]

    def test_repair_adds_manual_and_cron(self, cfg):
        assert _names(cfg.select_leaves(repair=True)) == [
            "new_x_new", "new_x_old", "manual_repair", "weekly_repair",
        ]

    def test_only_runs_named_regardless_of_schedule(self, cfg):
        assert _names(cfg.select_leaves(only=["manual_repair"])) == ["manual_repair"]
        assert _names(cfg.select_leaves(only=["weekly_repair"])) == ["weekly_repair"]

    def test_only_filters_disabled(self, cfg):
        assert cfg.select_leaves(only=["disabled"]) == []

    def test_cron_due_selects_without_repair(self, cfg):
        # A Sunday 3am firing has occurred and was never serviced → due.
        selected = cfg.select_leaves(
            now=datetime(2026, 6, 21, 4, 0),
            last_repair_at={},
        )
        assert "weekly_repair" in _names(selected)

    def test_cron_not_due_when_recently_serviced(self, cfg):
        selected = cfg.select_leaves(
            now=datetime(2026, 6, 21, 4, 0),
            last_repair_at={"weekly_repair": datetime(2026, 6, 21, 3, 0)},
        )
        assert "weekly_repair" not in _names(selected)

    def test_runnable_leaves_delegates_to_default_select(self, cfg):
        assert _names(cfg.runnable_leaves()) == _names(cfg.select_leaves())

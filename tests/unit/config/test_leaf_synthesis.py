"""Tests for leaf back-compat synthesis on PipelineConfig and DAG wiring."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef, PartitionDef
from bq_entity_resolution.pipeline.dag import build_pipeline_dag


@pytest.fixture
def cfg():
    return quick_config(
        bq_project="test-proj",
        source_table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        column_roles={
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
        },
        project_name="leaf_synth_test",
    )


class TestEffectivePartitions:
    def test_defaults_to_new_old(self, cfg):
        assert [p.name for p in cfg.effective_partitions()] == ["new", "old"]

    def test_uses_explicit_partitions(self, cfg):
        cfg.partitions = [
            PartitionDef(name="crm", source="batch"),
            PartitionDef(name="erp", source="canonical"),
        ]
        assert [p.name for p in cfg.effective_partitions()] == ["crm", "erp"]


class TestEffectiveLeaves:
    def test_synthesizes_new_x_new_and_new_x_old_when_cross_batch(self, cfg):
        # quick_config enables cross_batch blocking by default.
        assert cfg._has_cross_batch_blocking() is True
        names = [leaf.name for leaf in cfg.effective_leaves()]
        assert names == ["new_x_new", "new_x_old"]

    def test_only_new_x_new_without_cross_batch(self, cfg):
        for tier in cfg.matching_tiers:
            tier.blocking.cross_batch = False
        names = [leaf.name for leaf in cfg.effective_leaves()]
        assert names == ["new_x_new"]

    def test_explicit_leaves_take_precedence(self, cfg):
        cfg.leaves = [LeafDef(name="custom", left="new", right="new")]
        assert [leaf.name for leaf in cfg.effective_leaves()] == ["custom"]

    def test_runnable_excludes_manual_and_cron(self, cfg):
        cfg.leaves = [
            LeafDef(name="new_x_new", left="new", right="new"),
            LeafDef(name="manual_leaf", left="new", right="old", schedule="manual"),
            LeafDef(
                name="oxo", left="old", right="old",
                schedule="cron", cron="0 3 * * 0",
            ),
        ]
        assert [leaf.name for leaf in cfg.runnable_leaves()] == ["new_x_new"]


class TestLeafValidation:
    def test_rejects_duplicate_leaf_names(self, cfg):
        from pydantic import ValidationError

        from bq_entity_resolution.config.schema import PipelineConfig

        data = cfg.model_dump()
        data["leaves"] = [
            {"name": "dup", "left": "new", "right": "new"},
            {"name": "dup", "left": "new", "right": "old"},
        ]
        with pytest.raises(ValidationError, match="Duplicate leaf names"):
            PipelineConfig(**data)

    def test_rejects_unknown_partition_reference(self, cfg):
        from pydantic import ValidationError

        from bq_entity_resolution.config.schema import PipelineConfig

        data = cfg.model_dump()
        data["leaves"] = [{"name": "x", "left": "new", "right": "nope"}]
        with pytest.raises(ValidationError, match="undefined partition"):
            PipelineConfig(**data)

    def test_accepts_custom_partition_reference(self, cfg):
        from bq_entity_resolution.config.schema import PipelineConfig

        data = cfg.model_dump()
        data["partitions"] = [
            {"name": "crm", "source": "batch"},
            {"name": "erp", "source": "canonical"},
        ]
        data["leaves"] = [{"name": "crm_x_erp", "left": "crm", "right": "erp"}]
        config = PipelineConfig(**data)  # must not raise
        assert [leaf.name for leaf in config.effective_leaves()] == ["crm_x_erp"]


class TestDagWiring:
    def test_no_leaves_keeps_historical_chain(self, cfg):
        names = build_pipeline_dag(cfg).stage_names
        assert "leaf_resolution" not in names
        assert any(n.startswith("blocking_") for n in names)
        assert any(n.startswith("matching_") for n in names)

    def test_explicit_leaves_replace_tier_chain(self, cfg):
        cfg.leaves = [
            LeafDef(name="new_x_new", left="new", right="new"),
            LeafDef(name="new_x_old", left="new", right="old"),
        ]
        names = build_pipeline_dag(cfg).stage_names
        assert "leaf_resolution" in names
        assert not any(n.startswith("blocking_") for n in names)
        assert not any(n.startswith("matching_") for n in names)

    def test_clustering_depends_on_leaf_stage(self, cfg):
        cfg.leaves = [LeafDef(name="new_x_new", left="new", right="new")]
        dag = build_pipeline_dag(cfg)
        assert "leaf_resolution" in dag.get_dependencies("clustering")

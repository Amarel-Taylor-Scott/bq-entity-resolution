"""Tests for ClusteringStage incremental behavior.

Verifies that ClusteringStage switches between standard and incremental
clustering SQL based on config.incremental.enabled.
"""

from __future__ import annotations

from bq_entity_resolution.stages.reconciliation import ClusteringStage

# -- Minimal config fixture --

def _make_minimal_config(incremental_enabled: bool = False):
    """Create a minimal config-like object for testing ClusteringStage.

    Uses a simple namespace to avoid importing the full config schema.
    """
    class NS:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    project = NS(
        bq_project="test-proj",
        bq_dataset_bronze="test-proj.bronze",
        bq_dataset_silver="test-proj.silver",
        bq_dataset_gold="test-proj.gold",
        bq_location="US",
        udf_dataset="test-proj.udfs",
        watermark_dataset="meta",
    )

    incremental = NS(enabled=incremental_enabled)
    clustering = NS(max_iterations=20)
    reconciliation = NS(clustering=clustering)

    scale = NS(
        checkpoint_enabled=False,
        max_bytes_billed=None,
        canonical_index_clustering=["entity_uid"],
        canonical_index_partition_by=None,
    )

    config = NS(
        project=project,
        sources=[],
        incremental=incremental,
        reconciliation=reconciliation,
        scale=scale,
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table

    return config


class TestClusteringStageIncremental:
    """Tests for incremental behavior in ClusteringStage."""

    def test_is_incremental_true_when_enabled(self):
        """_is_incremental returns True when config.incremental.enabled=True."""
        config = _make_minimal_config(incremental_enabled=True)
        stage = ClusteringStage(config)
        assert stage._is_incremental is True

    def test_is_incremental_false_when_disabled(self):
        """_is_incremental returns False when config.incremental.enabled=False."""
        config = _make_minimal_config(incremental_enabled=False)
        stage = ClusteringStage(config)
        assert stage._is_incremental is False

    def test_inputs_include_canonical_index_when_incremental(self):
        """Inputs include canonical_index when incremental=True."""
        config = _make_minimal_config(incremental_enabled=True)
        stage = ClusteringStage(config)
        inputs = stage.inputs

        assert "canonical_index" in inputs
        assert "canonical_index" in inputs["canonical_index"].fq_name

    def test_inputs_exclude_canonical_index_when_not_incremental(self):
        """Inputs do NOT include canonical_index when incremental=False."""
        config = _make_minimal_config(incremental_enabled=False)
        stage = ClusteringStage(config)
        inputs = stage.inputs

        assert "canonical_index" not in inputs

    def test_inputs_always_include_all_matches_and_featured(self):
        """Inputs always include all_matches and featured."""
        for enabled in (True, False):
            config = _make_minimal_config(incremental_enabled=enabled)
            stage = ClusteringStage(config)
            inputs = stage.inputs

            assert "all_matches" in inputs
            assert "featured" in inputs

    def test_plan_incremental_references_canonical(self):
        """Incremental plan SQL includes canonical table reference."""
        config = _make_minimal_config(incremental_enabled=True)
        stage = ClusteringStage(config)
        exprs = stage.plan()

        assert len(exprs) == 1
        sql = exprs[0].render()

        # Incremental clustering initializes from canonical_index
        assert "canonical_index" in sql
        # Should contain the UNION ALL for merging prior + new entities
        assert "UNION ALL" in sql

    def test_plan_standard_no_canonical_reference(self):
        """Standard (non-incremental) plan SQL does not reference canonical."""
        config = _make_minimal_config(incremental_enabled=False)
        stage = ClusteringStage(config)
        exprs = stage.plan()

        assert len(exprs) == 1
        sql = exprs[0].render()

        # Standard clustering should not reference canonical_index
        assert "canonical_index" not in sql
        # Standard initialization: all entities as singletons
        assert "entity_uid AS cluster_id" in sql
        assert "UNION ALL" not in sql

    def test_plan_both_modes_produce_iterative_loop(self):
        """Both modes produce iterative WHILE loop for propagation."""
        for enabled in (True, False):
            config = _make_minimal_config(incremental_enabled=enabled)
            stage = ClusteringStage(config)
            exprs = stage.plan()
            sql = exprs[0].render()

            assert "DECLARE" in sql
            assert "WHILE" in sql
            assert "END WHILE" in sql

    def test_is_incremental_handles_missing_incremental_config(self):
        """_is_incremental returns False if config has no incremental attr."""
        class NS:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        project = NS(
            bq_project="test-proj",
            bq_dataset_bronze="test-proj.bronze",
            bq_dataset_silver="test-proj.silver",
            bq_dataset_gold="test-proj.gold",
            bq_location="US",
            udf_dataset="test-proj.udfs",
            watermark_dataset="meta",
        )

        config = NS(
            project=project,
            sources=[],
            reconciliation=NS(clustering=NS(max_iterations=20)),
            scale=NS(checkpoint_enabled=False, max_bytes_billed=None),
        )

        config.fq_table = lambda da, tn: f"{getattr(project, da, 'ds')}.{tn}"

        stage = ClusteringStage(config)
        # No incremental attr at all
        assert stage._is_incremental is False

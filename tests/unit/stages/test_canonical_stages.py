"""Tests for CanonicalIndexInitStage and CanonicalIndexPopulateStage.

Verifies these stages produce correct SQL for managing the
canonical_index table during incremental processing.
"""

from __future__ import annotations

from bq_entity_resolution.stages.reconciliation import (
    CanonicalIndexInitStage,
    CanonicalIndexPopulateStage,
)

# -- Minimal config fixture --

def _make_config():
    """Create a minimal config-like object for testing canonical stages."""
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

    scale = NS(
        checkpoint_enabled=False,
        max_bytes_billed=None,
        canonical_index_clustering=["entity_uid"],
        canonical_index_partition_by=None,
    )

    clustering = NS(max_iterations=20)
    reconciliation = NS(clustering=clustering)

    config = NS(
        project=project,
        sources=[],
        reconciliation=reconciliation,
        scale=scale,
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table

    return config


class TestCanonicalIndexInitStage:
    """Tests for CanonicalIndexInitStage."""

    def test_name(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        assert stage.name == "canonical_index_init"

    def test_inputs_has_featured(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        assert "featured" in stage.inputs
        assert "featured" in stage.inputs["featured"].fq_name

    def test_outputs_has_canonical_index(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        assert "canonical_index" in stage.outputs
        assert "canonical_index" in stage.outputs["canonical_index"].fq_name

    def test_plan_returns_create_table_if_not_exists(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        exprs = stage.plan()

        assert len(exprs) == 1
        sql = exprs[0].render()

        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "canonical_index" in sql

    def test_plan_sql_references_featured_table(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        sql = stage.plan()[0].render()

        assert "featured" in sql

    def test_plan_sql_includes_cluster_id(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        sql = stage.plan()[0].render()

        assert "entity_uid AS cluster_id" in sql

    def test_plan_sql_where_false(self):
        config = _make_config()
        stage = CanonicalIndexInitStage(config)
        sql = stage.plan()[0].render()

        assert "WHERE FALSE" in sql


class TestCanonicalIndexPopulateStage:
    """Tests for CanonicalIndexPopulateStage."""

    def test_name(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        assert stage.name == "canonical_index_populate"

    def test_inputs_has_featured_and_clusters(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        inputs = stage.inputs

        assert "featured" in inputs
        assert "clusters" in inputs
        assert "featured" in inputs["featured"].fq_name
        assert "entity_clusters" in inputs["clusters"].fq_name

    def test_outputs_is_empty(self):
        """Outputs is empty because this stage modifies in-place."""
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        assert stage.outputs == {}

    def test_plan_returns_atomic_merge(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        exprs = stage.plan()

        assert len(exprs) == 1
        sql = exprs[0].render()

        assert "MERGE INTO" in sql
        assert "WHEN MATCHED AND" in sql
        assert "WHEN NOT MATCHED THEN" in sql
        assert "INSERT ROW" in sql

    def test_plan_sql_references_canonical_index(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        sql = stage.plan()[0].render()

        assert "canonical_index" in sql

    def test_plan_sql_references_cluster_table(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        sql = stage.plan()[0].render()

        assert "entity_clusters" in sql

    def test_plan_sql_references_featured_table(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        sql = stage.plan()[0].render()

        assert "featured" in sql

    def test_plan_sql_update_sets_cluster_id(self):
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        sql = stage.plan()[0].render()

        assert "UPDATE SET cluster_id" in sql

    def test_plan_sql_merge_uses_entity_uid_key(self):
        """MERGE joins on entity_uid to detect existing vs new entities."""
        config = _make_config()
        stage = CanonicalIndexPopulateStage(config)
        sql = stage.plan()[0].render()

        assert "ON ci.entity_uid = src.entity_uid" in sql

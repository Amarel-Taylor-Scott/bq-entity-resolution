"""Tests for ClusteringStage method dispatch (star, best_match, connected_components)."""

from bq_entity_resolution.stages.clustering import ClusteringStage


def _make_config(method="connected_components", max_iterations=20, incremental=False):
    """Create a minimal config for ClusteringStage testing."""
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
        name="customer_dedup",
    )

    clustering = NS(
        method=method,
        max_iterations=max_iterations,
        min_cluster_confidence=0.0,
    )

    reconciliation = NS(
        clustering=clustering,
        output=NS(type="resolved_entities"),
    )

    source = NS(
        name="crm",
        table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=[],
        passthrough_columns=[],
        joins=[],
        filter=None,
        partition_column=None,
        batch_size=None,
    )

    inc = NS(enabled=incremental) if incremental else None

    config = NS(
        project=project,
        sources=[source],
        reconciliation=reconciliation,
        incremental=inc,
        name="customer_dedup",
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table

    return config


class TestClusteringStageMethodDispatch:
    def test_connected_components_default(self):
        config = _make_config(method="connected_components")
        stage = ClusteringStage(config)
        exprs = stage.plan()
        sql = exprs[0].render()

        assert "DECLARE" in sql
        assert "WHILE" in sql
        assert "entity_uid" in sql

    def test_star_method(self):
        config = _make_config(method="star")
        stage = ClusteringStage(config)
        exprs = stage.plan()
        sql = exprs[0].render()

        assert "CREATE OR REPLACE TABLE" in sql
        assert "cluster_id" in sql
        # Star clustering should NOT use WHILE loops
        assert "WHILE" not in sql

    def test_best_match_method(self):
        config = _make_config(method="best_match")
        stage = ClusteringStage(config)
        exprs = stage.plan()
        sql = exprs[0].render()

        assert "CREATE OR REPLACE TABLE" in sql
        assert "cluster_id" in sql
        assert "LEAST" in sql
        # Best match should NOT use WHILE loops
        assert "WHILE" not in sql

    def test_stage_name(self):
        config = _make_config()
        stage = ClusteringStage(config)
        assert stage.name == "clustering"

    def test_inputs_have_all_matches_and_featured(self):
        config = _make_config()
        stage = ClusteringStage(config)
        inputs = stage.inputs
        assert "all_matches" in inputs
        assert "featured" in inputs

    def test_outputs_have_clusters(self):
        config = _make_config()
        stage = ClusteringStage(config)
        outputs = stage.outputs
        assert "clusters" in outputs

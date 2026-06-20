"""Tests for concrete pipeline stages.

These tests verify that stages produce valid SQL using the builders,
without requiring BigQuery or DuckDB.
"""


from bq_entity_resolution.stages.base import Stage
from bq_entity_resolution.stages.blocking import BlockingStage
from bq_entity_resolution.stages.features import FeatureEngineeringStage
from bq_entity_resolution.stages.matching import MatchingStage
from bq_entity_resolution.stages.reconciliation import (
    ClusteringStage,
    ClusterQualityStage,
    GoldOutputStage,
)
from bq_entity_resolution.stages.staging import StagingStage

# -- Minimal config fixture --

def _make_minimal_config():
    """Create a minimal PipelineConfig-like object for testing stages.

    Uses a simple namespace to avoid importing the full config schema
    (which would pull in many dependencies).
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

    col1 = NS(name="first_name")
    col2 = NS(name="last_name")

    source = NS(
        name="crm",
        table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=[col1, col2],
        passthrough_columns=[],
        joins=[],
        filter=None,
        partition_column=None,
        batch_size=None,
    )

    feat1 = NS(
        name="name_clean",
        function="name_clean",
        inputs=["first_name"],
        params=None,
    )

    feat_group = NS(features=[feat1])

    bk1 = NS(
        name="bk_soundex",
        function="soundex",
        inputs=["last_name"],
        params=None,
    )

    ck1 = NS(
        name="bk_name_dob",
        expression="CONCAT(UPPER(first_name), '_', UPPER(last_name))",
    )

    features_config = NS(
        groups=[feat_group],
        blocking_keys=[bk1],
        composite_keys=[ck1],
    )

    blocking_path = NS(
        keys=["bk_soundex"],
        lsh_keys=[],
        candidate_limit=0,
        bucket_size_limit=0,
    )

    blocking_config = NS(
        paths=[blocking_path],
        cross_batch=False,
    )

    comp1 = NS(
        name="name_exact",
        method="exact",
        left="first_name_clean",
        right="first_name_clean",
        weight=2.0,
        params=None,
        tf_enabled=False,
        tf_column="",
        tf_minimum_u=0.01,
        levels=[],
    )

    threshold = NS(
        method="score",
        min_score=1.0,
        match_threshold=None,
        log_prior_odds=0.0,
        min_matching_comparisons=0,
    )

    active_learning_config = NS(
        enabled=False,
        queue_size=100,
        uncertainty_window=0.3,
    )

    tier = NS(
        name="exact",
        blocking=blocking_config,
        comparisons=[comp1],
        threshold=threshold,
        hard_negatives=[],
        hard_positives=[],
        soft_signals=[],
        score_banding=NS(enabled=False, bands=[]),
        active_learning=active_learning_config,
        confidence=None,
    )

    incremental_config = NS(
        grace_period_hours=6,
        cursor_columns=["updated_at"],
    )

    canonical_selection = NS(
        method="completeness",
        source_priority=[],
        field_strategies=[],
        default_field_strategy="most_complete",
    )

    audit_trail = NS(enabled=False)
    clustering = NS(max_iterations=20)
    output = NS(
        include_match_metadata=True,
        entity_id_prefix="ENT",
        partition_column=None,
        cluster_columns=[],
        audit_trail=audit_trail,
    )
    reconciliation = NS(
        canonical_selection=canonical_selection,
        clustering=clustering,
        output=output,
        strategy="tier_priority",
    )

    monitoring = NS(
        audit_trail_enabled=False,
        blocking_metrics=NS(enabled=False),
        cluster_quality=NS(
            enabled=False,
            alert_max_cluster_size=100,
            abort_on_explosion=False,
        ),
        persist_sql_log=False,
    )

    scale = NS(
        checkpoint_enabled=False,
        max_bytes_billed=None,
    )

    embeddings = NS(enabled=False)

    feature_engineering = NS(
        entity_type_column="",
        groups=[feat_group],
        blocking_keys=[bk1],
        composite_keys=[ck1],
    )

    config = NS(
        project=project,
        sources=[source],
        features=features_config,
        feature_engineering=feature_engineering,
        incremental=incremental_config,
        reconciliation=reconciliation,
        monitoring=monitoring,
        scale=scale,
        embeddings=embeddings,
        link_type=None,
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table

    def enabled_tiers():
        return [tier]

    config.enabled_tiers = enabled_tiers

    # Effective signal merging (global + tier)
    config.effective_hard_negatives = lambda t: list(
        getattr(t, "hard_negatives", [])
    )
    config.effective_hard_positives = lambda t: list(
        getattr(t, "hard_positives", [])
    )
    config.effective_soft_signals = lambda t: list(
        getattr(t, "soft_signals", [])
    )

    return config, source, tier


# -- Stage tests --


class TestStagingStage:
    def test_name(self):
        config, source, _ = _make_minimal_config()
        stage = StagingStage(source, config)
        assert stage.name == "staging_crm"

    def test_inputs(self):
        config, source, _ = _make_minimal_config()
        stage = StagingStage(source, config)
        assert "source" in stage.inputs
        assert "customers" in stage.inputs["source"].fq_name

    def test_outputs(self):
        config, source, _ = _make_minimal_config()
        stage = StagingStage(source, config)
        assert "staged" in stage.outputs
        assert "staged_crm" in stage.outputs["staged"].fq_name

    def test_plan_generates_sql(self):
        config, source, _ = _make_minimal_config()
        stage = StagingStage(source, config)
        exprs = stage.plan(watermark=None, full_refresh=True)
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "FARM_FINGERPRINT" in sql
        assert "crm" in sql

    def test_validate_ok(self):
        config, source, _ = _make_minimal_config()
        stage = StagingStage(source, config)
        assert stage.validate() == []

    def test_is_stage(self):
        config, source, _ = _make_minimal_config()
        stage = StagingStage(source, config)
        assert isinstance(stage, Stage)


class TestFeatureEngineeringStage:
    def test_name(self):
        config, _, _ = _make_minimal_config()
        stage = FeatureEngineeringStage(config)
        assert stage.name == "feature_engineering"

    def test_inputs_include_staged_sources(self):
        config, _, _ = _make_minimal_config()
        stage = FeatureEngineeringStage(config)
        assert "staged_crm" in stage.inputs

    def test_outputs_include_featured(self):
        config, _, _ = _make_minimal_config()
        stage = FeatureEngineeringStage(config)
        assert "featured" in stage.outputs

    def test_plan_generates_sql(self):
        config, _, _ = _make_minimal_config()
        stage = FeatureEngineeringStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "features_pass1" in sql
        assert "featured" in sql


class TestBlockingStage:
    def test_name(self):
        config, _, tier = _make_minimal_config()
        stage = BlockingStage(tier, 0, config)
        assert stage.name == "blocking_exact"

    def test_plan_generates_sql(self):
        config, _, tier = _make_minimal_config()
        stage = BlockingStage(tier, 0, config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "intra_path_0" in sql
        assert "bk_soundex" in sql

    def test_plan_with_exclusion(self):
        config, _, tier = _make_minimal_config()
        stage = BlockingStage(tier, 1, config)
        exprs = stage.plan(excluded_pairs_table="proj.ds.prior_matches")
        sql = exprs[0].render()
        assert "LEFT JOIN" in sql
        assert "prior_matches" in sql


class TestMatchingStage:
    def test_name(self):
        config, _, tier = _make_minimal_config()
        stage = MatchingStage(tier, 0, config)
        assert stage.name == "matching_exact"

    def test_plan_generates_sum_scoring(self):
        config, _, tier = _make_minimal_config()
        stage = MatchingStage(tier, 0, config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "total_score" in sql
        assert "match_score_" in sql


class TestClusteringStage:
    def test_name(self):
        config, _, _ = _make_minimal_config()
        stage = ClusteringStage(config)
        assert stage.name == "clustering"

    def test_plan_generates_bq_scripting(self):
        config, _, _ = _make_minimal_config()
        stage = ClusteringStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "DECLARE" in sql
        assert "WHILE" in sql
        assert "cluster_id" in sql


class TestGoldOutputStage:
    def test_name(self):
        config, _, _ = _make_minimal_config()
        stage = GoldOutputStage(config)
        assert stage.name == "gold_output"

    def test_plan_generates_sql(self):
        config, _, _ = _make_minimal_config()
        stage = GoldOutputStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "canonical" in sql
        assert "resolved_entity_id" in sql


class TestClusterQualityStage:
    def test_name(self):
        config, _, _ = _make_minimal_config()
        stage = ClusterQualityStage(config)
        assert stage.name == "cluster_quality"

    def test_plan_generates_metrics(self):
        config, _, _ = _make_minimal_config()
        stage = ClusterQualityStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "singleton_ratio" in sql
        assert "max_cluster_size" in sql

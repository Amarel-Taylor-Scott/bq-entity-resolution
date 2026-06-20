"""Tests for label feedback loop DAG wiring."""

from bq_entity_resolution.pipeline.dag import build_pipeline_dag


def _make_config_with_feedback():
    """Build a minimal config with active learning + label feedback enabled."""
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
    source = NS(
        name="crm",
        table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=[col1],
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
    bk1 = NS(name="bk_soundex", function="soundex", inputs=["last_name"], params=None)
    ck1 = NS(name="bk_name", expression="UPPER(first_name)")
    features_config = NS(
        groups=[feat_group],
        blocking_keys=[bk1],
        composite_keys=[ck1],
    )

    blocking_path = NS(keys=["bk_soundex"], lsh_keys=[], candidate_limit=0)
    blocking_config = NS(paths=[blocking_path], cross_batch=False)

    comp1 = NS(
        name="name_exact", method="exact",
        left="first_name", right="first_name",
        weight=2.0, params=None, tf_enabled=False,
        tf_column="", tf_minimum_u=0.01, levels=[],
    )

    threshold = NS(
        method="score", min_score=1.0,
        match_threshold=None, log_prior_odds=0.0,
        min_matching_comparisons=0,
    )

    label_feedback = NS(enabled=True, auto_retrain=True, min_labels_for_retrain=50)
    al = NS(
        enabled=True,
        queue_size=100,
        uncertainty_window=0.3,
        label_feedback=label_feedback,
    )

    tier = NS(
        name="exact",
        blocking=blocking_config,
        comparisons=[comp1],
        threshold=threshold,
        hard_negatives=[],
        soft_signals=[],
        active_learning=al,
        confidence=None,
    )

    incremental = NS(grace_period_hours=6, cursor_columns=["updated_at"])
    canonical_selection = NS(method="completeness", source_priority=[])
    clustering = NS(max_iterations=20)
    reconciliation = NS(
        canonical_selection=canonical_selection,
        clustering=clustering,
    )
    output = NS(
        include_match_metadata=True,
        entity_id_prefix="ent",
        partition_column=None,
        cluster_columns=[],
    )
    monitoring = NS(
        audit_trail_enabled=False,
        blocking_metrics=NS(enabled=False),
        cluster_quality=NS(
            enabled=False, alert_max_cluster_size=100, abort_on_explosion=False,
        ),
        persist_sql_log=False,
    )
    scale = NS(checkpoint_enabled=False, max_bytes_billed=None)
    embeddings = NS(enabled=False)

    config = NS(
        project=project,
        sources=[source],
        features=features_config,
        incremental=incremental,
        reconciliation=reconciliation,
        output=output,
        monitoring=monitoring,
        scale=scale,
        embeddings=embeddings,
        link_type=None,
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table
    config.enabled_tiers = lambda: [tier]
    return config


def _make_config_al_no_feedback():
    """Config with active learning enabled but label feedback disabled."""
    config = _make_config_with_feedback()
    tier = config.enabled_tiers()[0]
    tier.active_learning.label_feedback.enabled = False
    return config


class TestDAGFeedbackWiring:
    """Test that label ingestion stages are wired into the DAG."""

    def test_label_ingestion_stage_in_dag(self):
        """When label feedback is enabled, LabelIngestionStage is in the DAG."""
        config = _make_config_with_feedback()
        dag = build_pipeline_dag(config)
        assert "label_ingestion_exact" in dag.stage_names

    def test_label_ingestion_depends_on_active_learning(self):
        """Label ingestion depends on the active learning stage."""
        config = _make_config_with_feedback()
        dag = build_pipeline_dag(config)
        deps = dag.get_dependencies("label_ingestion_exact")
        assert "active_learning_exact" in deps

    def test_active_learning_in_dag(self):
        """ActiveLearningStage is present when enabled."""
        config = _make_config_with_feedback()
        dag = build_pipeline_dag(config)
        assert "active_learning_exact" in dag.stage_names

    def test_no_label_ingestion_when_feedback_disabled(self):
        """No LabelIngestionStage when label_feedback.enabled is False."""
        config = _make_config_al_no_feedback()
        dag = build_pipeline_dag(config)
        assert "label_ingestion_exact" not in dag.stage_names
        assert "active_learning_exact" in dag.stage_names

    def test_active_learning_constructor_fixed(self):
        """ActiveLearningStage is created with correct (tier, config) args."""
        config = _make_config_with_feedback()
        dag = build_pipeline_dag(config)
        # If this doesn't raise TypeError, the constructor bug is fixed
        al_stage = dag.get_stage("active_learning_exact")
        assert al_stage.name == "active_learning_exact"

    def test_label_ingestion_after_active_learning(self):
        """Label ingestion comes after active learning in execution order."""
        config = _make_config_with_feedback()
        dag = build_pipeline_dag(config)
        names = dag.stage_names
        assert names.index("active_learning_exact") < names.index("label_ingestion_exact")

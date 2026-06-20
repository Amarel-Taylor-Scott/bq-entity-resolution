"""Tests for the high-level Pipeline API."""


from bq_entity_resolution.backends.protocol import QueryResult
from bq_entity_resolution.pipeline.pipeline import Pipeline

# -- Mock backend --


class MockBackend:
    def __init__(self):
        self.executed = []

    @property
    def dialect(self):
        return "bigquery"

    def execute(self, sql, label=""):
        self.executed.append(sql)
        return QueryResult(rows_affected=10)

    def execute_script(self, sql, label=""):
        self.executed.append(sql)
        return QueryResult(rows_affected=5)

    def execute_and_fetch(self, sql, label=""):
        return [{"count": 100}]

    def table_exists(self, ref):
        return True

    def row_count(self, ref):
        return 100


# -- Config fixture --


def _make_config():
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
    bk1 = NS(
        name="bk_soundex",
        function="soundex",
        inputs=["last_name"],
        params=None,
    )
    ck1 = NS(
        name="bk_name",
        expression="UPPER(first_name)",
    )
    features_config = NS(
        groups=[feat_group],
        blocking_keys=[bk1],
        composite_keys=[ck1],
        entity_type_column=None,
    )

    blocking_path = NS(keys=["bk_soundex"], lsh_keys=[], candidate_limit=0, bucket_size_limit=0)
    blocking_config = NS(paths=[blocking_path], cross_batch=False)
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
    al = NS(enabled=False, queue_size=100, uncertainty_window=0.3)
    tier = NS(
        name="exact",
        blocking=blocking_config,
        comparisons=[comp1],
        threshold=threshold,
        hard_negatives=[],
        hard_positives=[],
        soft_signals=[],
        active_learning=al,
        confidence=None,
        score_banding=NS(enabled=False, bands=[]),
    )

    incremental = NS(
        grace_period_hours=6, cursor_columns=["updated_at"],
        drain_mode=False, drain_max_iterations=100,
    )
    canonical_selection = NS(
        method="completeness",
        source_priority=[],
        field_strategies=[],
        default_field_strategy="most_complete",
    )
    clustering = NS(max_iterations=20)
    audit_trail = NS(enabled=False)
    recon_output = NS(
        include_match_metadata=True,
        entity_id_prefix="ent",
        partition_column=None,
        cluster_columns=[],
        audit_trail=audit_trail,
    )
    reconciliation = NS(
        canonical_selection=canonical_selection,
        clustering=clustering,
        output=recon_output,
        strategy="canonical",
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
            enabled=False,
            alert_max_cluster_size=100,
            abort_on_explosion=False,
        ),
        persist_sql_log=False,
    )
    scale = NS(checkpoint_enabled=False, max_bytes_billed=None)
    embeddings = NS(enabled=False)
    execution = NS(skip_stages=[])

    config = NS(
        project=project,
        sources=[source],
        features=features_config,
        feature_engineering=features_config,
        incremental=incremental,
        reconciliation=reconciliation,
        output=output,
        monitoring=monitoring,
        scale=scale,
        embeddings=embeddings,
        execution=execution,
        link_type=None,
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table
    config.enabled_tiers = lambda: [tier]
    config.effective_hard_negatives = lambda t: list(t.hard_negatives)
    config.effective_hard_positives = lambda t: list(t.hard_positives)
    config.effective_soft_signals = lambda t: list(t.soft_signals)
    return config


# -- Tests --


class TestPipeline:
    def test_creation(self):
        config = _make_config()
        pipeline = Pipeline(config, quality_gates=[])
        assert pipeline.config is config
        assert len(pipeline.stage_names) >= 6

    def test_dag_property(self):
        config = _make_config()
        pipeline = Pipeline(config, quality_gates=[])
        assert pipeline.dag is not None
        assert len(pipeline.dag) >= 6

    def test_validate(self):
        config = _make_config()
        pipeline = Pipeline(config, quality_gates=[])
        violations = pipeline.validate()
        # Should not have hard errors (external tables are OK)
        errors = [v for v in violations if v.severity == "error"]
        assert errors == []

    def test_plan(self):
        config = _make_config()
        pipeline = Pipeline(config, quality_gates=[])
        plan = pipeline.plan(full_refresh=True)
        assert plan.total_sql_count > 0
        assert len(plan.stages) >= 6

    def test_execute(self):
        config = _make_config()
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])
        plan = pipeline.plan(full_refresh=True)
        result = pipeline.execute(plan, backend=backend)
        assert result.success
        assert len(backend.executed) > 0

    def test_run_convenience(self):
        config = _make_config()
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])
        result = pipeline.run(
            backend=backend,
            full_refresh=True,
            run_id="test_123",
        )
        assert result.success
        assert result.run_id == "test_123"
        assert len(result.completed_stages) >= 6

    def test_run_skip_stages(self):
        config = _make_config()
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])
        result = pipeline.run(
            backend=backend,
            full_refresh=True,
            skip_stages={"staging_crm", "feature_engineering"},
        )
        assert result.success
        assert "staging_crm" not in result.completed_stages
        assert "feature_engineering" not in result.completed_stages

    def test_external_tables(self):
        config = _make_config()
        pipeline = Pipeline(config, quality_gates=[])
        externals = pipeline._external_tables()
        assert "test-proj.raw.customers" in externals
        # all_matches_table is now produced by the accumulation stage, not external
        assert "test-proj.silver.all_matched_pairs" not in externals

    def test_estimate_cost(self):
        """estimate_cost() returns CostEstimate with per-stage breakdown."""
        from bq_entity_resolution.pipeline.pipeline import CostEstimate

        config = _make_config()

        class EstimateBackend(MockBackend):
            def estimate_bytes(self, sql, label=""):
                return 1024 * 1024  # 1 MB per statement

        backend = EstimateBackend()
        pipeline = Pipeline(config, quality_gates=[])
        estimate = pipeline.estimate_cost(backend=backend, full_refresh=True)
        assert isinstance(estimate, CostEstimate)
        assert estimate.total_bytes_processed > 0
        assert len(estimate.per_stage) >= 6
        assert estimate.total_gb > 0
        assert estimate.estimated_cost_usd >= 0

    def test_estimate_cost_zero_for_duckdb(self):
        """estimate_cost() returns zero for backends without dry-run support."""
        from bq_entity_resolution.pipeline.pipeline import CostEstimate

        config = _make_config()

        class NoCostBackend(MockBackend):
            def estimate_bytes(self, sql, label=""):
                return 0

        backend = NoCostBackend()
        pipeline = Pipeline(config, quality_gates=[])
        estimate = pipeline.estimate_cost(backend=backend, full_refresh=True)
        assert isinstance(estimate, CostEstimate)
        assert estimate.total_bytes_processed == 0
        assert estimate.estimated_cost_usd == 0.0

    def test_dry_run_returns_cost_estimate(self):
        """Pipeline.run(dry_run=True) returns CostEstimate instead of PipelineResult."""
        from bq_entity_resolution.pipeline.pipeline import CostEstimate

        config = _make_config()

        class EstimateBackend(MockBackend):
            def estimate_bytes(self, sql, label=""):
                return 500_000

        backend = EstimateBackend()
        pipeline = Pipeline(config, quality_gates=[])
        result = pipeline.run(backend=backend, full_refresh=True, dry_run=True)
        assert isinstance(result, CostEstimate)
        assert result.total_bytes_processed > 0

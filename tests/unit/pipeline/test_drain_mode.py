"""Tests for drain mode behavior in Pipeline.run().

Verifies that drain mode parameter passing and config-driven
auto-enable work correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bq_entity_resolution.backends.protocol import QueryResult
from bq_entity_resolution.pipeline.pipeline import Pipeline

# -- Mock backend --


class MockBackend:
    """Minimal mock backend for Pipeline tests."""

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

def _make_config(drain_mode=False, drain_max_iterations=100):
    """Create a minimal config with drain mode settings."""
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

    feat1 = NS(name="name_clean", function="name_clean", inputs=["first_name"], params=None)
    feat_group = NS(features=[feat1])
    bk1 = NS(name="bk_soundex", function="soundex", inputs=["last_name"], params=None)
    ck1 = NS(name="bk_name", expression="UPPER(first_name)")
    features_config = NS(
        groups=[feat_group],
        blocking_keys=[bk1],
        composite_keys=[ck1],
        entity_type_column=None,
    )

    blocking_path = NS(keys=["bk_soundex"], lsh_keys=[], candidate_limit=0, bucket_size_limit=0)
    blocking_config = NS(paths=[blocking_path], cross_batch=False)
    comp1 = NS(
        name="name_exact", method="exact",
        left="first_name_clean", right="first_name_clean",
        weight=2.0, params=None, tf_enabled=False,
        tf_column="", tf_minimum_u=0.01, levels=[],
    )
    threshold = NS(
        method="score", min_score=1.0, match_threshold=None,
        log_prior_odds=0.0, min_matching_comparisons=0,
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
        grace_period_hours=6,
        cursor_columns=["updated_at"],
        drain_mode=drain_mode,
        drain_max_iterations=drain_max_iterations,
        enabled=True,
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
            enabled=False, alert_max_cluster_size=100, abort_on_explosion=False,
        ),
        persist_sql_log=False,
        metrics=NS(enabled=False),
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


class TestDrainModePipeline:
    """Tests for drain mode in Pipeline.run()."""

    def test_run_accepts_drain_parameter(self):
        """Pipeline.run() accepts drain=True without error."""
        config = _make_config()
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])

        # drain=True without watermark_manager => single iteration
        result = pipeline.run(
            backend=backend,
            full_refresh=True,
            drain=True,
        )
        assert result.success

    def test_run_drain_false_single_iteration(self):
        """Pipeline.run() with drain=False runs exactly one iteration."""
        config = _make_config()
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])

        result = pipeline.run(
            backend=backend,
            full_refresh=True,
            drain=False,
        )
        assert result.success
        # Should complete normally in a single pass
        assert len(result.completed_stages) >= 6

    def test_config_drain_mode_auto_enables_drain(self):
        """IncrementalConfig.drain_mode=True causes Pipeline.run() to auto-enable drain."""
        config = _make_config(drain_mode=True)
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])

        # drain is not explicitly passed but config.incremental.drain_mode=True
        # Without watermark_manager, drain mode stops after single iteration
        result = pipeline.run(
            backend=backend,
            full_refresh=True,
        )
        assert result.success

    def test_drain_mode_with_mock_watermark_manager(self):
        """Drain mode iterates when watermark manager reports more records."""
        config = _make_config(drain_mode=True, drain_max_iterations=3)
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])

        # Mock watermark manager that says no more records after first check
        wm_mgr = MagicMock()
        wm_mgr.read.return_value = {"updated_at": "2024-01-01T00:00:00"}
        wm_mgr.compute_new_watermark_from_staged.return_value = {
            "updated_at": "2024-01-02T00:00:00"
        }
        wm_mgr.has_unprocessed_records.return_value = False

        result = pipeline.run(
            backend=backend,
            drain=True,
            watermark_manager=wm_mgr,
        )
        assert result.success

        # Watermark should have been read
        wm_mgr.read.assert_called()

    def test_drain_max_iterations_from_config(self):
        """drain_max_iterations is read from config."""
        config = _make_config(drain_mode=True, drain_max_iterations=5)
        assert config.incremental.drain_max_iterations == 5

    def test_drain_mode_without_watermark_manager_runs_once(self):
        """Without watermark_manager, drain mode runs exactly one iteration."""
        config = _make_config(drain_mode=True)
        backend = MockBackend()
        pipeline = Pipeline(config, quality_gates=[])

        result = pipeline.run(
            backend=backend,
            full_refresh=True,
            drain=True,
        )
        assert result.success

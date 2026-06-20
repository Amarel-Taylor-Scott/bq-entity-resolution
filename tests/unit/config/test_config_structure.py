"""Structural tests for all config models.

Verifies that every config model has the expected fields, defaults,
validators, and serialization behavior. These tests catch accidental
field deletions, naming changes, and broken defaults.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bq_entity_resolution.config.models.blocking import (
    BlockingPathDef,
    TierBlockingConfig,
)
from bq_entity_resolution.config.models.features import (
    BlockingKeyDef,
    CompoundDetectionConfig,
    EnrichmentJoinConfig,
    FeatureDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
)
from bq_entity_resolution.config.models.infrastructure import (
    ClusterQualityConfig,
    EmbeddingConfig,
    ExecutionConfig,
    HashCursorConfig,
    IncrementalConfig,
    MonitoringConfig,
    PartitionCursorConfig,
    ProjectConfig,
    ScaleConfig,
)
from bq_entity_resolution.config.models.matching import (
    ActiveLearningConfig,
    ComparisonDef,
    ComparisonLevelDef,
    HardNegativeDef,
    HardPositiveDef,
    LabelFeedbackConfig,
    MatchingTierConfig,
    ScoreBandDef,
    ScoreBandingConfig,
    SoftSignalDef,
    TermFrequencyConfig,
    ThresholdConfig,
    TrainingConfig,
)
from bq_entity_resolution.config.models.pipeline import PipelineConfig
from bq_entity_resolution.config.models.reconciliation import (
    AuditTrailConfig,
    CanonicalSelectionConfig,
    ClusteringConfig,
    ConfidenceShapingConfig,
    OutputConfig,
    ReconciliationConfig,
)
from bq_entity_resolution.config.models.source import (
    ColumnMapping,
    SourceConfig,
)

# ---------------------------------------------------------------------------
# Source models
# ---------------------------------------------------------------------------


class TestColumnMapping:
    def test_minimal(self):
        col = ColumnMapping(name="email")
        assert col.name == "email"
        assert col.role is None

    def test_with_role(self):
        col = ColumnMapping(name="first_name", role="first_name")
        assert col.role == "first_name"


class TestSourceConfig:
    def test_minimal(self):
        src = SourceConfig(
            name="crm",
            table="proj.ds.customers",
            unique_key="id",
            updated_at="ts",
            columns=[ColumnMapping(name="email")],
        )
        assert src.name == "crm"
        assert src.passthrough_columns == []
        assert src.entity_type is None

    def test_passthrough_columns(self):
        src = SourceConfig(
            name="crm",
            table="t",
            unique_key="id",
            updated_at="ts",
            columns=[ColumnMapping(name="email")],
            passthrough_columns=["raw_json"],
        )
        assert "raw_json" in src.passthrough_columns


# ---------------------------------------------------------------------------
# Feature models
# ---------------------------------------------------------------------------


class TestFeatureDef:
    def test_input_normalization(self):
        """Singular 'input' should be normalized to 'inputs' list."""
        feat = FeatureDef(name="clean", function="name_clean", input="first_name")
        assert feat.inputs == ["first_name"]

    def test_multi_input(self):
        feat = FeatureDef(name="concat", function="concat", inputs=["a", "b"])
        assert feat.inputs == ["a", "b"]


class TestFeatureGroupConfig:
    def test_defaults(self):
        group = FeatureGroupConfig()
        assert group.enabled is True
        assert group.features == []


class TestBlockingKeyDef:
    def test_required_fields(self):
        bk = BlockingKeyDef(name="bk_email", function="farm_fingerprint", inputs=["email"])
        assert bk.name == "bk_email"
        assert bk.function == "farm_fingerprint"


class TestEnrichmentJoinConfig:
    def test_all_fields(self):
        ej = EnrichmentJoinConfig(
            name="census",
            table="proj.ds.lookup",
            lookup_key="fp",
            source_key_function="farm_fingerprint_concat",
            source_key_inputs=["addr", "city"],
            columns=["lat", "lon"],
            column_prefix="census_",
            match_flag="has_match",
        )
        assert ej.column_prefix == "census_"
        assert ej.match_flag == "has_match"
        assert ej.type == "LEFT"

    def test_defaults(self):
        ej = EnrichmentJoinConfig(
            name="x", table="t", lookup_key="k",
            source_key_function="f", source_key_inputs=["a"],
            columns=["c"],
        )
        assert ej.column_prefix == ""
        assert ej.match_flag == ""
        assert ej.type == "LEFT"


class TestCompoundDetectionConfig:
    def test_defaults(self):
        cd = CompoundDetectionConfig()
        assert cd.enabled is False
        assert cd.action == "flag"
        assert cd.flag_column == "is_compound_name"


class TestFeatureEngineeringConfig:
    def test_all_feature_names_includes_compound(self):
        cfg = FeatureEngineeringConfig(
            compound_detection=CompoundDetectionConfig(enabled=True),
        )
        names = cfg.all_feature_names()
        assert "is_compound_name" in names
        assert "compound_pattern" in names

    def test_all_feature_names_includes_enrichment_outputs(self):
        cfg = FeatureEngineeringConfig(
            enrichment_joins=[
                EnrichmentJoinConfig(
                    name="geo", table="t", lookup_key="k",
                    source_key_function="f", source_key_inputs=["a"],
                    columns=["lat", "lon"],
                    column_prefix="census_",
                    match_flag="has_geo",
                ),
            ],
        )
        names = cfg.all_feature_names()
        assert "census_lat" in names
        assert "census_lon" in names
        assert "has_geo" in names

    def test_all_groups_includes_extra(self):
        cfg = FeatureEngineeringConfig(
            extra_groups={
                "identity": FeatureGroupConfig(
                    features=[FeatureDef(name="ssn", function="ssn_clean", input="ssn")]
                ),
            },
        )
        groups = cfg.all_groups()
        # 3 built-in + 1 extra = 4
        assert len(groups) == 4

    def test_entity_type_column_default(self):
        cfg = FeatureEngineeringConfig()
        assert cfg.entity_type_column == ""


# ---------------------------------------------------------------------------
# Blocking models
# ---------------------------------------------------------------------------


class TestBlockingPathDef:
    def test_defaults(self):
        bp = BlockingPathDef(keys=["bk_email"])
        assert bp.lsh_keys == []
        assert bp.candidate_limit == 200
        assert bp.bucket_size_limit == 10_000
        assert bp.lsh_min_bands == 1

    def test_with_lsh(self):
        bp = BlockingPathDef(keys=["bk_email"], lsh_keys=["lsh_embedding"])
        assert bp.lsh_keys == ["lsh_embedding"]


class TestTierBlockingConfig:
    def test_has_cross_batch(self):
        bc = TierBlockingConfig(
            paths=[BlockingPathDef(keys=["bk"])]
        )
        assert isinstance(bc.cross_batch, bool)


# ---------------------------------------------------------------------------
# Matching models
# ---------------------------------------------------------------------------


class TestComparisonLevelDef:
    def test_probability_validation(self):
        with pytest.raises(ValidationError, match="Probability"):
            ComparisonLevelDef(label="bad", m=1.5)

    def test_valid_level(self):
        lvl = ComparisonLevelDef(
            label="exact", method="exact",
            m=0.9, u=0.1, tf_adjusted=False,
        )
        assert lvl.sql_expr is None
        assert lvl.log_weight is None


class TestComparisonDef:
    def test_inline_requires_left_and_method(self):
        with pytest.raises(ValidationError, match="left, method"):
            ComparisonDef()

    def test_inline_requires_method(self):
        with pytest.raises(ValidationError, match="method"):
            ComparisonDef(left="email")

    def test_ref_bypasses_validation(self):
        comp = ComparisonDef(ref="email_exact")
        assert comp.ref == "email_exact"
        assert comp.left == ""  # Not filled yet

    def test_inline_with_all_fields(self):
        comp = ComparisonDef(
            left="email", right="email", method="exact", weight=5.0,
        )
        assert comp.weight == 5.0

    def test_tf_adjustment(self):
        comp = ComparisonDef(
            left="name", method="exact",
            tf_adjustment=TermFrequencyConfig(enabled=True),
        )
        assert comp.tf_adjustment.enabled is True

    def test_weight_mode_default(self):
        comp = ComparisonDef(left="x", method="exact")
        assert comp.weight_mode == "manual"


class TestThresholdConfig:
    def test_defaults(self):
        t = ThresholdConfig()
        assert t.method == "sum"
        assert t.min_score == 0.0
        assert t.match_threshold is None
        assert t.log_prior_odds == 0.0

    def test_fellegi_sunter(self):
        t = ThresholdConfig(
            method="fellegi_sunter",
            match_threshold=8.0,
            log_prior_odds=-3.0,
        )
        assert t.method == "fellegi_sunter"


class TestHardNegativeDef:
    def test_defaults(self):
        hn = HardNegativeDef(left="state", method="different")
        assert hn.action == "disqualify"
        assert hn.severity == "hn2_structural"
        assert hn.entity_type_condition is None
        assert hn.category == "general"
        assert hn.requires_overrides == 0

    def test_all_severities(self):
        for sev in ["hn1_critical", "hn2_structural", "hn3_identity", "hn4_contextual"]:
            hn = HardNegativeDef(left="x", method="different", severity=sev)
            assert hn.severity == sev


class TestHardPositiveDef:
    def test_defaults(self):
        hp = HardPositiveDef(left="ssn", method="exact")
        assert hp.action == "boost"
        assert hp.boost == 5.0
        assert hp.target_band == "HIGH"


class TestSoftSignalDef:
    def test_defaults(self):
        ss = SoftSignalDef(left="state", method="exact")
        assert ss.bonus == 1.0
        assert ss.entity_type_condition is None


class TestScoreBandDef:
    def test_required_fields(self):
        sb = ScoreBandDef(name="HIGH", min_score=8.0)
        assert sb.max_score == 999999.0
        assert sb.action == "accept"


class TestScoreBandingConfig:
    def test_defaults(self):
        sbc = ScoreBandingConfig()
        assert sbc.enabled is False
        assert sbc.bands == []


class TestTrainingConfig:
    def test_defaults(self):
        tc = TrainingConfig()
        assert tc.method == "none"
        assert tc.em_max_iterations == 10

    def test_em(self):
        tc = TrainingConfig(method="em", em_sample_size=50000)
        assert tc.em_sample_size == 50000


class TestLabelFeedbackConfig:
    def test_defaults(self):
        lf = LabelFeedbackConfig()
        assert lf.enabled is False
        assert lf.min_labels_for_retrain == 50


class TestActiveLearningConfig:
    def test_defaults(self):
        al = ActiveLearningConfig()
        assert al.enabled is False
        assert al.queue_size == 200


class TestMatchingTierConfig:
    def test_minimal_tier(self):
        tier = MatchingTierConfig(
            name="exact",
            blocking=TierBlockingConfig(
                paths=[BlockingPathDef(keys=["bk"])]
            ),
            comparisons=[
                ComparisonDef(left="email", method="exact", weight=5.0)
            ],
            threshold=ThresholdConfig(min_score=5.0),
        )
        assert tier.name == "exact"
        assert tier.enabled is True
        assert tier.hard_negatives == []
        assert tier.hard_positives == []
        assert tier.soft_signals == []
        assert tier.score_banding.enabled is False
        assert tier.confidence is None

    def test_invalid_tier_name(self):
        with pytest.raises(ValidationError, match="alphanumeric"):
            MatchingTierConfig(
                name="tier with spaces",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk"])]
                ),
                comparisons=[ComparisonDef(left="x", method="exact")],
                threshold=ThresholdConfig(),
            )


# ---------------------------------------------------------------------------
# Reconciliation models
# ---------------------------------------------------------------------------


class TestClusteringConfig:
    def test_defaults(self):
        cc = ClusteringConfig()
        assert cc.method == "connected_components"
        assert cc.max_iterations == 20

    def test_alternative_methods(self):
        for method in ["star", "best_match"]:
            cc = ClusteringConfig(method=method)
            assert cc.method == method


class TestCanonicalSelectionConfig:
    def test_defaults(self):
        cs = CanonicalSelectionConfig()
        assert cs.method == "completeness"
        assert cs.field_strategies == []


class TestConfidenceShapingConfig:
    def test_defaults(self):
        csc = ConfidenceShapingConfig()
        assert csc.group_size_penalty is False
        assert csc.hub_node_detection is False


class TestAuditTrailConfig:
    def test_defaults(self):
        at = AuditTrailConfig()
        assert at.enabled is False
        assert at.include_individual_scores is True


class TestOutputConfig:
    def test_defaults(self):
        oc = OutputConfig()
        assert oc.include_match_metadata is True
        assert oc.entity_id_prefix == "ENT"
        assert oc.audit_trail.enabled is False

    def test_audit_trail_nested(self):
        oc = OutputConfig(audit_trail=AuditTrailConfig(enabled=True))
        assert oc.audit_trail.enabled is True


class TestReconciliationConfig:
    def test_defaults(self):
        rc = ReconciliationConfig()
        assert rc.strategy == "tier_priority"
        assert rc.clustering.method == "connected_components"
        assert rc.output.entity_id_prefix == "ENT"
        assert rc.confidence_shaping.group_size_penalty is False


# ---------------------------------------------------------------------------
# Infrastructure models
# ---------------------------------------------------------------------------


class TestProjectConfig:
    def test_required_fields(self):
        pc = ProjectConfig(name="test", bq_project="proj")
        assert pc.bq_dataset_bronze == "er_bronze"
        assert pc.bq_dataset_silver == "er_silver"
        assert pc.bq_dataset_gold == "er_gold"
        assert pc.udf_dataset == "er_udfs"


class TestIncrementalConfig:
    def test_defaults(self):
        ic = IncrementalConfig()
        assert ic.enabled is True
        assert ic.cursor_mode == "ordered"
        assert ic.batch_size == 2_000_000

    def test_hash_cursor(self):
        ic = IncrementalConfig(
            hash_cursor=HashCursorConfig(column="policy_id", modulus=500)
        )
        assert ic.hash_cursor.modulus == 500


class TestPartitionCursorConfig:
    def test_strategies(self):
        for strategy in ["range", "equality", "in_list"]:
            pc = PartitionCursorConfig(column="state", strategy=strategy)
            assert pc.strategy == strategy


class TestMonitoringConfig:
    def test_defaults(self):
        mc = MonitoringConfig()
        assert mc.log_level == "INFO"
        assert mc.log_format == "json"
        assert mc.blocking_metrics.enabled is False
        assert mc.cluster_quality.enabled is False

    def test_cluster_quality(self):
        mc = MonitoringConfig(
            cluster_quality=ClusterQualityConfig(enabled=True, alert_max_cluster_size=50)
        )
        assert mc.cluster_quality.alert_max_cluster_size == 50


class TestScaleConfig:
    def test_defaults(self):
        sc = ScaleConfig()
        assert sc.max_bytes_billed is None
        assert sc.staging_clustering == ["entity_uid"]
        assert sc.featured_table_clustering == []

    def test_custom(self):
        sc = ScaleConfig(
            staging_partition_by="DATE(source_updated_at)",
            max_bytes_billed=10_000_000_000,
        )
        assert sc.staging_partition_by is not None


class TestExecutionConfig:
    def test_defaults(self):
        ec = ExecutionConfig()
        assert ec.allow_udfs is True
        assert ec.skip_stages == []

    def test_disable_udfs(self):
        ec = ExecutionConfig(allow_udfs=False)
        assert ec.allow_udfs is False

    def test_skip_stages(self):
        ec = ExecutionConfig(skip_stages=["cluster_quality", "term_frequencies"])
        assert len(ec.skip_stages) == 2


class TestEmbeddingConfig:
    def test_defaults(self):
        ec = EmbeddingConfig()
        assert ec.enabled is False
        assert ec.model == "text-embedding-004"
        assert ec.dimensions == 768


# ---------------------------------------------------------------------------
# Pipeline model
# ---------------------------------------------------------------------------


class TestPipelineConfig:
    def _make_fe(self, *bk_names):
        """Create feature_engineering with blocking keys."""
        return FeatureEngineeringConfig(
            blocking_keys=[
                BlockingKeyDef(name=n, function="farm_fingerprint", inputs=["x"])
                for n in bk_names
            ],
        )

    def test_minimal(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[
                SourceConfig(
                    name="crm", table="proj.ds.t", unique_key="id",
                    updated_at="ts",
                    columns=[ColumnMapping(name="email")],
                ),
            ],
            feature_engineering=self._make_fe("bk_email"),
            matching_tiers=[
                MatchingTierConfig(
                    name="exact",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk_email"])]
                    ),
                    comparisons=[
                        ComparisonDef(left="email", method="exact", weight=5.0)
                    ],
                    threshold=ThresholdConfig(min_score=5.0),
                ),
            ],
        )
        assert config.project.name == "test"
        assert len(config.sources) == 1
        assert len(config.matching_tiers) == 1
        assert config.execution.allow_udfs is True
        assert config.reconciliation.output.entity_id_prefix == "ENT"

    def test_enabled_tiers(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[
                SourceConfig(
                    name="src", table="t", unique_key="id",
                    updated_at="ts",
                    columns=[ColumnMapping(name="x")],
                ),
            ],
            feature_engineering=self._make_fe("bk"),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1", enabled=True,
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])]
                    ),
                    comparisons=[ComparisonDef(left="x", method="exact")],
                    threshold=ThresholdConfig(),
                ),
                MatchingTierConfig(
                    name="t2", enabled=False,
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])]
                    ),
                    comparisons=[ComparisonDef(left="x", method="exact")],
                    threshold=ThresholdConfig(),
                ),
            ],
        )
        enabled = config.enabled_tiers()
        assert len(enabled) == 1
        assert enabled[0].name == "t1"

    def test_fq_table(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[
                SourceConfig(
                    name="src", table="t", unique_key="id",
                    updated_at="ts",
                    columns=[ColumnMapping(name="x")],
                ),
            ],
            feature_engineering=self._make_fe("bk"),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])]
                    ),
                    comparisons=[ComparisonDef(left="x", method="exact")],
                    threshold=ThresholdConfig(),
                ),
            ],
        )
        fq = config.fq_table("bq_dataset_silver", "featured")
        assert "proj" in fq
        assert "er_silver" in fq
        assert "featured" in fq


# ---------------------------------------------------------------------------
# Cross-model integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """Tests verifying cross-model field wiring."""

    def test_reconciliation_output_has_audit_trail(self):
        """OutputConfig.audit_trail is accessible from ReconciliationConfig."""
        rc = ReconciliationConfig()
        assert hasattr(rc.output, "audit_trail")
        assert rc.output.audit_trail.enabled is False

    def test_tier_has_score_banding(self):
        """MatchingTierConfig always has score_banding (not None)."""
        tier = MatchingTierConfig(
            name="t",
            blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["bk"])]),
            comparisons=[ComparisonDef(left="x", method="exact")],
            threshold=ThresholdConfig(),
        )
        assert tier.score_banding is not None
        assert tier.score_banding.enabled is False

    def test_tier_has_hard_positives(self):
        """MatchingTierConfig has hard_positives list."""
        tier = MatchingTierConfig(
            name="t",
            blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["bk"])]),
            comparisons=[ComparisonDef(left="x", method="exact")],
            threshold=ThresholdConfig(),
        )
        assert tier.hard_positives == []

    def test_threshold_has_log_prior_odds(self):
        """ThresholdConfig has log_prior_odds for Fellegi-Sunter."""
        t = ThresholdConfig(method="fellegi_sunter")
        assert hasattr(t, "log_prior_odds")
        assert t.log_prior_odds == 0.0

    def test_blocking_path_has_bucket_size_limit(self):
        """BlockingPathDef has bucket_size_limit."""
        bp = BlockingPathDef(keys=["bk"])
        assert hasattr(bp, "bucket_size_limit")
        assert bp.bucket_size_limit == 10_000

    def test_comparison_level_has_all_fs_fields(self):
        """ComparisonLevelDef has all Fellegi-Sunter fields."""
        lvl = ComparisonLevelDef(label="test")
        assert hasattr(lvl, "log_weight")
        assert hasattr(lvl, "sql_expr")
        assert hasattr(lvl, "tf_adjusted")
        assert lvl.tf_adjusted is False

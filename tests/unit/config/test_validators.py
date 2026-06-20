"""Tests for cross-field configuration validators."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    ComparisonLevelDef,
    CompositeKeyDef,
    FeatureDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    HardNegativeDef,
    HardPositiveDef,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    ScoreBandDef,
    ScoreBandingConfig,
    SoftSignalDef,
    SourceConfig,
    TermFrequencyConfig,
    ThresholdConfig,
    TierBlockingConfig,
    TrainingConfig,
)
from bq_entity_resolution.config.validators import (
    validate_active_learning_config,
    validate_blocking_key_inputs,
    validate_canonical_field_strategies,
    validate_clustering_method,
    validate_comparison_columns_exist,
    validate_comparison_methods_registered,
    validate_comparison_weights,
    validate_composite_key_inputs,
    validate_embedding_source_columns,
    validate_enrichment_join_table_format,
    validate_enrichment_joins,
    validate_entity_type_column,
    validate_entity_type_conditions,
    validate_entity_type_roles,
    validate_feature_dependencies,
    validate_feature_inputs_exist,
    validate_fellegi_sunter_config,
    validate_full,
    validate_golden_record_columns,
    validate_hard_positive_target_band,
    validate_hash_cursor_column,
    validate_incremental_cursor_columns,
    validate_score_band_name_uniqueness,
    validate_score_banding,
    validate_skip_stages,
    validate_source_schema_alignment,
    validate_tf_columns_exist,
    validate_tier_comparisons,
    validate_udf_usage,
)
from bq_entity_resolution.exceptions import ConfigurationError


def _make_source(name: str, columns: list[str]) -> SourceConfig:
    return SourceConfig(
        name=name,
        table=f"proj.ds.{name}",
        unique_key="id",
        updated_at="updated_at",
        columns=[ColumnMapping(name=c) for c in columns],
    )


def _make_config(sources: list[SourceConfig]) -> PipelineConfig:
    return PipelineConfig(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=sources,
        feature_engineering=FeatureEngineeringConfig(
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        ),
        matching_tiers=[
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk"])],
                ),
                comparisons=[
                    ComparisonDef(left="a", right="a", method="exact"),
                ],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            ),
        ],
    )


class TestSourceSchemaAlignment:
    """Tests for validate_source_schema_alignment."""

    def test_single_source_passes(self):
        config = _make_config([_make_source("s1", ["a", "b"])])
        validate_source_schema_alignment(config)  # no error

    def test_identical_sources_pass(self):
        config = _make_config([
            _make_source("s1", ["a", "b"]),
            _make_source("s2", ["a", "b"]),
        ])
        validate_source_schema_alignment(config)  # no error

    def test_missing_column_fails(self):
        config = _make_config([
            _make_source("crm", ["a", "b", "c"]),
            _make_source("erp", ["a", "b"]),
        ])
        with pytest.raises(ConfigurationError, match="missing columns"):
            validate_source_schema_alignment(config)

    def test_extra_column_fails(self):
        config = _make_config([
            _make_source("crm", ["a", "b"]),
            _make_source("erp", ["a", "b", "extra"]),
        ])
        with pytest.raises(ConfigurationError, match="extra columns"):
            validate_source_schema_alignment(config)

    def test_both_missing_and_extra_fails(self):
        config = _make_config([
            _make_source("crm", ["a", "b"]),
            _make_source("erp", ["a", "c"]),
        ])
        with pytest.raises(ConfigurationError, match="Source schema alignment"):
            validate_source_schema_alignment(config)

    def test_three_sources_all_must_match(self):
        config = _make_config([
            _make_source("s1", ["a", "b"]),
            _make_source("s2", ["a", "b"]),
            _make_source("s3", ["a"]),
        ])
        with pytest.raises(ConfigurationError, match="s3"):
            validate_source_schema_alignment(config)

    def test_runs_in_validate_full(self):
        config = _make_config([
            _make_source("s1", ["a", "b"]),
            _make_source("s2", ["a"]),
        ])
        with pytest.raises(ConfigurationError, match="Source schema alignment"):
            validate_full(config)


class TestMethodRegistryValidation:
    """Tests for validate_comparison_methods_registered."""

    def test_valid_methods_pass(self):
        """Config with all valid methods passes validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_comparison_methods_registered(config)

    def test_invalid_comparison_method_fails(self):
        """Typo in comparison method is caught at config time."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="levenstein"),  # typo!
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="levenstein"):
            validate_comparison_methods_registered(config)

    def test_invalid_hard_negative_method_fails(self):
        """Typo in hard negative method is caught."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    hard_negatives=[
                        HardNegativeDef(left="a", method="diferent"),  # typo!
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="diferent"):
            validate_comparison_methods_registered(config)

    def test_raw_sql_override_skips_validation(self):
        """Hard negative with sql override skips method validation."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    hard_negatives=[
                        HardNegativeDef(
                            left="a", method="custom_thing",
                            sql="l.a != r.a",
                        ),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        validate_comparison_methods_registered(config)  # should pass

    def test_invalid_feature_function_fails(self):
        """Typo in feature function name is caught."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="a_clean", function="name_kleen", inputs=["a"]),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="name_kleen"):
            validate_comparison_methods_registered(config)

    def test_invalid_blocking_key_function_fails(self):
        """Typo in blocking key function name is caught."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farmm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="farmm_fingerprint"):
            validate_comparison_methods_registered(config)

    def test_runs_in_validate_full(self):
        """Method validation runs as part of validate_full."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="typo_method"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="typo_method"):
            validate_full(config)


class TestGlobalHardNegativesAndSoftSignals:
    """Tests for global hard negatives and soft signals."""

    def test_global_hard_negatives_in_config(self):
        """Global hard negatives are accepted in PipelineConfig."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_hard_negatives=[
                HardNegativeDef(left="a", method="different", action="disqualify"),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        assert len(config.global_hard_negatives) == 1

    def test_effective_hard_negatives_combines(self):
        """effective_hard_negatives merges global + tier-level."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a", "b"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_hard_negatives=[
                HardNegativeDef(left="a", method="different", action="disqualify"),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    hard_negatives=[
                        HardNegativeDef(left="b", method="null_either", action="disqualify"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        effective = config.effective_hard_negatives(config.matching_tiers[0])
        assert len(effective) == 2
        assert effective[0].left == "a"  # global first
        assert effective[1].left == "b"  # tier-specific second

    def test_effective_soft_signals_combines(self):
        """effective_soft_signals merges global + tier-level."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a", "b"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_soft_signals=[
                SoftSignalDef(left="a", method="exact", bonus=1.0),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    soft_signals=[
                        SoftSignalDef(left="b", method="exact", bonus=2.0),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        effective = config.effective_soft_signals(config.matching_tiers[0])
        assert len(effective) == 2
        assert effective[0].bonus == 1.0  # global first
        assert effective[1].bonus == 2.0  # tier-specific second

    def test_global_only_no_tier_level(self):
        """Global signals work when tier has none."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_hard_negatives=[
                HardNegativeDef(left="a", method="different", action="disqualify"),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        effective = config.effective_hard_negatives(config.matching_tiers[0])
        assert len(effective) == 1

    def test_global_column_reference_validated(self):
        """Global hard negative referencing unknown column is caught."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_hard_negatives=[
                HardNegativeDef(left="nonexistent", method="different"),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="nonexistent"):
            validate_full(config)


class TestToYaml:
    """Tests for PipelineConfig.to_yaml()."""

    def test_to_yaml_returns_string(self):
        config = _make_config([_make_source("s1", ["a"])])
        yaml_str = config.to_yaml()
        assert isinstance(yaml_str, str)
        assert "project:" in yaml_str
        assert "bq_project: proj" in yaml_str

    def test_to_yaml_includes_tiers(self):
        config = _make_config([_make_source("s1", ["a"])])
        yaml_str = config.to_yaml()
        assert "matching_tiers:" in yaml_str
        assert "method: exact" in yaml_str

    def test_to_yaml_roundtrip_structure(self):
        """YAML output can be parsed back as a dict."""
        import yaml
        config = _make_config([_make_source("s1", ["a"])])
        yaml_str = config.to_yaml()
        data = yaml.safe_load(yaml_str)
        assert "project" in data
        assert "sources" in data
        assert "matching_tiers" in data


class TestTierComparisons:
    """Tests for validate_tier_comparisons."""

    def test_valid_tier_passes(self):
        config = _make_config([_make_source("s1", ["a"])])
        validate_tier_comparisons(config)

    def test_empty_comparisons_fails(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["a"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="empty_tier",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="no comparisons"):
            validate_tier_comparisons(config)

    def test_zero_total_weight_fails(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["a"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="zero_weight",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a",
                            method="exact", weight=0.0,
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="weight"):
            validate_tier_comparisons(config)

    def test_unreachable_threshold_fails(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["a"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="unreachable",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a",
                            method="exact", weight=3.0,
                        ),
                    ],
                    threshold=ThresholdConfig(
                        method="sum", min_score=100.0,
                    ),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="exceeds maximum"):
            validate_tier_comparisons(config)

    def test_reachable_threshold_passes(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["a"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="reachable",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a",
                            method="exact", weight=5.0,
                        ),
                    ],
                    threshold=ThresholdConfig(
                        method="sum", min_score=3.0,
                    ),
                ),
            ],
        )
        validate_tier_comparisons(config)

    def test_runs_in_validate_full(self):
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["a"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="bad",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="no comparisons"):
            validate_full(config)

    def test_fellegi_sunter_threshold_skipped(self):
        """Threshold reachability check only applies to sum method."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["a"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="fs_tier",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a",
                            method="exact", weight=1.0,
                        ),
                    ],
                    threshold=ThresholdConfig(
                        method="fellegi_sunter",
                        min_score=100.0,
                    ),
                ),
            ],
        )
        validate_tier_comparisons(config)


class TestSkipStagesValidator:
    """Tests for validate_skip_stages."""

    def test_valid_skip_stages_pass(self):
        """Known stage names pass validation."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.execution = ExecutionConfig(skip_stages=["cluster_quality"])
        validate_skip_stages(config)

    def test_empty_skip_stages_pass(self):
        """No skip_stages passes validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_skip_stages(config)

    def test_unknown_stage_fails(self):
        """Typo in skip_stages is caught."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.execution = ExecutionConfig(skip_stages=["cluter_quality"])
        with pytest.raises(ConfigurationError, match="cluter_quality"):
            validate_skip_stages(config)

    def test_suggestion_offered(self):
        """Close matches are suggested."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.execution = ExecutionConfig(skip_stages=["clustring"])
        with pytest.raises(ConfigurationError, match="Did you mean"):
            validate_skip_stages(config)

    def test_tier_specific_stage_names_valid(self):
        """Tier-specific stage names (blocking_t1, matching_t1) pass."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.execution = ExecutionConfig(skip_stages=["blocking_t1"])
        validate_skip_stages(config)

    def test_runs_in_validate_full(self):
        """skip_stages validator runs as part of validate_full."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.execution = ExecutionConfig(skip_stages=["nonexistent_stage"])
        with pytest.raises(ConfigurationError, match="nonexistent_stage"):
            validate_full(config)


class TestIncrementalCursorValidator:
    """Tests for validate_incremental_cursor_columns."""

    def test_valid_cursor_column_passes(self):
        """Cursor column present in source passes validation."""
        config = _make_config([_make_source("s1", ["a"])])
        # updated_at is the default cursor column and is the updated_at system column
        validate_incremental_cursor_columns(config)

    def test_missing_cursor_column_fails(self):
        """Cursor column not in source columns is caught."""
        from bq_entity_resolution.config.models.infrastructure import IncrementalConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.incremental = IncrementalConfig(
            cursor_columns=["nonexistent_cursor"],
        )
        with pytest.raises(ConfigurationError, match="nonexistent_cursor"):
            validate_incremental_cursor_columns(config)

    def test_cursor_column_in_source_columns(self):
        """Cursor column defined as a source column passes."""
        from bq_entity_resolution.config.models.infrastructure import IncrementalConfig
        config = _make_config([_make_source("s1", ["a", "batch_id"])])
        config.incremental = IncrementalConfig(
            cursor_columns=["batch_id"],
        )
        validate_incremental_cursor_columns(config)

    def test_partition_cursor_column_validated(self):
        """Partition cursor columns are also validated."""
        from bq_entity_resolution.config.models.infrastructure import (
            IncrementalConfig,
            PartitionCursorConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.incremental = IncrementalConfig(
            partition_cursors=[
                PartitionCursorConfig(column="missing_partition_col"),
            ],
        )
        with pytest.raises(ConfigurationError, match="missing_partition_col"):
            validate_incremental_cursor_columns(config)

    def test_disabled_incremental_skips_validation(self):
        """Disabled incremental config skips cursor validation."""
        from bq_entity_resolution.config.models.infrastructure import IncrementalConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.incremental = IncrementalConfig(
            enabled=False,
            cursor_columns=["nonexistent"],
        )
        validate_incremental_cursor_columns(config)  # no error


class TestEmbeddingSourceColumns:
    """Tests for validate_embedding_source_columns."""

    def test_disabled_embeddings_skip(self):
        """Disabled embeddings skip validation."""
        from bq_entity_resolution.config.models.infrastructure import EmbeddingConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.embeddings = EmbeddingConfig(enabled=False, source_columns=["nonexistent"])
        validate_embedding_source_columns(config)  # no error

    def test_valid_source_column_passes(self):
        """Embedding source_columns referencing real columns pass."""
        from bq_entity_resolution.config.models.infrastructure import EmbeddingConfig
        config = _make_config([_make_source("s1", ["a", "name"])])
        config.embeddings = EmbeddingConfig(enabled=True, source_columns=["a", "name"])
        validate_embedding_source_columns(config)

    def test_missing_source_column_fails(self):
        """Embedding source_columns referencing unknown columns fail."""
        from bq_entity_resolution.config.models.infrastructure import EmbeddingConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.embeddings = EmbeddingConfig(enabled=True, source_columns=["nonexistent"])
        with pytest.raises(ConfigurationError, match="nonexistent"):
            validate_embedding_source_columns(config)

    def test_feature_names_accepted(self):
        """Embedding source_columns can reference engineered features."""
        from bq_entity_resolution.config.models.infrastructure import EmbeddingConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.name_features = FeatureGroupConfig(
            features=[FeatureDef(name="name_clean", function="name_clean", input="a")]
        )
        config.embeddings = EmbeddingConfig(enabled=True, source_columns=["name_clean"])
        validate_embedding_source_columns(config)


class TestHashCursorColumn:
    """Tests for validate_hash_cursor_column."""

    def test_no_hash_cursor_skips(self):
        """No hash_cursor config skips validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_hash_cursor_column(config)  # no error

    def test_valid_hash_cursor_passes(self):
        """Hash cursor referencing a known column passes."""
        from bq_entity_resolution.config.models.infrastructure import (
            HashCursorConfig,
            IncrementalConfig,
        )
        config = _make_config([_make_source("s1", ["a", "batch_id"])])
        config.incremental = IncrementalConfig(
            hash_cursor=HashCursorConfig(column="batch_id"),
        )
        validate_hash_cursor_column(config)

    def test_entity_uid_always_valid(self):
        """entity_uid is always a valid hash cursor column."""
        from bq_entity_resolution.config.models.infrastructure import (
            HashCursorConfig,
            IncrementalConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.incremental = IncrementalConfig(
            hash_cursor=HashCursorConfig(column="entity_uid"),
        )
        validate_hash_cursor_column(config)

    def test_missing_hash_cursor_column_fails(self):
        """Hash cursor referencing unknown column fails."""
        from bq_entity_resolution.config.models.infrastructure import (
            HashCursorConfig,
            IncrementalConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.incremental = IncrementalConfig(
            hash_cursor=HashCursorConfig(column="nonexistent_col"),
        )
        with pytest.raises(ConfigurationError, match="nonexistent_col"):
            validate_hash_cursor_column(config)


class TestHardPositiveTargetBand:
    """Tests for validate_hard_positive_target_band."""

    def test_no_hard_positives_passes(self):
        """Tiers without hard_positives pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_hard_positive_target_band(config)

    def test_valid_target_band_passes(self):
        """Hard positive with matching target_band passes."""
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="high", min_score=8.0),
                ScoreBandDef(name="medium", min_score=4.0),
            ],
        )
        config.matching_tiers[0].hard_positives = [
            HardPositiveDef(
                left="a",
                method="exact",
                action="elevate_band",
                target_band="high",
            ),
        ]
        validate_hard_positive_target_band(config)

    def test_missing_target_band_fails(self):
        """Hard positive with non-existent target_band fails."""
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[ScoreBandDef(name="high", min_score=8.0)],
        )
        config.matching_tiers[0].hard_positives = [
            HardPositiveDef(
                left="a",
                method="exact",
                action="elevate_band",
                target_band="nonexistent",
            ),
        ]
        with pytest.raises(ConfigurationError, match="nonexistent"):
            validate_hard_positive_target_band(config)

    def test_elevate_band_without_banding_fails(self):
        """elevate_band action without score_banding enabled fails."""
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].hard_positives = [
            HardPositiveDef(
                left="a",
                method="exact",
                action="elevate_band",
                target_band="high",
            ),
        ]
        with pytest.raises(ConfigurationError, match="score_banding is not enabled"):
            validate_hard_positive_target_band(config)


class TestScoreBandNameUniqueness:
    """Tests for validate_score_band_name_uniqueness."""

    def test_unique_bands_pass(self):
        """Tiers with unique band names pass."""
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="high", min_score=8.0),
                ScoreBandDef(name="medium", min_score=4.0),
            ],
        )
        validate_score_band_name_uniqueness(config)

    def test_duplicate_bands_fail(self):
        """Tiers with duplicate band names fail."""
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="high", min_score=8.0),
                ScoreBandDef(name="high", min_score=4.0),
            ],
        )
        with pytest.raises(ConfigurationError, match="duplicate.*high"):
            validate_score_band_name_uniqueness(config)

    def test_no_banding_passes(self):
        """Tiers without score_banding pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_score_band_name_uniqueness(config)


class TestClusteringMethod:
    """Tests for validate_clustering_method."""

    def test_valid_methods_pass(self):
        """All supported clustering methods pass."""
        from bq_entity_resolution.config.models.reconciliation import ClusteringConfig
        for method in ("connected_components", "star", "best_match"):
            config = _make_config([_make_source("s1", ["a"])])
            config.reconciliation.clustering = ClusteringConfig(method=method)
            validate_clustering_method(config)

    def test_default_method_passes(self):
        """Default clustering method (connected_components) passes."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_clustering_method(config)


class TestGoldenRecordColumns:
    """Tests for validate_golden_record_columns."""

    def test_empty_cluster_columns_passes(self):
        """No cluster_columns configured passes."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_golden_record_columns(config)

    def test_valid_cluster_columns_pass(self):
        """Cluster columns referencing known columns pass."""
        from bq_entity_resolution.config.models.reconciliation import OutputConfig
        config = _make_config([_make_source("s1", ["a", "name"])])
        config.reconciliation.output = OutputConfig(cluster_columns=["a", "name"])
        validate_golden_record_columns(config)

    def test_system_columns_pass(self):
        """System columns (entity_uid, cluster_id) pass."""
        from bq_entity_resolution.config.models.reconciliation import OutputConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.reconciliation.output = OutputConfig(
            cluster_columns=["entity_uid", "cluster_id"]
        )
        validate_golden_record_columns(config)

    def test_unknown_column_fails(self):
        """Unknown cluster column fails with suggestion."""
        from bq_entity_resolution.config.models.reconciliation import OutputConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.reconciliation.output = OutputConfig(cluster_columns=["nonexistent_col"])
        with pytest.raises(ConfigurationError, match="nonexistent_col"):
            validate_golden_record_columns(config)


class TestCanonicalFieldStrategies:
    """Tests for validate_canonical_field_strategies."""

    def test_empty_strategies_passes(self):
        """No field strategies configured passes."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_canonical_field_strategies(config)

    def test_valid_strategies_pass(self):
        """Field strategies referencing known columns pass."""
        from bq_entity_resolution.config.models.reconciliation import (
            CanonicalSelectionConfig,
            FieldMergeStrategy,
        )
        config = _make_config([_make_source("s1", ["a", "name"])])
        config.reconciliation.canonical_selection = CanonicalSelectionConfig(
            method="field_merge",
            field_strategies=[
                FieldMergeStrategy(column="a", strategy="most_recent"),
                FieldMergeStrategy(column="name", strategy="most_common"),
            ],
        )
        validate_canonical_field_strategies(config)

    def test_unknown_column_fails(self):
        """Field strategy referencing unknown column fails."""
        from bq_entity_resolution.config.models.reconciliation import (
            CanonicalSelectionConfig,
            FieldMergeStrategy,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.reconciliation.canonical_selection = CanonicalSelectionConfig(
            method="field_merge",
            field_strategies=[
                FieldMergeStrategy(column="nonexistent", strategy="most_recent"),
            ],
        )
        with pytest.raises(ConfigurationError, match="nonexistent"):
            validate_canonical_field_strategies(config)


class TestActiveLearningConfig:
    """Tests for validate_active_learning_config."""

    def test_disabled_passes(self):
        """Disabled active learning passes."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_active_learning_config(config)

    def test_enabled_with_table_passes(self):
        """Active learning enabled with review_queue_table passes."""
        from bq_entity_resolution.config.models.matching import ActiveLearningConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].active_learning = ActiveLearningConfig(
            enabled=True,
            review_queue_table="proj.ds.review_queue",
        )
        validate_active_learning_config(config)

    def test_enabled_without_table_fails(self):
        """Active learning enabled without review_queue_table fails."""
        from bq_entity_resolution.config.models.matching import ActiveLearningConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].active_learning = ActiveLearningConfig(
            enabled=True,
        )
        with pytest.raises(ConfigurationError, match="review_queue_table"):
            validate_active_learning_config(config)

    def test_label_feedback_without_table_fails(self):
        """Label feedback enabled without feedback_table fails."""
        from bq_entity_resolution.config.models.matching import (
            ActiveLearningConfig,
            LabelFeedbackConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].active_learning = ActiveLearningConfig(
            enabled=True,
            review_queue_table="proj.ds.review_queue",
            label_feedback=LabelFeedbackConfig(enabled=True),
        )
        with pytest.raises(ConfigurationError, match="feedback_table"):
            validate_active_learning_config(config)


class TestEnrichmentJoinTableFormat:
    """Tests for validate_enrichment_join_table_format."""

    def test_no_joins_passes(self):
        """No enrichment joins passes."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_enrichment_join_table_format(config)

    def test_valid_table_ref_passes(self):
        """Fully-qualified table reference passes."""
        from bq_entity_resolution.config.models.features import EnrichmentJoinConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.enrichment_joins = [
            EnrichmentJoinConfig(
                name="geo",
                table="proj.dataset.geocoding",
                lookup_key="zip_fp",
                source_key_function="farm_fingerprint",
                source_key_inputs=["a"],
                columns=["latitude"],
            ),
        ]
        validate_enrichment_join_table_format(config)

    def test_invalid_table_ref_fails(self):
        """Non-qualified table reference fails."""
        from bq_entity_resolution.config.models.features import EnrichmentJoinConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.enrichment_joins = [
            EnrichmentJoinConfig(
                name="geo",
                table="just_a_table",
                lookup_key="zip_fp",
                source_key_function="farm_fingerprint",
                source_key_inputs=["a"],
                columns=["latitude"],
            ),
        ]
        with pytest.raises(ConfigurationError, match="just_a_table"):
            validate_enrichment_join_table_format(config)


# ---------------------------------------------------------------------------
# Tests for the 14 previously-untested validators
# ---------------------------------------------------------------------------


class TestValidateComparisonColumnsExist:
    """Tests for validate_comparison_columns_exist."""

    def test_valid_columns_pass(self):
        """Comparison columns that exist as source columns pass."""
        config = _make_config([_make_source("s1", ["a", "b"])])
        validate_comparison_columns_exist(config)

    def test_feature_columns_pass(self):
        """Comparison columns referencing engineered features pass."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="a_clean", function="name_clean", input="a"),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a_clean", right="a_clean", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_comparison_columns_exist(config)

    def test_unknown_left_column_fails(self):
        """Unknown left column in comparison raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="nonexistent", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="nonexistent"):
            validate_comparison_columns_exist(config)

    def test_unknown_hard_negative_column_fails(self):
        """Hard negative referencing unknown column raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    hard_negatives=[
                        HardNegativeDef(left="missing_col", method="different"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="missing_col"):
            validate_comparison_columns_exist(config)


class TestValidateFeatureInputsExist:
    """Tests for validate_feature_inputs_exist."""

    def test_valid_inputs_pass(self):
        """Feature inputs that reference source columns pass."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["first_name"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="fn_clean", function="name_clean", input="first_name"),
                ]),
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint", inputs=["first_name"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="first_name", right="first_name", method="exact",
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_feature_inputs_exist(config)

    def test_unknown_input_fails(self):
        """Feature referencing a non-existent input raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(
                        name="fn_clean", function="name_clean",
                        input="nonexistent_column",
                    ),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="nonexistent_column"):
            validate_feature_inputs_exist(config)

    def test_chained_feature_references_pass(self):
        """Feature that references a prior feature name passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="a_clean", function="name_clean", input="a"),
                    FeatureDef(name="a_upper", function="upper", input="a_clean"),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_feature_inputs_exist(config)


class TestValidateFeatureDependencies:
    """Tests for validate_feature_dependencies."""

    def test_no_depends_on_passes(self):
        """Features without depends_on pass validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_feature_dependencies(config)

    def test_valid_depends_on_passes(self):
        """Feature depending on a known feature passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="a_clean", function="name_clean", input="a"),
                    FeatureDef(
                        name="a_upper", function="upper", input="a",
                        depends_on=["a_clean"],
                    ),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_feature_dependencies(config)

    def test_unknown_depends_on_fails(self):
        """Feature depending on unknown feature raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(
                        name="a_clean", function="name_clean", input="a",
                        depends_on=["totally_unknown"],
                    ),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="totally_unknown"):
            validate_feature_dependencies(config)


class TestValidateComparisonWeights:
    """Tests for validate_comparison_weights."""

    def test_positive_weight_passes(self):
        """Comparisons with positive weights pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_comparison_weights(config)

    def test_zero_weight_passes(self):
        """Zero weight is technically allowed (not negative)."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a", method="exact", weight=0.0,
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=0.0),
                ),
            ],
        )
        validate_comparison_weights(config)

    def test_negative_weight_fails(self):
        """Negative comparison weight raises ConfigurationError.

        Note: Pydantic field_validator also rejects < 0, but the cross-field
        validator catches it if the model is built programmatically.
        """
        config = _make_config([_make_source("s1", ["a"])])
        # Bypass Pydantic validation by mutating the object
        config.matching_tiers[0].comparisons[0].weight = -1.0
        with pytest.raises(ConfigurationError, match="negative weight"):
            validate_comparison_weights(config)


class TestValidateFellegiSunterConfig:
    """Tests for validate_fellegi_sunter_config."""

    def test_sum_threshold_skips_fs_validation(self):
        """Tiers with sum threshold skip Fellegi-Sunter validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_fellegi_sunter_config(config)

    def test_fs_with_training_passes(self):
        """Fellegi-Sunter tier with EM training and no levels passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            training=TrainingConfig(method="em"),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="fellegi_sunter", min_score=0.0),
                ),
            ],
        )
        validate_fellegi_sunter_config(config)

    def test_fs_with_levels_and_manual_mu_passes(self):
        """F-S tier with fully-specified levels (m/u + null last) passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a", method="exact",
                            levels=[
                                ComparisonLevelDef(
                                    label="exact", method="exact", m=0.9, u=0.1,
                                ),
                                ComparisonLevelDef(
                                    label="else", method=None, m=0.1, u=0.9,
                                ),
                            ],
                        ),
                    ],
                    threshold=ThresholdConfig(method="fellegi_sunter", min_score=0.0),
                ),
            ],
        )
        validate_fellegi_sunter_config(config)

    def test_fs_last_level_not_null_fails(self):
        """F-S tier where last level has method != None fails."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a", method="exact",
                            levels=[
                                ComparisonLevelDef(
                                    label="exact", method="exact", m=0.9, u=0.1,
                                ),
                                ComparisonLevelDef(
                                    label="fuzzy", method="levenshtein", m=0.5, u=0.5,
                                ),
                            ],
                        ),
                    ],
                    threshold=ThresholdConfig(method="fellegi_sunter", min_score=0.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="last level must have method=null"):
            validate_fellegi_sunter_config(config)

    def test_fs_no_training_no_mu_fails(self):
        """F-S tier with no training and missing m/u fails."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(method="fellegi_sunter", min_score=0.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="fellegi_sunter requires"):
            validate_fellegi_sunter_config(config)


class TestValidateTfColumnsExist:
    """Tests for validate_tf_columns_exist."""

    def test_no_tf_adjustment_passes(self):
        """Comparisons without TF adjustment pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_tf_columns_exist(config)

    def test_tf_column_as_source_column_passes(self):
        """TF adjustment referencing a source column passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a", method="exact",
                            tf_adjustment=TermFrequencyConfig(enabled=True),
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_tf_columns_exist(config)

    def test_tf_column_unknown_fails(self):
        """TF adjustment referencing unknown column raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a", method="exact",
                            tf_adjustment=TermFrequencyConfig(
                                enabled=True,
                                tf_adjustment_column="nonexistent_col",
                            ),
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="nonexistent_col"):
            validate_tf_columns_exist(config)


class TestValidateEntityTypeConditions:
    """Tests for validate_entity_type_conditions."""

    def test_no_conditions_passes(self):
        """Signals without entity_type_condition pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_entity_type_conditions(config)

    def test_valid_condition_passes(self):
        """Known entity type condition (e.g. 'person') passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_hard_negatives=[
                HardNegativeDef(
                    left="a", method="different",
                    entity_type_condition="person",
                ),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_entity_type_conditions(config)

    def test_unknown_condition_fails(self):
        """Unknown entity type condition raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            global_hard_negatives=[
                HardNegativeDef(
                    left="a", method="different",
                    entity_type_condition="alien_species",
                ),
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="alien_species"):
            validate_entity_type_conditions(config)

    def test_tier_level_unknown_condition_fails(self):
        """Tier-level hard negative with unknown condition fails."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    hard_negatives=[
                        HardNegativeDef(
                            left="a", method="different",
                            entity_type_condition="unknown_type",
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="unknown_type"):
            validate_entity_type_conditions(config)


class TestValidateEntityTypeRoles:
    """Tests for validate_entity_type_roles."""

    def test_no_entity_type_passes(self):
        """Sources without entity_type pass silently."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_entity_type_roles(config)  # no error, no warning

    def test_unknown_entity_type_warns(self, caplog):
        """Unknown entity_type on a source logs a warning."""
        import logging
        source = SourceConfig(
            name="s1",
            table="proj.ds.s1",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="a")],
            entity_type="MythicalCreature",
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.sources = [source]
        with caplog.at_level(logging.WARNING):
            validate_entity_type_roles(config)
        assert "MythicalCreature" in caplog.text

    def test_valid_entity_type_with_required_roles_passes(self, caplog):
        """Source with Person entity_type and matching roles passes."""
        import logging
        source = SourceConfig(
            name="s1",
            table="proj.ds.s1",
            unique_key="id",
            updated_at="updated_at",
            columns=[
                ColumnMapping(name="first_name", role="first_name"),
                ColumnMapping(name="last_name", role="last_name"),
            ],
            entity_type="Person",
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.sources = [source]
        with caplog.at_level(logging.WARNING):
            validate_entity_type_roles(config)
        # Person template may require first_name + last_name which we provide
        # No error raised; warnings depend on template definition


class TestValidateEnrichmentJoins:
    """Tests for validate_enrichment_joins."""

    def test_no_joins_passes(self):
        """No enrichment joins pass validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_enrichment_joins(config)

    def test_valid_join_passes(self):
        """Enrichment join with valid function and inputs passes."""
        from bq_entity_resolution.config.models.features import EnrichmentJoinConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.enrichment_joins = [
            EnrichmentJoinConfig(
                name="geo",
                table="proj.dataset.geocoding",
                lookup_key="zip_fp",
                source_key_function="farm_fingerprint",
                source_key_inputs=["a"],
                columns=["latitude"],
            ),
        ]
        validate_enrichment_joins(config)

    def test_unknown_source_key_function_fails(self):
        """Enrichment join with unknown source_key_function fails."""
        from bq_entity_resolution.config.models.features import EnrichmentJoinConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.enrichment_joins = [
            EnrichmentJoinConfig(
                name="geo",
                table="proj.dataset.geocoding",
                lookup_key="zip_fp",
                source_key_function="totally_fake_function",
                source_key_inputs=["a"],
                columns=["latitude"],
            ),
        ]
        with pytest.raises(ConfigurationError, match="totally_fake_function"):
            validate_enrichment_joins(config)

    def test_unknown_source_key_input_fails(self):
        """Enrichment join referencing unknown input column fails."""
        from bq_entity_resolution.config.models.features import EnrichmentJoinConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.enrichment_joins = [
            EnrichmentJoinConfig(
                name="geo",
                table="proj.dataset.geocoding",
                lookup_key="zip_fp",
                source_key_function="farm_fingerprint",
                source_key_inputs=["nonexistent_input"],
                columns=["latitude"],
            ),
        ]
        with pytest.raises(ConfigurationError, match="nonexistent_input"):
            validate_enrichment_joins(config)

    def test_duplicate_join_names_fails(self):
        """Duplicate enrichment join names raise ConfigurationError."""
        from bq_entity_resolution.config.models.features import EnrichmentJoinConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.enrichment_joins = [
            EnrichmentJoinConfig(
                name="geo",
                table="proj.dataset.geocoding",
                lookup_key="zip_fp",
                source_key_function="farm_fingerprint",
                source_key_inputs=["a"],
                columns=["latitude"],
            ),
            EnrichmentJoinConfig(
                name="geo",
                table="proj.dataset.geocoding2",
                lookup_key="zip_fp2",
                source_key_function="farm_fingerprint",
                source_key_inputs=["a"],
                columns=["longitude"],
            ),
        ]
        with pytest.raises(ConfigurationError, match="Duplicate enrichment join name.*geo"):
            validate_enrichment_joins(config)


class TestValidateUdfUsage:
    """Tests for validate_udf_usage."""

    def test_allow_udfs_true_passes(self):
        """When allow_udfs is True (default), UDF methods are allowed."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_udf_usage(config)  # default is allow_udfs=True

    def test_allow_udfs_false_with_udf_method_fails(self):
        """When allow_udfs=False, a UDF comparison method fails."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(
                            left="a", right="a", method="jaro_winkler",
                        ),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        config.execution = ExecutionConfig(allow_udfs=False)
        with pytest.raises(ConfigurationError, match="jaro_winkler.*allow_udfs=false"):
            validate_udf_usage(config)

    def test_allow_udfs_false_with_native_method_passes(self):
        """When allow_udfs=False, native comparison methods are allowed."""
        from bq_entity_resolution.config.models.infrastructure import ExecutionConfig
        config = _make_config([_make_source("s1", ["a"])])
        config.execution = ExecutionConfig(allow_udfs=False)
        # 'exact' is a native method, should pass
        validate_udf_usage(config)


class TestValidateCompositeKeyInputs:
    """Tests for validate_composite_key_inputs."""

    def test_no_composite_keys_passes(self):
        """No composite keys passes validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_composite_key_inputs(config)

    def test_valid_composite_key_passes(self):
        """Composite key with known inputs passes."""
        config = _make_config([_make_source("s1", ["a", "b"])])
        config.feature_engineering.composite_keys = [
            CompositeKeyDef(name="ck1", function="concat", inputs=["a", "b"]),
        ]
        validate_composite_key_inputs(config)

    def test_unknown_composite_key_input_fails(self):
        """Composite key with unknown input raises ConfigurationError."""
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.composite_keys = [
            CompositeKeyDef(
                name="ck1", function="concat", inputs=["a", "nonexistent"],
            ),
        ]
        with pytest.raises(ConfigurationError, match="nonexistent"):
            validate_composite_key_inputs(config)


class TestValidateBlockingKeyInputs:
    """Tests for validate_blocking_key_inputs."""

    def test_valid_blocking_key_inputs_pass(self):
        """Blocking key inputs referencing source columns pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_blocking_key_inputs(config)

    def test_blocking_key_referencing_feature_passes(self):
        """Blocking key inputs referencing engineered features pass."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="a_clean", function="name_clean", input="a"),
                ]),
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint", inputs=["a_clean"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_blocking_key_inputs(config)

    def test_unknown_blocking_key_input_fails(self):
        """Blocking key referencing unknown column raises ConfigurationError."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                blocking_keys=[
                    BlockingKeyDef(
                        name="bk", function="farm_fingerprint",
                        inputs=["nonexistent_col"],
                    ),
                ],
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="nonexistent_col"):
            validate_blocking_key_inputs(config)


class TestValidateEntityTypeColumn:
    """Tests for validate_entity_type_column."""

    def test_no_entity_type_column_passes(self):
        """No entity_type_column set passes validation."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_entity_type_column(config)

    def test_valid_entity_type_column_passes(self):
        """entity_type_column referencing a source column passes."""
        config = _make_config([_make_source("s1", ["a", "entity_type"])])
        config.feature_engineering.entity_type_column = "entity_type"
        validate_entity_type_column(config)

    def test_entity_type_column_as_feature_passes(self):
        """entity_type_column referencing an engineered feature passes."""
        config = PipelineConfig(
            project=ProjectConfig(name="test", bq_project="proj"),
            sources=[_make_source("s1", ["a"])],
            feature_engineering=FeatureEngineeringConfig(
                name_features=FeatureGroupConfig(features=[
                    FeatureDef(name="etype", function="name_clean", input="a"),
                ]),
                blocking_keys=[
                    BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
                ],
                entity_type_column="etype",
            ),
            matching_tiers=[
                MatchingTierConfig(
                    name="t1",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk"])],
                    ),
                    comparisons=[
                        ComparisonDef(left="a", right="a", method="exact"),
                    ],
                    threshold=ThresholdConfig(min_score=1.0),
                ),
            ],
        )
        validate_entity_type_column(config)

    def test_unknown_entity_type_column_fails(self):
        """entity_type_column not in columns or features raises ConfigurationError."""
        config = _make_config([_make_source("s1", ["a"])])
        config.feature_engineering.entity_type_column = "nonexistent_col"
        with pytest.raises(ConfigurationError, match="nonexistent_col"):
            validate_entity_type_column(config)


class TestValidateScoreBanding:
    """Tests for validate_score_banding."""

    def test_no_banding_passes(self):
        """Tiers without score banding pass."""
        config = _make_config([_make_source("s1", ["a"])])
        validate_score_banding(config)

    def test_non_overlapping_contiguous_bands_pass(self):
        """Score bands that are contiguous and non-overlapping pass."""
        from bq_entity_resolution.config.models.matching import (
            ScoreBandDef,
            ScoreBandingConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="high", min_score=8.0, max_score=100.0),
                ScoreBandDef(name="medium", min_score=4.0, max_score=8.0),
                ScoreBandDef(name="low", min_score=0.0, max_score=4.0),
            ],
        )
        validate_score_banding(config)

    def test_overlapping_bands_fail(self):
        """Overlapping score bands raise ConfigurationError."""
        from bq_entity_resolution.config.models.matching import (
            ScoreBandDef,
            ScoreBandingConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="high", min_score=7.0, max_score=100.0),
                ScoreBandDef(name="medium", min_score=4.0, max_score=9.0),
            ],
        )
        with pytest.raises(ConfigurationError, match="overlaps"):
            validate_score_banding(config)

    def test_gap_between_bands_fails(self):
        """Gap between score bands raises ConfigurationError."""
        from bq_entity_resolution.config.models.matching import (
            ScoreBandDef,
            ScoreBandingConfig,
        )
        config = _make_config([_make_source("s1", ["a"])])
        config.matching_tiers[0].score_banding = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="high", min_score=8.0, max_score=100.0),
                ScoreBandDef(name="low", min_score=0.0, max_score=4.0),
            ],
        )
        with pytest.raises(ConfigurationError, match="gap"):
            validate_score_banding(config)

"""Tests for ExecutionConfig: allow_udfs and skip_stages."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    ComparisonLevelDef,
    ExecutionConfig,
    FeatureDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.config.validators import validate_udf_usage
from bq_entity_resolution.exceptions import ConfigurationError
from bq_entity_resolution.features.registry import UDF_FEATURE_FUNCTIONS
from bq_entity_resolution.matching.comparisons import UDF_COMPARISON_METHODS
from bq_entity_resolution.pipeline.dag import build_pipeline_dag
from bq_entity_resolution.pipeline.pipeline import Pipeline


def _make_source() -> SourceConfig:
    return SourceConfig(
        name="customers",
        table="proj.ds.customers",
        unique_key="id",
        updated_at="updated_at",
        columns=[
            ColumnMapping(name="first_name"),
            ColumnMapping(name="email"),
        ],
    )


def _make_config(
    comparisons: list[ComparisonDef] | None = None,
    allow_udfs: bool = True,
    skip_stages: list[str] | None = None,
    feature_groups: dict[str, FeatureGroupConfig] | None = None,
) -> PipelineConfig:
    comps = comparisons or [
        ComparisonDef(left="first_name", right="first_name", method="exact", weight=3.0),
    ]
    fe_kwargs: dict = {
        "blocking_keys": [
            BlockingKeyDef(name="bk_email", function="farm_fingerprint", inputs=["email"]),
        ],
    }
    if feature_groups:
        fe_kwargs["extra_groups"] = feature_groups

    return PipelineConfig(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=[_make_source()],
        feature_engineering=FeatureEngineeringConfig(**fe_kwargs),
        matching_tiers=[
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=comps,
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            ),
        ],
        execution=ExecutionConfig(
            allow_udfs=allow_udfs,
            skip_stages=skip_stages or [],
        ),
    )


# ---------------------------------------------------------------------------
# ExecutionConfig defaults
# ---------------------------------------------------------------------------


class TestExecutionConfigDefaults:
    def test_allow_udfs_default_true(self):
        cfg = ExecutionConfig()
        assert cfg.allow_udfs is True

    def test_skip_stages_default_empty(self):
        cfg = ExecutionConfig()
        assert cfg.skip_stages == []

    def test_pipeline_config_has_execution_field(self):
        config = _make_config()
        assert hasattr(config, "execution")
        assert isinstance(config.execution, ExecutionConfig)


# ---------------------------------------------------------------------------
# UDF constants
# ---------------------------------------------------------------------------


class TestUDFConstants:
    def test_udf_comparison_methods_contains_jaro_winkler(self):
        assert "jaro_winkler" in UDF_COMPARISON_METHODS
        assert "jaro_winkler_score" in UDF_COMPARISON_METHODS

    def test_udf_comparison_methods_contains_metaphone(self):
        assert "metaphone_match" in UDF_COMPARISON_METHODS
        assert "double_metaphone_match" in UDF_COMPARISON_METHODS

    def test_udf_feature_functions_contains_metaphone(self):
        assert "metaphone" in UDF_FEATURE_FUNCTIONS

    def test_native_methods_not_in_udf_set(self):
        assert "exact" not in UDF_COMPARISON_METHODS
        assert "levenshtein" not in UDF_COMPARISON_METHODS
        assert "levenshtein_normalized" not in UDF_COMPARISON_METHODS
        assert "soundex_match" not in UDF_COMPARISON_METHODS


# ---------------------------------------------------------------------------
# allow_udfs validation
# ---------------------------------------------------------------------------


class TestAllowUdfsValidation:
    def test_allow_udfs_true_permits_jaro_winkler(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="jaro_winkler", weight=3.0,
                ),
            ],
            allow_udfs=True,
        )
        # Should not raise
        validate_udf_usage(config)

    def test_allow_udfs_false_rejects_jaro_winkler(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="jaro_winkler", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError, match="jaro_winkler"):
            validate_udf_usage(config)

    def test_allow_udfs_false_rejects_jaro_winkler_score(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="jaro_winkler_score", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError, match="jaro_winkler_score"):
            validate_udf_usage(config)

    def test_allow_udfs_false_rejects_metaphone_match(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="metaphone_match", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError, match="metaphone_match"):
            validate_udf_usage(config)

    def test_allow_udfs_false_rejects_double_metaphone(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="double_metaphone_match", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError, match="double_metaphone_match"):
            validate_udf_usage(config)

    def test_allow_udfs_false_allows_native_methods(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="levenshtein_normalized", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        # Should not raise
        validate_udf_usage(config)

    def test_allow_udfs_false_allows_exact(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="exact", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        validate_udf_usage(config)

    def test_allow_udfs_false_rejects_metaphone_feature(self):
        config = _make_config(
            allow_udfs=False,
            feature_groups={
                "phonetic": FeatureGroupConfig(
                    features=[
                        FeatureDef(
                            name="first_metaphone",
                            function="metaphone",
                            input="first_name",
                        ),
                    ],
                ),
            },
        )
        with pytest.raises(ConfigurationError, match="metaphone"):
            validate_udf_usage(config)

    def test_allow_udfs_false_rejects_udf_in_multi_level(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="exact", weight=3.0,
                    levels=[
                        ComparisonLevelDef(
                            label="exact", method="exact", m=0.95, u=0.01,
                        ),
                        ComparisonLevelDef(
                            label="fuzzy", method="jaro_winkler", m=0.8, u=0.1,
                        ),
                        ComparisonLevelDef(
                            label="else", method=None, m=0.1, u=0.9,
                        ),
                    ],
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError, match="jaro_winkler"):
            validate_udf_usage(config)

    def test_error_message_suggests_alternative(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="jaro_winkler", weight=3.0,
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError, match="levenshtein_normalized"):
            validate_udf_usage(config)

    def test_multiple_udf_methods_all_reported(self):
        config = _make_config(
            comparisons=[
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="jaro_winkler", weight=3.0,
                ),
                ComparisonDef(
                    left="first_name", right="first_name",
                    method="metaphone_match", weight=2.0,
                ),
            ],
            allow_udfs=False,
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_udf_usage(config)
        msg = str(exc_info.value)
        assert "jaro_winkler" in msg
        assert "metaphone_match" in msg


# ---------------------------------------------------------------------------
# skip_stages
# ---------------------------------------------------------------------------


class TestSkipStages:
    def test_skip_stages_excludes_from_dag(self):
        config = _make_config(skip_stages=["term_frequencies"])
        pipeline = Pipeline(config)
        assert "term_frequencies" not in pipeline.stage_names

    def test_skip_stages_empty_has_no_effect(self):
        config = _make_config(skip_stages=[])
        pipeline = Pipeline(config)
        assert "term_frequencies" in pipeline.stage_names

    def test_skip_stages_default_includes_all(self):
        config = _make_config()
        pipeline = Pipeline(config)
        assert "feature_engineering" in pipeline.stage_names
        assert "term_frequencies" in pipeline.stage_names

    def test_skip_stages_merges_with_python_api_excludes(self):
        config = _make_config(skip_stages=["term_frequencies"])
        pipeline = Pipeline(config, exclude_stages={"clustering"})
        assert "term_frequencies" not in pipeline.stage_names
        assert "clustering" not in pipeline.stage_names

    def test_skip_cluster_quality(self):
        """Skipping a conditional stage that doesn't exist is safe."""
        config = _make_config(skip_stages=["cluster_quality"])
        pipeline = Pipeline(config)
        assert "cluster_quality" not in pipeline.stage_names

    def test_build_pipeline_dag_respects_skip(self):
        config = _make_config(skip_stages=["term_frequencies"])
        # skip_stages flows through Pipeline, but test build_pipeline_dag directly
        dag = build_pipeline_dag(config, exclude_stages={"term_frequencies"})
        assert "term_frequencies" not in dag.stage_names

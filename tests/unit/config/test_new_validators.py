"""Tests for new configuration validators.

Tests validate_incremental_config, validate_clustering_compatibility,
validate_threshold_consistency, validate_name_collisions,
and validate_feature_dependencies.
"""

from __future__ import annotations

import warnings

import pytest

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ClusteringConfig,
    ColumnMapping,
    ComparisonDef,
    FeatureDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    IncrementalConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    ReconciliationConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.config.validators import (
    validate_clustering_compatibility,
    validate_feature_dependencies,
    validate_incremental_config,
    validate_name_collisions,
    validate_threshold_consistency,
)
from bq_entity_resolution.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(
    name: str = "customers",
    columns: list[str] | None = None,
    updated_at: str = "updated_at",
) -> SourceConfig:
    cols = columns or ["a", "b"]
    return SourceConfig(
        name=name,
        table=f"proj.ds.{name}",
        unique_key="id",
        updated_at=updated_at,
        columns=[ColumnMapping(name=c) for c in cols],
    )


def _make_config(
    sources: list[SourceConfig] | None = None,
    incremental: IncrementalConfig | None = None,
    reconciliation: ReconciliationConfig | None = None,
    matching_tiers: list[MatchingTierConfig] | None = None,
    feature_engineering: FeatureEngineeringConfig | None = None,
) -> PipelineConfig:
    sources = sources or [_make_source()]
    fe = feature_engineering or FeatureEngineeringConfig(
        blocking_keys=[
            BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
        ],
    )
    tiers = matching_tiers or [
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
    ]
    return PipelineConfig(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=sources,
        feature_engineering=fe,
        matching_tiers=tiers,
        incremental=incremental or IncrementalConfig(enabled=False),
        reconciliation=reconciliation or ReconciliationConfig(),
    )


# ---------------------------------------------------------------------------
# validate_incremental_config
# ---------------------------------------------------------------------------

class TestValidateIncrementalConfig:
    """Tests for validate_incremental_config."""

    def test_disabled_incremental_passes(self):
        """No errors when incremental is disabled."""
        config = _make_config(incremental=IncrementalConfig(enabled=False))
        # Should not raise
        validate_incremental_config(config)

    def test_valid_incremental_config_passes(self):
        config = _make_config(
            incremental=IncrementalConfig(
                enabled=True,
                cursor_columns=["updated_at"],
            ),
        )
        validate_incremental_config(config)

    def test_empty_cursor_columns_raises(self):
        """Pydantic validator rejects empty cursor_columns at model level."""
        with pytest.raises(Exception):
            IncrementalConfig(enabled=True, cursor_columns=[])

    def test_source_without_updated_at_raises(self):
        """Source missing updated_at raises at model validation time."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="non-empty"):
            SourceConfig(
                name="customers",
                table="proj.ds.customers",
                unique_key="id",
                updated_at="",
                columns=[ColumnMapping(name="a")],
            )


# ---------------------------------------------------------------------------
# validate_clustering_compatibility
# ---------------------------------------------------------------------------

class TestValidateClusteringCompatibility:
    """Tests for validate_clustering_compatibility."""

    def test_connected_components_no_warning(self):
        """connected_components is compatible with incremental."""
        config = _make_config(
            incremental=IncrementalConfig(enabled=True, cursor_columns=["updated_at"]),
            reconciliation=ReconciliationConfig(
                clustering=ClusteringConfig(method="connected_components"),
            ),
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_clustering_compatibility(config)
            assert len(w) == 0

    def test_star_with_incremental_warns(self):
        """star + incremental should emit UserWarning."""
        config = _make_config(
            incremental=IncrementalConfig(enabled=True, cursor_columns=["updated_at"]),
            reconciliation=ReconciliationConfig(
                clustering=ClusteringConfig(method="star"),
            ),
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_clustering_compatibility(config)
            assert len(w) == 1
            assert "star" in str(w[0].message)
            assert issubclass(w[0].category, UserWarning)

    def test_best_match_with_incremental_warns(self):
        """best_match + incremental should emit UserWarning."""
        config = _make_config(
            incremental=IncrementalConfig(enabled=True, cursor_columns=["updated_at"]),
            reconciliation=ReconciliationConfig(
                clustering=ClusteringConfig(method="best_match"),
            ),
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_clustering_compatibility(config)
            assert len(w) == 1
            assert "best_match" in str(w[0].message)

    def test_star_without_incremental_no_warning(self):
        """star is fine when incremental is disabled."""
        config = _make_config(
            incremental=IncrementalConfig(enabled=False),
            reconciliation=ReconciliationConfig(
                clustering=ClusteringConfig(method="star"),
            ),
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_clustering_compatibility(config)
            assert len(w) == 0


# ---------------------------------------------------------------------------
# validate_threshold_consistency
# ---------------------------------------------------------------------------

class TestValidateThresholdConsistency:
    """Tests for validate_threshold_consistency."""

    def test_sum_without_match_threshold_no_warning(self):
        """Normal sum config should not warn."""
        tiers = [
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
        ]
        config = _make_config(matching_tiers=tiers)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_threshold_consistency(config)
            threshold_warnings = [
                x for x in w if "match_threshold" in str(x.message)
            ]
            assert len(threshold_warnings) == 0

    def test_sum_with_match_threshold_warns(self):
        """match_threshold with method=sum is a misconfiguration."""
        tiers = [
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk"])],
                ),
                comparisons=[
                    ComparisonDef(left="a", right="a", method="exact"),
                ],
                threshold=ThresholdConfig(
                    method="sum",
                    min_score=1.0,
                    match_threshold=0.5,
                ),
            ),
        ]
        config = _make_config(matching_tiers=tiers)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_threshold_consistency(config)
            threshold_warnings = [
                x for x in w if "match_threshold" in str(x.message)
            ]
            assert len(threshold_warnings) == 1
            assert "min_score" in str(threshold_warnings[0].message)

    def test_fellegi_sunter_with_match_threshold_no_warning(self):
        """match_threshold is valid for fellegi_sunter."""
        tiers = [
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk"])],
                ),
                comparisons=[
                    ComparisonDef(left="a", right="a", method="exact"),
                ],
                threshold=ThresholdConfig(
                    method="fellegi_sunter",
                    match_threshold=0.5,
                ),
            ),
        ]
        config = _make_config(matching_tiers=tiers)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_threshold_consistency(config)
            threshold_warnings = [
                x for x in w if "match_threshold" in str(x.message)
            ]
            assert len(threshold_warnings) == 0


# ---------------------------------------------------------------------------
# validate_name_collisions
# ---------------------------------------------------------------------------

class TestValidateNameCollisions:
    """Tests for validate_name_collisions."""

    def test_no_collision_passes(self):
        """Distinct feature and blocking key names should pass."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(name="name_clean", function="name_clean", input="a"),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk_name", function="farm_fingerprint", inputs=["name_clean"]),
            ],
        )
        tiers = [
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_name"])],
                ),
                comparisons=[
                    ComparisonDef(left="a", right="a", method="exact"),
                ],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            ),
        ]
        config = _make_config(feature_engineering=fe, matching_tiers=tiers)
        # Should not raise
        validate_name_collisions(config)

    def test_collision_raises(self):
        """Feature name == blocking key name should raise ConfigurationError."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(name="email_hash", function="name_clean", input="a"),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(
                    name="email_hash",
                    function="farm_fingerprint",
                    inputs=["a"],
                ),
            ],
        )
        tiers = [
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["email_hash"])],
                ),
                comparisons=[
                    ComparisonDef(left="a", right="a", method="exact"),
                ],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            ),
        ]
        config = _make_config(feature_engineering=fe, matching_tiers=tiers)
        with pytest.raises(ConfigurationError, match="collide"):
            validate_name_collisions(config)

    def test_collision_message_includes_name(self):
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(name="overlap_key", function="name_clean", input="a"),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(
                    name="overlap_key",
                    function="farm_fingerprint",
                    inputs=["a"],
                ),
            ],
        )
        tiers = [
            MatchingTierConfig(
                name="t1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["overlap_key"])],
                ),
                comparisons=[
                    ComparisonDef(left="a", right="a", method="exact"),
                ],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            ),
        ]
        config = _make_config(feature_engineering=fe, matching_tiers=tiers)
        with pytest.raises(ConfigurationError, match="overlap_key"):
            validate_name_collisions(config)


# ---------------------------------------------------------------------------
# validate_feature_dependencies
# ---------------------------------------------------------------------------

class TestValidateFeatureDependencies:
    """Tests for validate_feature_dependencies cycle detection."""

    def test_valid_chain_passes(self):
        """A -> B dependency chain is valid."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(name="raw_name", function="upper_trim", input="a"),
                    FeatureDef(
                        name="clean_name",
                        function="name_clean",
                        input="raw_name",
                        depends_on=["raw_name"],
                    ),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        # Should not raise
        validate_feature_dependencies(config)

    def test_cycle_raises(self):
        """Circular dependency A -> B -> A should raise."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(
                        name="feat_a",
                        function="upper_trim",
                        input="a",
                        depends_on=["feat_b"],
                    ),
                    FeatureDef(
                        name="feat_b",
                        function="upper_trim",
                        input="a",
                        depends_on=["feat_a"],
                    ),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        with pytest.raises(ConfigurationError, match="[Cc]ircular"):
            validate_feature_dependencies(config)

    def test_self_cycle_raises(self):
        """Feature depending on itself should raise."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(
                        name="self_ref",
                        function="upper_trim",
                        input="a",
                        depends_on=["self_ref"],
                    ),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        with pytest.raises(ConfigurationError, match="[Cc]ircular"):
            validate_feature_dependencies(config)

    def test_missing_dependency_raises(self):
        """Dependency on non-existent feature/column raises."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(
                        name="feat_a",
                        function="upper_trim",
                        input="a",
                        depends_on=["nonexistent_feature"],
                    ),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        with pytest.raises(ConfigurationError, match="nonexistent_feature"):
            validate_feature_dependencies(config)

    def test_no_features_passes(self):
        """Empty feature engineering should not raise."""
        fe = FeatureEngineeringConfig(
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        validate_feature_dependencies(config)

    def test_depends_on_source_column_passes(self):
        """Features can depend on source columns, not just other features."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(
                        name="feat_a",
                        function="upper_trim",
                        input="a",
                        depends_on=["a"],  # "a" is a source column
                    ),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        # Should not raise (source column "a" is available)
        validate_feature_dependencies(config)

    def test_three_node_cycle_raises(self):
        """A -> B -> C -> A cycle should be detected."""
        fe = FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(
                features=[
                    FeatureDef(
                        name="feat_a",
                        function="upper_trim",
                        input="a",
                        depends_on=["feat_b"],
                    ),
                    FeatureDef(
                        name="feat_b",
                        function="upper_trim",
                        input="a",
                        depends_on=["feat_c"],
                    ),
                    FeatureDef(
                        name="feat_c",
                        function="upper_trim",
                        input="a",
                        depends_on=["feat_a"],
                    ),
                ],
            ),
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["a"]),
            ],
        )
        config = _make_config(feature_engineering=fe)
        with pytest.raises(ConfigurationError, match="[Cc]ircular"):
            validate_feature_dependencies(config)

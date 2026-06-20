"""Tests for type-driven default signal injection."""
from __future__ import annotations

from bq_entity_resolution.config.entity_types import (
    ENTITY_TYPE_TEMPLATES,
    DefaultSignal,
    EntityTypeTemplate,
    _resolved_cache,
    register_entity_type,
)
from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    HardNegativeDef,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)


def _config_with_signals(
    entity_type: str | None = None,
    features: list[FeatureDef] | None = None,
    global_hard_negatives: list[HardNegativeDef] | None = None,
    custom_entity_types: dict | None = None,
) -> PipelineConfig:
    """Build a config for testing signal injection."""
    return PipelineConfig(
        project=ProjectConfig(name="test", bq_project="test-proj"),
        sources=[
            SourceConfig(
                name="src",
                table="test-proj.ds.tbl",
                unique_key="id",
                updated_at="updated_at",
                entity_type=entity_type,
                columns=[ColumnMapping(name="first_name", role="first_name")],
            ),
        ],
        feature_engineering=FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(features=features or []),
            blocking_keys=[
                BlockingKeyDef(name="bk_test", function="soundex", inputs=["first_name"]),
            ],
        ),
        matching_tiers=[
            MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_test"])],
                ),
                comparisons=[
                    ComparisonDef(left="first_name", right="first_name", method="exact"),
                ],
                threshold=ThresholdConfig(min_score=1.0),
            ),
        ],
        global_hard_negatives=global_hard_negatives or [],
        custom_entity_types=custom_entity_types or {},
    )


class TestSignalInjection:
    def test_no_entity_type_no_injection(self):
        """Without entity_type, no signals are injected."""
        config = _config_with_signals(entity_type=None)
        assert len(config.global_hard_negatives) == 0
        assert len(config.global_soft_signals) == 0

    def test_unknown_entity_type_no_injection(self):
        """Unknown entity type is silently skipped (validation catches later)."""
        config = _config_with_signals(entity_type="NonExistent")
        assert len(config.global_hard_negatives) == 0

    def test_signal_injected_when_feature_exists(self):
        """Default signals are injected when the referenced feature exists."""
        # Register a test type with a signal referencing 'test_feature'
        test_type = EntityTypeTemplate(
            name="_TestSignalType",
            default_signals=(
                DefaultSignal(
                    kind="hard_negative",
                    left="test_feature",
                    method="different",
                    action="disqualify",
                    severity="hn2_structural",
                    value=0.0,
                    category="test_cat",
                ),
            ),
        )
        register_entity_type(test_type)
        try:
            config = _config_with_signals(
                entity_type="_TestSignalType",
                features=[
                    FeatureDef(name="test_feature", function="name_clean", inputs=["first_name"]),
                ],
            )
            assert len(config.global_hard_negatives) == 1
            hn = config.global_hard_negatives[0]
            assert hn.left == "test_feature"
            assert hn.method == "different"
            assert hn.category == "test_cat"
            assert hn.entity_type_condition == "_testsignaltype"
        finally:
            ENTITY_TYPE_TEMPLATES.pop("_TestSignalType", None)
            _resolved_cache.clear()

    def test_signal_skipped_when_feature_missing(self):
        """Signals are not injected if the referenced feature doesn't exist."""
        test_type = EntityTypeTemplate(
            name="_TestMissing",
            default_signals=(
                DefaultSignal(
                    kind="hard_negative",
                    left="nonexistent_feature",
                    method="different",
                    category="test_cat",
                ),
            ),
        )
        register_entity_type(test_type)
        try:
            config = _config_with_signals(entity_type="_TestMissing")
            assert len(config.global_hard_negatives) == 0
        finally:
            ENTITY_TYPE_TEMPLATES.pop("_TestMissing", None)
            _resolved_cache.clear()

    def test_user_signal_takes_precedence(self):
        """User-defined signals with same (category, left) are not overridden."""
        test_type = EntityTypeTemplate(
            name="_TestPrecedence",
            default_signals=(
                DefaultSignal(
                    kind="hard_negative",
                    left="test_feature",
                    method="different",
                    action="disqualify",
                    severity="hn2_structural",
                    value=0.0,
                    category="my_cat",
                ),
            ),
        )
        register_entity_type(test_type)
        try:
            user_hn = HardNegativeDef(
                left="test_feature",
                method="null_either",
                action="penalize",
                penalty=5.0,
                category="my_cat",
            )
            config = _config_with_signals(
                entity_type="_TestPrecedence",
                features=[
                    FeatureDef(name="test_feature", function="name_clean", inputs=["first_name"]),
                ],
                global_hard_negatives=[user_hn],
            )
            # Only 1 signal: the user's
            assert len(config.global_hard_negatives) == 1
            assert config.global_hard_negatives[0].method == "null_either"
        finally:
            ENTITY_TYPE_TEMPLATES.pop("_TestPrecedence", None)
            _resolved_cache.clear()

    def test_soft_signal_injection(self):
        """Soft signals from templates are injected correctly."""
        test_type = EntityTypeTemplate(
            name="_TestSoftSignal",
            default_signals=(
                DefaultSignal(
                    kind="soft_signal",
                    left="test_feature",
                    method="exact",
                    value=2.5,
                    category="soft_cat",
                ),
            ),
        )
        register_entity_type(test_type)
        try:
            config = _config_with_signals(
                entity_type="_TestSoftSignal",
                features=[
                    FeatureDef(name="test_feature", function="name_clean", inputs=["first_name"]),
                ],
            )
            assert len(config.global_soft_signals) == 1
            ss = config.global_soft_signals[0]
            assert ss.left == "test_feature"
            assert ss.method == "exact"
            assert ss.bonus == 2.5
            assert ss.category == "soft_cat"
        finally:
            ENTITY_TYPE_TEMPLATES.pop("_TestSoftSignal", None)
            _resolved_cache.clear()

    def test_custom_type_signals_injected(self):
        """Signals from custom entity types defined in YAML are injected."""
        config = _config_with_signals(
            entity_type="_YamlType",
            features=[
                FeatureDef(name="yaml_feature", function="name_clean", inputs=["first_name"]),
            ],
            custom_entity_types={
                "_YamlType": {
                    "valid_roles": ["first_name"],
                    "default_signals": [
                        {
                            "kind": "hard_negative",
                            "left": "yaml_feature",
                            "method": "different",
                            "action": "disqualify",
                            "severity": "hn2_structural",
                            "value": 0.0,
                            "category": "yaml_cat",
                        },
                    ],
                },
            },
        )
        assert len(config.global_hard_negatives) == 1
        assert config.global_hard_negatives[0].left == "yaml_feature"
        # Cleanup
        ENTITY_TYPE_TEMPLATES.pop("_YamlType", None)
        _resolved_cache.clear()

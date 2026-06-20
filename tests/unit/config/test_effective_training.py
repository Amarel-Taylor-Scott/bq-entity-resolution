"""Tests for effective_training_config() on PipelineConfig."""

from bq_entity_resolution.config.schema import (
    ActiveLearningConfig,
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    LabelFeedbackConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
    TrainingConfig,
)


def _make_config(**overrides) -> PipelineConfig:
    """Build a config for training config tests."""
    defaults = dict(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=[SourceConfig(
            name="src",
            table="proj.ds.src",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="email")],
        )],
        feature_engineering=FeatureEngineeringConfig(
            blocking_keys=[BlockingKeyDef(
                name="bk_email",
                function="farm_fingerprint",
                inputs=["email"],
            )],
        ),
        matching_tiers=[MatchingTierConfig(
            name="exact",
            blocking=TierBlockingConfig(
                paths=[BlockingPathDef(keys=["bk_email"])],
            ),
            comparisons=[ComparisonDef(
                left="email", right="email", method="exact",
            )],
            threshold=ThresholdConfig(method="sum", min_score=1.0),
        )],
    )
    defaults.update(overrides)
    return PipelineConfig(**defaults)


class TestEffectiveTrainingConfig:
    """Test the effective_training_config() resolution logic."""

    def test_tier_level_training_takes_priority(self):
        """Tier-level training config overrides everything."""
        tier_training = TrainingConfig(method="em", em_max_iterations=20)
        config = _make_config(
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(
                    left="email", right="email", method="exact",
                )],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
                training=tier_training,
            )],
        )
        tier = config.matching_tiers[0]
        effective = config.effective_training_config(tier)
        assert effective.method == "em"
        assert effective.em_max_iterations == 20

    def test_auto_retrain_wires_labels_table(self):
        """When auto_retrain=True, training method becomes 'labeled'."""
        config = _make_config(
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(
                    left="email", right="email", method="exact",
                )],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
                active_learning=ActiveLearningConfig(
                    enabled=True,
                    label_feedback=LabelFeedbackConfig(
                        enabled=True,
                        auto_retrain=True,
                    ),
                ),
            )],
        )
        tier = config.matching_tiers[0]
        effective = config.effective_training_config(tier)
        assert effective.method == "labeled"
        assert "al_labels" in effective.labeled_pairs_table

    def test_falls_back_to_global_training(self):
        """When no tier training and no auto_retrain, use global."""
        config = _make_config(
            training=TrainingConfig(method="labeled", labeled_pairs_table="proj.ds.labels"),
        )
        tier = config.matching_tiers[0]
        effective = config.effective_training_config(tier)
        assert effective.method == "labeled"
        assert effective.labeled_pairs_table == "proj.ds.labels"

    def test_default_is_none(self):
        """Default: no training (method=none)."""
        config = _make_config()
        tier = config.matching_tiers[0]
        effective = config.effective_training_config(tier)
        assert effective.method == "none"

    def test_auto_retrain_disabled_falls_through(self):
        """When auto_retrain=False, don't auto-wire labels."""
        config = _make_config(
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(
                    left="email", right="email", method="exact",
                )],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
                active_learning=ActiveLearningConfig(
                    enabled=True,
                    label_feedback=LabelFeedbackConfig(
                        enabled=True,
                        auto_retrain=False,
                    ),
                ),
            )],
        )
        tier = config.matching_tiers[0]
        effective = config.effective_training_config(tier)
        assert effective.method == "none"

    def test_tier_training_overrides_auto_retrain(self):
        """Explicit tier training takes priority over auto_retrain."""
        config = _make_config(
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(
                    left="email", right="email", method="exact",
                )],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
                training=TrainingConfig(method="em"),
                active_learning=ActiveLearningConfig(
                    enabled=True,
                    label_feedback=LabelFeedbackConfig(
                        enabled=True,
                        auto_retrain=True,
                    ),
                ),
            )],
        )
        tier = config.matching_tiers[0]
        effective = config.effective_training_config(tier)
        assert effective.method == "em"  # tier training wins

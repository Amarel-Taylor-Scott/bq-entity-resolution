"""Tests for label ingestion and retrain feedback loop."""

from bq_entity_resolution.config.schema import (
    ActiveLearningConfig,
    LabelFeedbackConfig,
)
from bq_entity_resolution.matching.active_learning import ActiveLearningEngine
from bq_entity_resolution.matching.parameters import ParameterEstimator

# ---------------------------------------------------------------
# Config model tests
# ---------------------------------------------------------------


def test_label_feedback_config_defaults():
    """Default label feedback config is disabled."""
    lf = LabelFeedbackConfig()
    assert not lf.enabled
    assert lf.feedback_table is None
    assert lf.min_labels_for_retrain == 50
    assert not lf.auto_retrain


def test_label_feedback_config_enabled():
    """Label feedback config can be enabled."""
    lf = LabelFeedbackConfig(
        enabled=True,
        feedback_table="proj.ds.labels",
        min_labels_for_retrain=100,
        auto_retrain=True,
    )
    assert lf.enabled
    assert lf.feedback_table == "proj.ds.labels"
    assert lf.min_labels_for_retrain == 100
    assert lf.auto_retrain


def test_active_learning_includes_label_feedback():
    """ActiveLearningConfig includes label_feedback field."""
    al = ActiveLearningConfig(enabled=True)
    assert al.label_feedback is not None
    assert not al.label_feedback.enabled


def test_active_learning_with_feedback():
    """ActiveLearningConfig with feedback enabled."""
    al = ActiveLearningConfig(
        enabled=True,
        label_feedback=LabelFeedbackConfig(enabled=True),
    )
    assert al.label_feedback.enabled


# ---------------------------------------------------------------
# ActiveLearningEngine: label ingestion SQL
# ---------------------------------------------------------------


def test_label_ingestion_sql_generates(sample_config):
    """Label ingestion SQL renders successfully."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.active_learning.enabled = True

    sql = engine.generate_label_ingestion_sql(tier)
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "MERGE INTO" in sql
    assert "human_label" in sql
    assert "is_match" in sql
    assert "al_labels" in sql


def test_label_ingestion_uses_custom_table(sample_config):
    """Custom feedback table is used when configured."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.active_learning.enabled = True
    tier.active_learning.label_feedback = LabelFeedbackConfig(
        enabled=True,
        feedback_table="proj.custom.my_labels",
    )

    sql = engine.generate_label_ingestion_sql(tier)
    assert "proj.custom.my_labels" in sql


def test_label_ingestion_includes_tier_name(sample_config):
    """Ingested labels are tagged with the tier name."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.active_learning.enabled = True

    sql = engine.generate_label_ingestion_sql(tier)
    assert tier.name in sql


# ---------------------------------------------------------------
# ActiveLearningEngine: label count SQL
# ---------------------------------------------------------------


def test_label_count_sql(sample_config):
    """Label count SQL generates correct query."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.active_learning.enabled = True

    sql = engine.generate_label_count_sql(tier)
    assert "COUNT(*)" in sql
    assert "label_count" in sql
    assert tier.name in sql


# ---------------------------------------------------------------
# ParameterEstimator: reestimation SQL
# ---------------------------------------------------------------


def test_reestimation_sql_generates(sample_config):
    """Reestimation SQL renders from labels table."""
    estimator = ParameterEstimator(sample_config)

    tier = sample_config.matching_tiers[1]  # fuzzy tier
    sql = estimator.generate_reestimation_sql(tier)
    assert "al_labels" in sql  # Uses default labels table


def test_reestimation_custom_labels_table(sample_config):
    """Reestimation uses custom labels table when specified."""
    estimator = ParameterEstimator(sample_config)

    tier = sample_config.matching_tiers[1]
    sql = estimator.generate_reestimation_sql(
        tier, labels_tbl="proj.custom.labels"
    )
    assert "proj.custom.labels" in sql

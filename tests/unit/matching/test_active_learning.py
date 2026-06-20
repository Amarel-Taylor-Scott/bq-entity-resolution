"""Tests for active learning engine."""

from bq_entity_resolution.matching.active_learning import ActiveLearningEngine


def test_review_queue_sql_sum_based(sample_config):
    """Review queue SQL generates for sum-based tiers."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.active_learning.enabled = True
    tier.active_learning.queue_size = 100

    sql = engine.generate_review_queue_sql(tier)
    assert "CREATE OR REPLACE TABLE" in sql
    assert "human_label" in sql
    assert "uncertainty" in sql
    assert "LIMIT 100" in sql
    assert "queued_at" in sql


def test_review_queue_sql_fellegi_sunter(sample_config):
    """Review queue SQL generates differently for F-S tiers."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.threshold.method = "fellegi_sunter"
    tier.active_learning.enabled = True
    tier.active_learning.queue_size = 200
    tier.active_learning.uncertainty_window = 0.2

    sql = engine.generate_review_queue_sql(tier)
    assert "CREATE OR REPLACE TABLE" in sql
    assert "match_confidence" in sql
    assert "0.5" in sql  # F-S uses distance from 0.5
    assert "LIMIT 200" in sql
    assert "0.2" in sql  # uncertainty_window


def test_review_queue_custom_table(sample_config):
    """Custom review queue table name is used."""
    engine = ActiveLearningEngine(sample_config)

    tier = sample_config.matching_tiers[0]
    tier.active_learning.enabled = True
    tier.active_learning.review_queue_table = "proj.dataset.my_review_queue"

    sql = engine.generate_review_queue_sql(tier)
    assert "proj.dataset.my_review_queue" in sql

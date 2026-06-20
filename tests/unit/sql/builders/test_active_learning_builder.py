"""Tests for the active learning SQL builder."""

from bq_entity_resolution.sql.builders.active_learning import (
    ActiveLearningParams,
    build_active_learning_sql,
)


def test_active_learning_fellegi_sunter():
    """F-S active learning sorts by distance from 0.5 confidence."""
    params = ActiveLearningParams(
        review_table="proj.ds.review_queue",
        matches_table="proj.ds.matches",
        queue_size=200,
        uncertainty_window=0.3,
        is_fellegi_sunter=True,
    )
    expr = build_active_learning_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "ABS(match_confidence - 0.5)" in sql
    assert "uncertainty" in sql
    assert "human_label" in sql
    assert "queued_at" in sql
    assert "LIMIT 200" in sql
    assert "<= 0.3" in sql


def test_active_learning_sum_scoring():
    """Sum-based active learning sorts by distance from threshold."""
    params = ActiveLearningParams(
        review_table="proj.ds.review_queue",
        matches_table="proj.ds.matches",
        queue_size=100,
        is_fellegi_sunter=False,
        min_score=3.5,
    )
    expr = build_active_learning_sql(params)
    sql = expr.render()

    assert "ABS(match_total_score - 3.5)" in sql
    assert "LIMIT 100" in sql


def test_active_learning_sum_zero_threshold():
    """Sum scoring with zero threshold falls back to confidence-based."""
    params = ActiveLearningParams(
        review_table="proj.ds.review_queue",
        matches_table="proj.ds.matches",
        queue_size=50,
        is_fellegi_sunter=False,
        min_score=0.0,
    )
    expr = build_active_learning_sql(params)
    sql = expr.render()

    assert "ABS(match_confidence - 0.5)" in sql


def test_active_learning_returns_sql_expression():
    """Builder returns SQLExpression."""
    params = ActiveLearningParams(
        review_table="p.d.review",
        matches_table="p.d.matches",
    )
    expr = build_active_learning_sql(params)
    assert expr.is_raw is True
    assert isinstance(expr.render(), str)

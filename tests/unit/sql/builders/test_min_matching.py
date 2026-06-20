"""Tests for min_matching_comparisons in sum and Fellegi-Sunter scoring builders."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.models.matching import ThresholdConfig
from bq_entity_resolution.sql.builders.comparison.fellegi_sunter import (
    build_fellegi_sunter_sql,
)
from bq_entity_resolution.sql.builders.comparison.models import (
    ComparisonDef,
    ComparisonLevel,
    FellegiSunterParams,
    SumScoringParams,
    Threshold,
)
from bq_entity_resolution.sql.builders.comparison.sum_scoring import (
    build_sum_scoring_sql,
)


def _sum_params(**overrides) -> SumScoringParams:
    """Create minimal SumScoringParams."""
    defaults = dict(
        tier_name="t1",
        tier_index=0,
        matches_table="proj.ds.matches",
        candidates_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        comparisons=[
            ComparisonDef(name="name", sql_expr="l.name = r.name", weight=2.0),
            ComparisonDef(name="email", sql_expr="l.email = r.email", weight=3.0),
            ComparisonDef(name="phone", sql_expr="l.phone = r.phone", weight=1.5),
        ],
        threshold=Threshold(min_score=1.0),
        max_possible_score=6.5,
    )
    defaults.update(overrides)
    return SumScoringParams(**defaults)


def _fs_params(**overrides) -> FellegiSunterParams:
    """Create minimal FellegiSunterParams."""
    defaults = dict(
        tier_name="fs_tier",
        tier_index=0,
        matches_table="proj.ds.matches",
        candidates_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        comparisons=[
            ComparisonDef(
                name="name",
                levels=[
                    ComparisonLevel(
                        label="exact", sql_expr="l.name = r.name", log_weight=3.0
                    ),
                    ComparisonLevel(label="else", sql_expr=None, log_weight=-1.0),
                ],
            ),
            ComparisonDef(
                name="email",
                levels=[
                    ComparisonLevel(
                        label="exact", sql_expr="l.email = r.email", log_weight=4.0
                    ),
                    ComparisonLevel(label="else", sql_expr=None, log_weight=-2.0),
                ],
            ),
        ],
        threshold=Threshold(min_score=2.0),
    )
    defaults.update(overrides)
    return FellegiSunterParams(**defaults)


class TestMinMatchingSumScoring:
    """Test min_matching_comparisons in sum-based scoring."""

    def test_zero_adds_no_clause(self):
        """min_matching_comparisons=0 adds no extra WHERE clause."""
        params = _sum_params(threshold=Threshold(min_score=1.0, min_matching_comparisons=0))
        sql = build_sum_scoring_sql(params).render()
        # Should not have the CASE WHEN counting pattern
        assert "CASE WHEN l.name = r.name THEN 1 ELSE 0 END)" not in sql

    def test_positive_value_adds_counting_clause(self):
        """min_matching_comparisons=2 adds CASE WHEN counting clause."""
        params = _sum_params(
            threshold=Threshold(min_score=1.0, min_matching_comparisons=2)
        )
        sql = build_sum_scoring_sql(params).render()
        # Should contain CASE WHEN ... THEN 1 ELSE 0 END for each comparison
        assert "CASE WHEN l.name = r.name THEN 1 ELSE 0 END)" in sql
        assert "CASE WHEN l.email = r.email THEN 1 ELSE 0 END)" in sql
        assert "CASE WHEN l.phone = r.phone THEN 1 ELSE 0 END)" in sql
        assert ">= 2" in sql

    def test_min_matching_equals_total_comparisons(self):
        """min_matching_comparisons can equal total number of comparisons."""
        params = _sum_params(
            threshold=Threshold(min_score=1.0, min_matching_comparisons=3)
        )
        sql = build_sum_scoring_sql(params).render()
        assert ">= 3" in sql

    def test_min_one_adds_clause(self):
        """min_matching_comparisons=1 adds counting clause."""
        params = _sum_params(
            threshold=Threshold(min_score=1.0, min_matching_comparisons=1)
        )
        sql = build_sum_scoring_sql(params).render()
        assert ">= 1" in sql


class TestMinMatchingFellegiSunter:
    """Test min_matching_comparisons in Fellegi-Sunter scoring."""

    def test_zero_adds_no_clause(self):
        """min_matching_comparisons=0 adds no extra clause for F-S."""
        params = _fs_params(threshold=Threshold(min_score=2.0, min_matching_comparisons=0))
        sql = build_fellegi_sunter_sql(params).render()
        # F-S uses log_weight columns instead of raw sql_expr
        assert "THEN 1 ELSE 0 END)" not in sql

    def test_positive_value_adds_log_weight_counting(self):
        """min_matching_comparisons=2 adds log-weight > 0 counting for F-S."""
        params = _fs_params(
            threshold=Threshold(min_score=2.0, min_matching_comparisons=2)
        )
        sql = build_fellegi_sunter_sql(params).render()
        # F-S checks log_weight columns > 0 instead of raw sql expressions
        assert "match_log_weight_name" in sql
        assert "match_log_weight_email" in sql
        assert "> 0" in sql
        assert ">= 2" in sql

    def test_zero_default(self):
        """Default min_matching_comparisons is 0."""
        params = _fs_params()
        assert params.threshold.min_matching_comparisons == 0


class TestMinMatchingConfigValidation:
    """Test ThresholdConfig validates min_matching_comparisons."""

    def test_negative_value_rejected(self):
        """Negative min_matching_comparisons is rejected by ThresholdConfig."""
        with pytest.raises(ValueError, match="min_matching_comparisons must be >= 0"):
            ThresholdConfig(min_score=1.0, min_matching_comparisons=-1)

    def test_zero_accepted(self):
        """Zero is a valid value for min_matching_comparisons."""
        config = ThresholdConfig(min_score=1.0, min_matching_comparisons=0)
        assert config.min_matching_comparisons == 0

    def test_positive_accepted(self):
        """Positive integers are valid for min_matching_comparisons."""
        config = ThresholdConfig(min_score=1.0, min_matching_comparisons=5)
        assert config.min_matching_comparisons == 5

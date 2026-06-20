"""Tests for data quality scoring."""

from __future__ import annotations

from bq_entity_resolution.monitoring.data_quality import (
    DataQualityScore,
    DataQualityScorer,
)


class TestDataQualityScorer:
    """Tests for DataQualityScorer.compute()."""

    def test_perfect_score_no_issues(self):
        scorer = DataQualityScorer()
        result = scorer.compute()
        assert result.overall_score == 100
        assert len(result.details) == 0

    def test_placeholder_rate_above_5pct(self):
        scorer = DataQualityScorer()
        result = scorer.compute(placeholder_rates={"phone": 0.08})
        assert result.overall_score == 90
        assert len(result.details) == 1

    def test_placeholder_rate_above_20pct(self):
        scorer = DataQualityScorer()
        result = scorer.compute(placeholder_rates={"phone": 0.25})
        assert result.overall_score == 75

    def test_null_rate_above_10pct(self):
        scorer = DataQualityScorer()
        result = scorer.compute(null_rates={"email": 0.15})
        assert result.overall_score == 95

    def test_null_rate_above_50pct(self):
        scorer = DataQualityScorer()
        result = scorer.compute(null_rates={"email": 0.60})
        assert result.overall_score == 85

    def test_blocking_low_reduction(self):
        scorer = DataQualityScorer()
        result = scorer.compute(blocking_stats=[
            {
                "tier_name": "exact",
                "reduction_ratio": 0.80,
                "max_candidates_per_entity": 50,
            },
        ])
        assert result.overall_score == 90

    def test_blocking_very_low_reduction(self):
        scorer = DataQualityScorer()
        result = scorer.compute(blocking_stats=[
            {
                "tier_name": "exact",
                "reduction_ratio": 0.30,
                "max_candidates_per_entity": 50,
            },
        ])
        assert result.overall_score == 75

    def test_large_max_bucket(self):
        scorer = DataQualityScorer()
        result = scorer.compute(blocking_stats=[
            {
                "tier_name": "exact",
                "reduction_ratio": 0.99,
                "max_candidates_per_entity": 15000,
            },
        ])
        assert result.overall_score == 85

    def test_moderate_max_bucket(self):
        scorer = DataQualityScorer()
        result = scorer.compute(blocking_stats=[
            {
                "tier_name": "exact",
                "reduction_ratio": 0.99,
                "max_candidates_per_entity": 5000,
            },
        ])
        assert result.overall_score == 95

    def test_combined_deductions(self):
        scorer = DataQualityScorer()
        result = scorer.compute(
            placeholder_rates={"phone": 0.25},
            null_rates={"email": 0.60},
            blocking_stats=[
                {
                    "tier_name": "fuzzy",
                    "reduction_ratio": 0.40,
                    "max_candidates_per_entity": 20000,
                },
            ],
        )
        # -25 (placeholder) -15 (null) -25 (blocking) -15 (bucket) = 20
        assert result.overall_score == 20

    def test_floor_at_zero(self):
        scorer = DataQualityScorer()
        result = scorer.compute(
            placeholder_rates={f"col{i}": 0.25 for i in range(10)},
        )
        assert result.overall_score == 0

    def test_component_scores(self):
        scorer = DataQualityScorer()
        result = scorer.compute(
            placeholder_rates={"phone": 0.08},
            null_rates={"email": 0.15},
        )
        assert "placeholder" in result.component_scores
        assert "null_rates" in result.component_scores
        assert "blocking" in result.component_scores
        assert result.component_scores["placeholder"] == 90
        assert result.component_scores["null_rates"] == 95

    def test_empty_inputs(self):
        scorer = DataQualityScorer()
        result = scorer.compute(
            placeholder_rates={},
            null_rates={},
            blocking_stats=[],
        )
        assert result.overall_score == 100

    def test_multiple_columns(self):
        scorer = DataQualityScorer()
        result = scorer.compute(
            placeholder_rates={"phone": 0.08, "email": 0.06},
        )
        # -10 (phone) -10 (email) = 80
        assert result.overall_score == 80


class TestDataQualityScore:
    """Tests for DataQualityScore dataclass."""

    def test_construction(self):
        score = DataQualityScore(
            overall_score=85,
            component_scores={"placeholder": 90},
            details=["test detail"],
        )
        assert score.overall_score == 85
        assert score.component_scores == {"placeholder": 90}
        assert score.details == ["test detail"]

    def test_default_values(self):
        score = DataQualityScore(overall_score=100)
        assert score.component_scores == {}
        assert score.details == []

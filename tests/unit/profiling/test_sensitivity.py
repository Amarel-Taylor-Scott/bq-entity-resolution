"""Tests for the weight sensitivity analyzer module."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.profiling.weight_sensitivity import WeightSensitivityAnalyzer


@pytest.fixture()
def sample_config() -> PipelineConfig:
    return PipelineConfig(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=[
            SourceConfig(
                name="src",
                table="proj.ds.t",
                unique_key="id",
                updated_at="u",
                columns=[ColumnMapping(name="c")],
            )
        ],
        feature_engineering=FeatureEngineeringConfig(
            blocking_keys=[
                BlockingKeyDef(name="bk", function="farm_fingerprint", inputs=["c"]),
            ],
        ),
        matching_tiers=[
            MatchingTierConfig(
                name="fuzzy",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk"])],
                ),
                comparisons=[
                    ComparisonDef(
                        left="first_name", right="first_name",
                        method="jaro_winkler", weight=3.0,
                    ),
                    ComparisonDef(left="last_name", right="last_name", method="exact", weight=5.0),
                    ComparisonDef(left="email", right="email", method="exact", weight=4.0),
                    ComparisonDef(left="state", right="state", method="exact", weight=0.5),
                ],
                threshold=ThresholdConfig(method="sum", min_score=8.0),
            )
        ],
    )


class TestContributionSQL:
    """Tests for contribution analysis SQL generation."""

    def test_generates_valid_sql(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_contribution_sql(tier)

        assert "contribution" in sql.lower() or "comparison_name" in sql
        assert "first_name__jaro_winkler" in sql
        assert "last_name__exact" in sql
        assert "email__exact" in sql
        assert "state__exact" in sql

    def test_includes_all_comparisons(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_contribution_sql(tier)

        # All comparison names appear
        for comp in tier.comparisons:
            safe_name = f"{comp.left}__{comp.method}"
            assert safe_name in sql

    def test_includes_weights(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_contribution_sql(tier)

        # Weights appear in SQL
        assert "3.0" in sql  # jaro_winkler weight
        assert "5.0" in sql  # last_name exact weight
        assert "4.0" in sql  # email exact weight

    def test_references_matches_table(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_contribution_sql(tier)
        assert "matches" in sql.lower()


class TestThresholdSweepSQL:
    """Tests for threshold sweep SQL generation."""

    def test_generates_union_all(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_threshold_sweep_sql(tier)

        assert "UNION ALL" in sql
        assert "threshold" in sql.lower()
        assert "match_count" in sql

    def test_includes_current_threshold(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_threshold_sweep_sql(tier)

        # Current threshold (8.0) should appear as one of the steps
        assert "8.0" in sql

    def test_scans_range_around_threshold(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_threshold_sweep_sql(tier)

        # Should have steps below and above current threshold
        assert "total_score >=" in sql
        assert "ORDER BY threshold" in sql

    def test_zero_threshold_scans_0_to_10(self, sample_config):
        sample_config.matching_tiers[0].threshold.min_score = 0
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_threshold_sweep_sql(tier)
        assert "0" in sql


class TestWeightImpactSQL:
    """Tests for weight impact analysis SQL generation."""

    def test_generates_for_each_comparison(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_weight_impact_sql(tier)

        assert "first_name__jaro_winkler" in sql
        assert "last_name__exact" in sql
        assert "matches_lost_if_halved" in sql
        assert "matches_gained_if_doubled" in sql

    def test_includes_current_weight(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_weight_impact_sql(tier)
        assert "current_weight" in sql

    def test_shows_threshold(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        tier = sample_config.matching_tiers[0]
        sql = analyzer.generate_weight_impact_sql(tier)
        assert "8.0" in sql  # threshold


class TestFormatReport:
    """Tests for report formatting."""

    def test_format_empty_rows(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        report = analyzer.format_contribution_report([], "fuzzy")
        assert "No match data" in report

    def test_format_with_data(self, sample_config):
        analyzer = WeightSensitivityAnalyzer(sample_config)
        rows = [
            {
                "comparison_name": "last_name__exact",
                "method": "exact",
                "weight": 5.0,
                "max_contribution_pct": 41.7,
                "importance": "HIGH",
                "total_matches": 1200,
                "avg_score": 12.0,
                "min_score": 8.1,
                "max_score": 12.5,
            },
            {
                "comparison_name": "state__exact",
                "method": "exact",
                "weight": 0.5,
                "max_contribution_pct": 4.2,
                "importance": "LOW",
                "total_matches": 1200,
                "avg_score": 12.0,
                "min_score": 8.1,
                "max_score": 12.5,
            },
        ]
        report = analyzer.format_contribution_report(rows, "fuzzy")
        assert "last_name__exact" in report
        assert "state__exact" in report
        assert "HIGH" in report
        assert "LOW" in report
        assert "1,200" in report

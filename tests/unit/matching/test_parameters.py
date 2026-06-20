"""Tests for Fellegi-Sunter parameter estimation."""

import math

from bq_entity_resolution.matching.parameters import (
    LevelParameters,
    ParameterEstimator,
    TierParameters,
)


def test_level_parameters_log_weight():
    """Log weight = log2(m/u)."""
    lp = LevelParameters(label="exact", m=0.9, u=0.1)
    assert abs(lp.log_weight - math.log2(9.0)) < 0.001


def test_level_parameters_equal_mu():
    """Equal m and u -> log weight = 0 (uninformative)."""
    lp = LevelParameters(label="test", m=0.5, u=0.5)
    assert abs(lp.log_weight) < 0.001


def test_level_parameters_clamping():
    """Extreme probabilities are clamped to prevent infinity."""
    lp = LevelParameters(label="test", m=1.0, u=0.0)
    # Should not be infinite
    assert math.isfinite(lp.log_weight)


def test_tier_parameters_log_prior_odds():
    """Prior odds = log2(p / (1-p))."""
    tp = TierParameters(tier_name="test", prior_match_prob=0.5)
    assert abs(tp.log_prior_odds) < 0.001  # 50/50 = log2(1) = 0

    tp2 = TierParameters(tier_name="test", prior_match_prob=0.1)
    assert tp2.log_prior_odds < 0  # 10% prior -> negative


def test_tier_parameters_clamped_prior():
    """Extreme prior probabilities are clamped."""
    tp = TierParameters(tier_name="test", prior_match_prob=0.0)
    assert math.isfinite(tp.log_prior_odds)

    tp2 = TierParameters(tier_name="test", prior_match_prob=1.0)
    assert math.isfinite(tp2.log_prior_odds)


def test_parse_estimation_results(sample_config):
    """Parse BigQuery result rows into TierParameters."""
    estimator = ParameterEstimator(sample_config)
    tier = sample_config.matching_tiers[0]

    rows = [
        {
            "comparison_name": "first_name_clean__exact",
            "level_label": "exact",
            "m_probability": 0.95,
            "u_probability": 0.08,
        },
        {
            "comparison_name": "first_name_clean__exact",
            "level_label": "else",
            "m_probability": 0.05,
            "u_probability": 0.92,
        },
    ]

    params = estimator.parse_estimation_results(tier, rows)
    assert params.tier_name == tier.name
    assert len(params.comparisons) == 1
    assert len(params.comparisons[0].levels) == 2
    assert params.comparisons[0].levels[0]["m"] == 0.95
    assert params.comparisons[0].levels[0]["u"] == 0.08


def test_extract_manual_params(sample_config):
    """Extract manual params for tiers without training."""
    estimator = ParameterEstimator(sample_config)
    tier = sample_config.matching_tiers[0]

    params = estimator.extract_manual_params(tier)
    assert params.tier_name == tier.name
    # Each comparison with no levels gets auto binary levels
    for cp in params.comparisons:
        assert len(cp.levels) == 2
        assert cp.levels[0]["label"] == "match"
        assert cp.levels[1]["label"] == "else"

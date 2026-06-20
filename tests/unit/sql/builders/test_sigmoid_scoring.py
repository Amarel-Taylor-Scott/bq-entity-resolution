"""Tests for sigmoid vs ratio confidence scoring in sum-based scoring builder."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.comparison.models import (
    ComparisonDef,
    SumScoringParams,
    Threshold,
)
from bq_entity_resolution.sql.builders.comparison.sum_scoring import build_sum_scoring_sql


def _make_params(**overrides) -> SumScoringParams:
    """Create minimal SumScoringParams with sensible defaults."""
    defaults = dict(
        tier_name="t1",
        tier_index=0,
        matches_table="proj.ds.matches",
        candidates_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        comparisons=[
            ComparisonDef(
                name="email",
                sql_expr="l.email_clean = r.email_clean",
                weight=3.0,
            ),
        ],
        threshold=Threshold(min_score=1.0),
        max_possible_score=3.0,
    )
    defaults.update(overrides)
    return SumScoringParams(**defaults)


class TestSigmoidConfidence:
    """Test that confidence_method='sigmoid' produces correct SQL."""

    def test_sigmoid_generates_exp_expression(self):
        """confidence_method='sigmoid' generates 1.0/(1.0+EXP(-1.0*...))."""
        params = _make_params(confidence_method="sigmoid")
        sql = build_sum_scoring_sql(params).render()
        assert "1.0 / (1.0 + EXP(-1.0 *" in sql

    def test_sigmoid_does_not_generate_nullif(self):
        """Sigmoid mode should NOT generate the ratio-based NULLIF pattern."""
        params = _make_params(confidence_method="sigmoid")
        sql = build_sum_scoring_sql(params).render()
        assert "NULLIF(" not in sql

    def test_sigmoid_rounds_to_four_decimals(self):
        """Sigmoid confidence is ROUND(..., 4)."""
        params = _make_params(confidence_method="sigmoid")
        sql = build_sum_scoring_sql(params).render()
        assert "ROUND(1.0 / (1.0 + EXP(-1.0 * match_total_score)), 4)" in sql


class TestRatioConfidence:
    """Test that confidence_method='ratio' (default) produces correct SQL."""

    def test_ratio_generates_nullif_expression(self):
        """Default ratio mode generates NULLIF-based confidence."""
        params = _make_params(confidence_method="ratio")
        sql = build_sum_scoring_sql(params).render()
        assert "NULLIF(" in sql

    def test_ratio_does_not_generate_exp(self):
        """Ratio mode should NOT generate EXP() sigmoid."""
        params = _make_params(confidence_method="ratio")
        sql = build_sum_scoring_sql(params).render()
        assert "EXP(-1.0" not in sql

    def test_ratio_is_default(self):
        """confidence_method defaults to 'ratio' when not specified."""
        params = _make_params()  # no confidence_method override
        assert params.confidence_method == "ratio"
        sql = build_sum_scoring_sql(params).render()
        assert "NULLIF(" in sql

    def test_ratio_uses_max_possible_score(self):
        """Ratio mode divides by max_possible_score via NULLIF."""
        params = _make_params(confidence_method="ratio", max_possible_score=10.0)
        sql = build_sum_scoring_sql(params).render()
        assert "NULLIF(10.0, 0)" in sql


class TestFixedConfidenceOverride:
    """Test that a fixed confidence value overrides both methods."""

    def test_fixed_confidence_overrides_sigmoid(self):
        """When confidence is set, neither sigmoid nor ratio is used."""
        params = _make_params(confidence=0.95, confidence_method="sigmoid")
        sql = build_sum_scoring_sql(params).render()
        assert "0.95 AS match_confidence" in sql
        assert "EXP(" not in sql
        assert "NULLIF(" not in sql

    def test_fixed_confidence_overrides_ratio(self):
        """When confidence is set, neither sigmoid nor ratio is used."""
        params = _make_params(confidence=0.85, confidence_method="ratio")
        sql = build_sum_scoring_sql(params).render()
        assert "0.85 AS match_confidence" in sql
        assert "NULLIF(" not in sql


class TestInvalidConfidenceMethod:
    """Test that invalid confidence_method values are rejected."""

    def test_invalid_confidence_method_raises(self):
        """Unknown confidence_method raises ValueError."""
        with pytest.raises(ValueError, match="confidence_method must be"):
            _make_params(confidence_method="invalid")

    def test_empty_confidence_method_raises(self):
        """Empty string confidence_method raises ValueError."""
        with pytest.raises(ValueError, match="confidence_method must be"):
            _make_params(confidence_method="")

    def test_none_like_string_raises(self):
        """String 'none' is not a valid confidence_method."""
        with pytest.raises(ValueError, match="confidence_method must be"):
            _make_params(confidence_method="none")

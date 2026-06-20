"""Tests for token-based comparison functions."""
from __future__ import annotations

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


class TestDiceCoefficient:
    """Tests for dice_coefficient comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient"]("name", "name", min_similarity=0.6)
        assert isinstance(result, str) and len(result) > 0
    def test_contains_column_references(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient"]("fname", "fname")
        assert "l.fname" in result and "r.fname" in result
    def test_contains_expected_functions(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient"]("name", "name")
        assert "SPLIT" in result and "UNNEST" in result and "COUNTIF" in result
    def test_threshold_affects_output(self):
        r1 = COMPARISON_FUNCTIONS["dice_coefficient"]("n", "n", min_similarity=0.5)
        r2 = COMPARISON_FUNCTIONS["dice_coefficient"]("n", "n", min_similarity=0.8)
        assert "0.5" in r1 and "0.8" in r2
    def test_null_checks_present(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient"]("n", "n")
        assert "IS NOT NULL" in result

class TestDiceCoefficientScore:
    """Tests for dice_coefficient_score comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient_score"]("name", "name")
        assert isinstance(result, str) and "SPLIT" in result
    def test_contains_column_references(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient_score"]("fname", "fname")
        assert "l.fname" in result and "r.fname" in result
    def test_null_handling(self):
        result = COMPARISON_FUNCTIONS["dice_coefficient_score"]("n", "n")
        assert "IS NOT NULL" in result and "ELSE 0.0" in result

class TestOverlapCoefficient:
    """Tests for overlap_coefficient comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["overlap_coefficient"]("name", "name", min_similarity=0.5)
        assert isinstance(result, str) and "LEAST" in result
    def test_contains_column_references(self):
        result = COMPARISON_FUNCTIONS["overlap_coefficient"]("addr", "addr")
        assert "l.addr" in result and "r.addr" in result
    def test_uses_least_for_denominator(self):
        result = COMPARISON_FUNCTIONS["overlap_coefficient"]("n", "n")
        assert "LEAST" in result and "COUNT(DISTINCT" in result

class TestOverlapCoefficientScore:
    """Tests for overlap_coefficient_score comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["overlap_coefficient_score"]("name", "name")
        assert isinstance(result, str) and "LEAST" in result
    def test_null_handling(self):
        result = COMPARISON_FUNCTIONS["overlap_coefficient_score"]("n", "n")
        assert "IS NOT NULL" in result and "ELSE 0.0" in result

class TestMongeElkan:
    """Tests for monge_elkan comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["monge_elkan"]("name", "name", min_similarity=0.7)
        assert isinstance(result, str) and "EDIT_DISTANCE" in result
    def test_contains_column_references(self):
        result = COMPARISON_FUNCTIONS["monge_elkan"]("fname", "fname")
        assert "l.fname" in result and "r.fname" in result
    def test_uses_cross_join_for_token_pairs(self):
        result = COMPARISON_FUNCTIONS["monge_elkan"]("n", "n")
        assert "CROSS JOIN" in result and "UNNEST" in result
    def test_threshold_affects_output(self):
        r1 = COMPARISON_FUNCTIONS["monge_elkan"]("n", "n", min_similarity=0.7)
        r2 = COMPARISON_FUNCTIONS["monge_elkan"]("n", "n", min_similarity=0.9)
        assert "0.7" in r1 and "0.9" in r2

class TestMongeElkanScore:
    """Tests for monge_elkan_score comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["monge_elkan_score"]("name", "name")
        assert isinstance(result, str) and "EDIT_DISTANCE" in result
    def test_null_handling(self):
        result = COMPARISON_FUNCTIONS["monge_elkan_score"]("n", "n")
        assert "IS NOT NULL" in result and "ELSE 0.0" in result

class TestTokenSortRatio:
    """Tests for token_sort_ratio comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["token_sort_ratio"]("name", "name", min_similarity=0.8)
        assert isinstance(result, str) and "EDIT_DISTANCE" in result
    def test_contains_column_references(self):
        result = COMPARISON_FUNCTIONS["token_sort_ratio"]("full_name", "full_name")
        assert "l.full_name" in result and "r.full_name" in result
    def test_sorts_tokens(self):
        result = COMPARISON_FUNCTIONS["token_sort_ratio"]("n", "n")
        assert "ORDER BY" in result and "ARRAY_TO_STRING" in result
    def test_null_checks_present(self):
        result = COMPARISON_FUNCTIONS["token_sort_ratio"]("n", "n")
        assert "IS NOT NULL" in result

class TestTokenSortRatioScore:
    """Tests for token_sort_ratio_score comparison."""
    def test_returns_valid_sql(self):
        result = COMPARISON_FUNCTIONS["token_sort_ratio_score"]("name", "name")
        assert isinstance(result, str) and "EDIT_DISTANCE" in result
    def test_null_handling(self):
        result = COMPARISON_FUNCTIONS["token_sort_ratio_score"]("n", "n")
        assert "IS NOT NULL" in result and "ELSE 0.0" in result

class TestAllTokenFunctionsRegistered:
    """Tests that all 8 token comparison functions are registered."""
    def test_all_registered(self):
        expected = {
            "dice_coefficient",
            "dice_coefficient_score",
            "overlap_coefficient",
            "overlap_coefficient_score",
            "monge_elkan",
            "monge_elkan_score",
            "token_sort_ratio",
            "token_sort_ratio_score",
        }
        assert expected.issubset(set(COMPARISON_FUNCTIONS.keys()))

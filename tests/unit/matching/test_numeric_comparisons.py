"""Tests for numeric comparison functions."""

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


def test_numeric_ratio_registered():
    assert "numeric_ratio" in COMPARISON_FUNCTIONS


def test_numeric_ratio():
    result = COMPARISON_FUNCTIONS["numeric_ratio"]("amount_a", "amount_b")
    assert "SAFE_DIVIDE" in result
    assert "LEAST" in result
    assert "GREATEST" in result
    assert "l.amount_a" in result
    assert "r.amount_b" in result
    assert "IS NOT NULL" in result
    assert "0.9" in result  # default min_ratio


def test_numeric_ratio_custom_threshold():
    result = COMPARISON_FUNCTIONS["numeric_ratio"]("col_a", "col_b", min_ratio=0.8)
    assert "0.8" in result


def test_numeric_ratio_zero_exclusion():
    result = COMPARISON_FUNCTIONS["numeric_ratio"]("col_a", "col_b")
    assert "!= 0" in result


def test_numeric_ratio_score_registered():
    assert "numeric_ratio_score" in COMPARISON_FUNCTIONS


def test_numeric_ratio_score():
    result = COMPARISON_FUNCTIONS["numeric_ratio_score"]("amount_a", "amount_b")
    assert "SAFE_DIVIDE" in result
    assert "LEAST" in result
    assert "GREATEST" in result
    assert "CASE WHEN" in result
    assert "ELSE 0.0" in result


def test_numeric_ratio_score_null_handling():
    result = COMPARISON_FUNCTIONS["numeric_ratio_score"]("col_a", "col_b")
    assert "IS NOT NULL" in result
    assert "!= 0" in result


def test_numeric_percent_diff_registered():
    assert "numeric_percent_diff" in COMPARISON_FUNCTIONS


def test_numeric_percent_diff():
    result = COMPARISON_FUNCTIONS["numeric_percent_diff"]("premium_a", "premium_b")
    assert "SAFE_DIVIDE" in result
    assert "ABS" in result
    assert "l.premium_a" in result
    assert "r.premium_b" in result


def test_numeric_percent_diff_default_tolerance():
    result = COMPARISON_FUNCTIONS["numeric_percent_diff"]("col_a", "col_b")
    assert "0.05" in result  # 5% -> 0.05


def test_numeric_percent_diff_custom_tolerance():
    result = COMPARISON_FUNCTIONS["numeric_percent_diff"]("col_a", "col_b", tolerance=10.0)
    assert "0.1" in result  # 10% -> 0.1


def test_numeric_within_still_works():
    """Existing numeric_within should still be registered."""
    assert "numeric_within" in COMPARISON_FUNCTIONS
    result = COMPARISON_FUNCTIONS["numeric_within"]("a", "b", tolerance=5)
    assert "ABS" in result
    assert "5" in result

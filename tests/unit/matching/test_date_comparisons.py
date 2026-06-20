"""Tests for date comparison functions."""

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


def test_date_within_months_registered():
    assert "date_within_months" in COMPARISON_FUNCTIONS


def test_date_within_months():
    result = COMPARISON_FUNCTIONS["date_within_months"]("dob_a", "dob_b", months=6)
    assert "DATE_DIFF" in result
    assert "MONTH" in result
    assert "6" in result
    assert "IS NOT NULL" in result


def test_date_within_months_default():
    result = COMPARISON_FUNCTIONS["date_within_months"]("col_a", "col_b")
    assert "0" in result  # default months=0 (exact month match)


def test_date_within_years_registered():
    assert "date_within_years" in COMPARISON_FUNCTIONS


def test_date_within_years():
    result = COMPARISON_FUNCTIONS["date_within_years"]("dob_a", "dob_b", years=1)
    assert "DATE_DIFF" in result
    assert "YEAR" in result
    assert "1" in result
    assert "IS NOT NULL" in result


def test_age_difference_registered():
    assert "age_difference" in COMPARISON_FUNCTIONS


def test_age_difference():
    result = COMPARISON_FUNCTIONS["age_difference"]("dob_a", "dob_b")
    assert "DATE_DIFF" in result
    assert "CURRENT_DATE" in result
    assert "YEAR" in result
    assert "IS NOT NULL" in result
    assert "2" in result  # default max_diff=2


def test_age_difference_custom_max():
    result = COMPARISON_FUNCTIONS["age_difference"]("dob_a", "dob_b", max_diff=5)
    assert "5" in result


def test_date_overlap_registered():
    assert "date_overlap" in COMPARISON_FUNCTIONS


def test_date_overlap():
    result = COMPARISON_FUNCTIONS["date_overlap"]("start_a", "start_b")
    assert "l.start_a" in result
    assert "r.start_b" in result
    assert "IS NOT NULL" in result


def test_date_overlap_explicit_end_columns():
    result = COMPARISON_FUNCTIONS["date_overlap"](
        "policy_start", "policy_start",
        left_end="policy_end", right_end="policy_end",
    )
    assert "policy_end" in result
    assert "policy_start" in result


def test_date_overlap_auto_end_columns():
    result = COMPARISON_FUNCTIONS["date_overlap"]("start_date", "start_date")
    assert "start_date_end" in result


def test_date_overlap_score_registered():
    assert "date_overlap_score" in COMPARISON_FUNCTIONS


def test_date_overlap_score():
    result = COMPARISON_FUNCTIONS["date_overlap_score"]("start_a", "start_b")
    assert "SAFE_DIVIDE" in result
    assert "CASE WHEN" in result
    assert "ELSE 0.0" in result


def test_date_overlap_score_with_explicit_ends():
    result = COMPARISON_FUNCTIONS["date_overlap_score"](
        "eff_date", "eff_date",
        left_end="exp_date", right_end="exp_date",
    )
    assert "exp_date" in result
    assert "eff_date" in result


def test_date_within_days_still_works():
    """Existing date_within_days should still be registered."""
    assert "date_within_days" in COMPARISON_FUNCTIONS
    result = COMPARISON_FUNCTIONS["date_within_days"]("d1", "d2", days=30)
    assert "DATE_DIFF" in result
    assert "30" in result

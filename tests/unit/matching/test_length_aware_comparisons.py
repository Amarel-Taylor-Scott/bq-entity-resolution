"""Tests for length-aware comparison functions.

Tests levenshtein_length_aware, levenshtein_length_aware_score,
length_ratio, length_ratio_score, and exact_diacritics_insensitive.
"""

from __future__ import annotations

import pytest

from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS

# ---------------------------------------------------------------------------
# Registry checks
# ---------------------------------------------------------------------------

class TestRegistration:
    """All new functions must be discoverable via the comparison registry."""

    def test_levenshtein_length_aware_registered(self):
        assert "levenshtein_length_aware" in COMPARISON_FUNCTIONS

    def test_levenshtein_length_aware_score_registered(self):
        assert "levenshtein_length_aware_score" in COMPARISON_FUNCTIONS

    def test_length_ratio_registered(self):
        assert "length_ratio" in COMPARISON_FUNCTIONS

    def test_length_ratio_score_registered(self):
        assert "length_ratio_score" in COMPARISON_FUNCTIONS

    def test_exact_diacritics_insensitive_registered(self):
        assert "exact_diacritics_insensitive" in COMPARISON_FUNCTIONS


# ---------------------------------------------------------------------------
# levenshtein_length_aware
# ---------------------------------------------------------------------------

class TestLevenshteinLengthAware:
    """Tests for levenshtein_length_aware comparison."""

    def test_generates_valid_sql(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("first_name", "first_name")
        assert "EDIT_DISTANCE" in result
        assert "l.first_name" in result
        assert "r.first_name" in result

    def test_normalizes_by_least_not_greatest(self):
        """Length-aware divides by LEAST(len), not GREATEST(len)."""
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("name", "name")
        assert "LEAST(CHAR_LENGTH" in result
        # Should NOT contain GREATEST for normalization
        assert "GREATEST(CHAR_LENGTH" not in result

    def test_default_threshold_0_8(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("col", "col")
        assert ">= 0.8" in result

    def test_custom_threshold(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("col", "col", threshold=0.9)
        assert ">= 0.9" in result

    def test_null_handling(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("name", "name")
        assert "l.name IS NOT NULL" in result
        assert "r.name IS NOT NULL" in result

    def test_empty_string_handling(self):
        """Guards against zero-length strings (division by zero)."""
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("name", "name")
        assert "CHAR_LENGTH(l.name) > 0" in result
        assert "CHAR_LENGTH(r.name) > 0" in result

    def test_different_left_right_columns(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("first_name_clean", "last_name_clean")
        assert "l.first_name_clean" in result
        assert "r.last_name_clean" in result

    def test_returns_string(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware"]
        result = fn("col", "col")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# levenshtein_length_aware_score
# ---------------------------------------------------------------------------

class TestLevenshteinLengthAwareScore:
    """Tests for levenshtein_length_aware_score comparison."""

    def test_generates_valid_sql(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware_score"]
        result = fn("name", "name")
        assert "EDIT_DISTANCE" in result
        assert "CASE WHEN" in result

    def test_normalizes_by_least(self):
        """Score variant also divides by LEAST."""
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware_score"]
        result = fn("col", "col")
        assert "LEAST(CHAR_LENGTH" in result
        assert "GREATEST(CHAR_LENGTH" not in result

    def test_null_returns_zero(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware_score"]
        result = fn("name", "name")
        assert "ELSE 0.0 END" in result

    def test_empty_string_guard(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware_score"]
        result = fn("col", "col")
        assert "CHAR_LENGTH(l.col) > 0" in result
        assert "CHAR_LENGTH(r.col) > 0" in result

    def test_null_handling(self):
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware_score"]
        result = fn("col", "col")
        assert "l.col IS NOT NULL" in result
        assert "r.col IS NOT NULL" in result

    def test_no_threshold_in_score(self):
        """Score functions return numeric value, no threshold comparison."""
        fn = COMPARISON_FUNCTIONS["levenshtein_length_aware_score"]
        result = fn("col", "col")
        assert ">=" not in result


# ---------------------------------------------------------------------------
# length_ratio
# ---------------------------------------------------------------------------

class TestLengthRatio:
    """Tests for length_ratio comparison."""

    def test_generates_valid_sql(self):
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("name", "name")
        assert "CHAR_LENGTH" in result
        assert "l.name" in result
        assert "r.name" in result

    def test_uses_least_over_greatest(self):
        """length_ratio = LEAST(len) / GREATEST(len)."""
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("col", "col")
        assert "LEAST(CHAR_LENGTH" in result
        assert "GREATEST(CHAR_LENGTH" in result

    def test_default_threshold_0_6(self):
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("col", "col")
        assert ">= 0.6" in result

    def test_custom_threshold(self):
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("col", "col", threshold=0.8)
        assert ">= 0.8" in result

    def test_null_handling(self):
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("col", "col")
        assert "l.col IS NOT NULL" in result
        assert "r.col IS NOT NULL" in result

    def test_uses_safe_divide(self):
        """SAFE_DIVIDE prevents division by zero."""
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("col", "col")
        assert "SAFE_DIVIDE" in result

    def test_casts_to_float64(self):
        fn = COMPARISON_FUNCTIONS["length_ratio"]
        result = fn("col", "col")
        assert "AS FLOAT64" in result


# ---------------------------------------------------------------------------
# length_ratio_score
# ---------------------------------------------------------------------------

class TestLengthRatioScore:
    """Tests for length_ratio_score comparison."""

    def test_generates_valid_sql(self):
        fn = COMPARISON_FUNCTIONS["length_ratio_score"]
        result = fn("name", "name")
        assert "CHAR_LENGTH" in result
        assert "CASE WHEN" in result

    def test_uses_least_over_greatest(self):
        fn = COMPARISON_FUNCTIONS["length_ratio_score"]
        result = fn("col", "col")
        assert "LEAST(CHAR_LENGTH" in result
        assert "GREATEST(CHAR_LENGTH" in result

    def test_null_returns_zero(self):
        fn = COMPARISON_FUNCTIONS["length_ratio_score"]
        result = fn("col", "col")
        assert "ELSE 0.0 END" in result

    def test_null_handling(self):
        fn = COMPARISON_FUNCTIONS["length_ratio_score"]
        result = fn("col", "col")
        assert "l.col IS NOT NULL" in result
        assert "r.col IS NOT NULL" in result

    def test_no_threshold(self):
        """Score function does not include threshold comparison."""
        fn = COMPARISON_FUNCTIONS["length_ratio_score"]
        result = fn("col", "col")
        assert ">=" not in result or "0.6" not in result

    def test_uses_safe_divide(self):
        fn = COMPARISON_FUNCTIONS["length_ratio_score"]
        result = fn("col", "col")
        assert "SAFE_DIVIDE" in result


# ---------------------------------------------------------------------------
# exact_diacritics_insensitive
# ---------------------------------------------------------------------------

class TestExactDiacriticsInsensitive:
    """Tests for exact_diacritics_insensitive comparison."""

    def test_generates_valid_sql(self):
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("name", "name")
        assert "l.name" in result
        assert "r.name" in result

    def test_uses_normalize_nfd(self):
        """Must use NORMALIZE(..., NFD) to decompose Unicode."""
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("col", "col")
        assert "NORMALIZE" in result
        assert "NFD" in result

    def test_uses_regexp_replace_for_combining_marks(self):
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("col", "col")
        assert "REGEXP_REPLACE" in result

    def test_case_insensitive(self):
        """Comparison uses UPPER for case insensitivity."""
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("col", "col")
        assert "UPPER" in result

    def test_null_handling(self):
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("name", "name")
        assert "l.name IS NOT NULL" in result
        assert "r.name IS NOT NULL" in result

    def test_both_sides_stripped(self):
        """Both left and right should have diacritics stripped."""
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("first_name", "first_name")
        # The pattern should appear twice (once per side)
        assert result.count("NORMALIZE") == 2

    def test_equality_comparison(self):
        fn = COMPARISON_FUNCTIONS["exact_diacritics_insensitive"]
        result = fn("col", "col")
        assert "=" in result


# ---------------------------------------------------------------------------
# Cross-function consistency
# ---------------------------------------------------------------------------

class TestCrossFunctionConsistency:
    """Verify consistent patterns across all new functions."""

    @pytest.mark.parametrize("name", [
        "levenshtein_length_aware",
        "levenshtein_length_aware_score",
        "length_ratio",
        "length_ratio_score",
        "exact_diacritics_insensitive",
    ])
    def test_all_return_strings(self, name):
        fn = COMPARISON_FUNCTIONS[name]
        result = fn("col", "col")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("name", [
        "levenshtein_length_aware",
        "levenshtein_length_aware_score",
        "length_ratio",
        "length_ratio_score",
        "exact_diacritics_insensitive",
    ])
    def test_all_handle_null(self, name):
        fn = COMPARISON_FUNCTIONS[name]
        result = fn("x", "x")
        assert "IS NOT NULL" in result

    @pytest.mark.parametrize("name", [
        "levenshtein_length_aware",
        "levenshtein_length_aware_score",
        "length_ratio",
        "length_ratio_score",
        "exact_diacritics_insensitive",
    ])
    def test_all_accept_kwargs(self, name):
        """All registry functions accept **kwargs for forward compatibility."""
        fn = COMPARISON_FUNCTIONS[name]
        # Should not raise
        result = fn("col", "col", unknown_param="whatever")
        assert isinstance(result, str)

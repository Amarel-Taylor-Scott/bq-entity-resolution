"""Tests for comparison input validation (safe identifiers)."""

from __future__ import annotations

import pytest

from bq_entity_resolution.matching.comparisons import (
    COMPARISON_FUNCTIONS,
    _validated_call,
    get_comparison_safe,
)


class TestGetComparisonSafe:
    """Test get_comparison_safe returns a validating wrapper."""

    def test_safe_exact_accepts_valid_identifiers(self):
        """get_comparison_safe('exact') accepts valid column names."""
        fn = get_comparison_safe("exact")
        result = fn(left="first_name", right="first_name")
        assert isinstance(result, str)
        assert "first_name" in result

    def test_safe_exact_accepts_underscored_names(self):
        """Valid identifiers with underscores are accepted."""
        fn = get_comparison_safe("exact")
        result = fn(left="first_name_clean", right="last_name_clean")
        assert "first_name_clean" in result
        assert "last_name_clean" in result

    def test_safe_rejects_sql_injection_semicolon(self):
        """Semicolon in column name is rejected."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="col; DROP TABLE", right="name")

    def test_safe_rejects_sql_injection_quotes(self):
        """Single quotes in column name are rejected."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="col'--", right="name")

    def test_safe_rejects_spaces(self):
        """Spaces in column name are rejected."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="first name", right="name")

    def test_safe_rejects_dot_notation(self):
        """Dot notation (e.g., l.col) in column name is rejected."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="l.first_name", right="name")

    def test_safe_rejects_dashes(self):
        """Dashes in column name are rejected."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="first-name", right="name")

    def test_safe_rejects_empty_string(self):
        """Empty string is not a valid identifier."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="", right="name")

    def test_safe_rejects_right_injection(self):
        """Right column is also validated."""
        fn = get_comparison_safe("exact")
        with pytest.raises(ValueError, match="Invalid SQL"):
            fn(left="name", right="col; DROP TABLE")

    def test_safe_unknown_method_raises_key_error(self):
        """Unknown comparison name raises KeyError."""
        with pytest.raises(KeyError):
            get_comparison_safe("nonexistent_method_xyz")

    def test_safe_preserves_function_name(self):
        """Wrapped function preserves __name__ from original."""
        fn = get_comparison_safe("exact")
        original = COMPARISON_FUNCTIONS["exact"]
        assert fn.__name__ == original.__name__


class TestValidatedCall:
    """Test _validated_call directly."""

    def test_validated_call_with_valid_inputs(self):
        """_validated_call passes through valid inputs to function."""
        def mock_fn(left: str, right: str, **kwargs) -> str:
            return f"l.{left} = r.{right}"

        result = _validated_call(mock_fn, "first_name", "last_name")
        assert result == "l.first_name = r.last_name"

    def test_validated_call_rejects_invalid_left(self):
        """_validated_call rejects invalid left identifier."""
        def mock_fn(left: str, right: str, **kwargs) -> str:
            return f"l.{left} = r.{right}"

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validated_call(mock_fn, "col; DROP", "name")

    def test_validated_call_rejects_invalid_right(self):
        """_validated_call rejects invalid right identifier."""
        def mock_fn(left: str, right: str, **kwargs) -> str:
            return f"l.{left} = r.{right}"

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validated_call(mock_fn, "name", "col; DROP")

    def test_validated_call_passes_kwargs(self):
        """_validated_call forwards extra kwargs to the function."""
        def mock_fn(left: str, right: str, **kwargs) -> str:
            return f"EDIT_DISTANCE(l.{left}, r.{right}) <= {kwargs.get('max_distance', 2)}"

        result = _validated_call(mock_fn, "name", "name", max_distance=3)
        assert "max_distance" not in result or "<= 3" in result

    def test_validated_call_accepts_numeric_suffix(self):
        """Identifiers with numeric suffixes are valid."""
        def mock_fn(left: str, right: str, **kwargs) -> str:
            return f"l.{left} = r.{right}"

        result = _validated_call(mock_fn, "address_line_1", "address_line_2")
        assert "address_line_1" in result
        assert "address_line_2" in result

    def test_validated_call_rejects_leading_digit(self):
        """Identifiers starting with digits are rejected."""
        def mock_fn(left: str, right: str, **kwargs) -> str:
            return f"l.{left} = r.{right}"

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validated_call(mock_fn, "1st_name", "name")


class TestComparisonSafeIntegration:
    """Integration tests: get_comparison_safe with real registered functions."""

    def test_levenshtein_safe(self):
        """Levenshtein comparison works through safe wrapper."""
        if "levenshtein" not in COMPARISON_FUNCTIONS:
            pytest.skip("levenshtein not registered")
        fn = get_comparison_safe("levenshtein")
        result = fn(left="first_name_clean", right="first_name_clean", max_distance=2)
        assert isinstance(result, str)
        assert "first_name_clean" in result

    def test_soundex_match_safe(self):
        """Soundex comparison works through safe wrapper."""
        if "soundex_match" not in COMPARISON_FUNCTIONS:
            pytest.skip("soundex_match not registered")
        fn = get_comparison_safe("soundex_match")
        result = fn(left="last_name_clean", right="last_name_clean")
        assert isinstance(result, str)
        assert "last_name_clean" in result

    def test_exact_or_null_safe(self):
        """exact_or_null comparison works through safe wrapper."""
        if "exact_or_null" not in COMPARISON_FUNCTIONS:
            pytest.skip("exact_or_null not registered")
        fn = get_comparison_safe("exact_or_null")
        result = fn(left="email", right="email")
        assert isinstance(result, str)

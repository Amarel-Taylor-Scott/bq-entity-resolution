"""Tests for compound detection feature functions."""

from __future__ import annotations

import pytest

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestCompoundFeaturesRegistered:
    """Verify all 4 compound feature functions are registered."""

    def test_is_compound_name_registered(self):
        assert "is_compound_name" in FEATURE_FUNCTIONS

    def test_compound_pattern_registered(self):
        assert "compound_pattern" in FEATURE_FUNCTIONS

    def test_extract_compound_first_registered(self):
        assert "extract_compound_first" in FEATURE_FUNCTIONS

    def test_extract_compound_second_registered(self):
        assert "extract_compound_second" in FEATURE_FUNCTIONS


class TestIsCompoundName:
    def test_returns_case_expression(self):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["first_name"])
        assert "CASE WHEN" in expr
        assert "THEN 1 ELSE 0 END" in expr

    def test_checks_conjunctions(self):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["name"])
        assert "AND" in expr
        assert "&" in expr

    def test_checks_title_pairs(self):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["name"])
        assert "MR" in expr
        assert "MRS" in expr

    def test_checks_family_pattern(self):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["name"])
        assert "FAMILY" in expr

    def test_checks_slash_pattern(self):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["name"])
        assert "/" in expr

    def test_uses_input_column(self):
        expr = FEATURE_FUNCTIONS["is_compound_name"](["full_name"])
        assert "full_name" in expr


class TestCompoundPattern:
    def test_returns_case_expression(self):
        expr = FEATURE_FUNCTIONS["compound_pattern"](["name"])
        assert "CASE" in expr

    def test_returns_all_pattern_types(self):
        expr = FEATURE_FUNCTIONS["compound_pattern"](["name"])
        assert "'title_pair'" in expr
        assert "'family'" in expr
        assert "'slash'" in expr
        assert "'conjunction'" in expr
        assert "NULL" in expr

    def test_uses_input_column(self):
        expr = FEATURE_FUNCTIONS["compound_pattern"](["my_col"])
        assert "my_col" in expr


class TestExtractCompoundFirst:
    def test_returns_case_expression(self):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["name"])
        assert "CASE" in expr
        assert "REGEXP_EXTRACT" in expr

    def test_handles_conjunction_pattern(self):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["name"])
        # Should extract first word before AND/&/+
        assert "AND" in expr

    def test_handles_slash_pattern(self):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["name"])
        assert "/" in expr

    def test_uses_input_column(self):
        expr = FEATURE_FUNCTIONS["extract_compound_first"](["fname"])
        assert "fname" in expr


class TestExtractCompoundSecond:
    def test_returns_case_expression(self):
        expr = FEATURE_FUNCTIONS["extract_compound_second"](["name"])
        assert "CASE" in expr
        assert "REGEXP_EXTRACT" in expr

    def test_handles_conjunction_pattern(self):
        expr = FEATURE_FUNCTIONS["extract_compound_second"](["name"])
        assert "AND" in expr

    def test_handles_slash_pattern(self):
        expr = FEATURE_FUNCTIONS["extract_compound_second"](["name"])
        assert "/" in expr

    def test_uses_input_column(self):
        expr = FEATURE_FUNCTIONS["extract_compound_second"](["fname"])
        assert "fname" in expr


class TestCompoundFeaturesAcceptKwargs:
    """All feature functions must accept **kwargs for forward compat."""

    @pytest.mark.parametrize("fn_name", [
        "is_compound_name",
        "compound_pattern",
        "extract_compound_first",
        "extract_compound_second",
    ])
    def test_accepts_extra_kwargs(self, fn_name):
        func = FEATURE_FUNCTIONS[fn_name]
        # Should not raise
        result = func(["col"], extra_param="value")
        assert isinstance(result, str)

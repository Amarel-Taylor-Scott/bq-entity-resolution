"""Tests for zip/postal code feature functions."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestZip5:
    def test_extracts_5_digits(self):
        result = FEATURE_FUNCTIONS["zip5"](["zipcode"])
        assert "LEFT" in result and "5" in result

    def test_strips_non_digits(self):
        result = FEATURE_FUNCTIONS["zip5"](["zipcode"])
        assert "REGEXP_REPLACE" in result and "[^0-9]" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["zip5"](["postal_code"])
        assert "postal_code" in result


class TestZip3:
    def test_extracts_3_digits(self):
        result = FEATURE_FUNCTIONS["zip3"](["zipcode"])
        assert "LEFT" in result and "3" in result

    def test_strips_non_digits(self):
        result = FEATURE_FUNCTIONS["zip3"](["zipcode"])
        assert "REGEXP_REPLACE" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["zip3"](["zip"])
        assert "zip" in result

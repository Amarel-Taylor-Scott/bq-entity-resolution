"""Tests for address feature functions."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestAddressStandardize:
    def test_returns_sql_string(self):
        result = FEATURE_FUNCTIONS["address_standardize"](["address"])
        assert isinstance(result, str)

    def test_uppercases(self):
        result = FEATURE_FUNCTIONS["address_standardize"](["address"])
        assert "UPPER" in result

    def test_abbreviates_street_types(self):
        result = FEATURE_FUNCTIONS["address_standardize"](["address"])
        assert "REGEXP_REPLACE" in result
        # Should contain at least some common abbreviations
        assert "ST" in result and "AVE" in result and "BLVD" in result

    def test_trims_whitespace(self):
        result = FEATURE_FUNCTIONS["address_standardize"](["address"])
        assert "TRIM" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["address_standardize"](["street_addr"])
        assert "street_addr" in result


class TestExtractStreetNumber:
    def test_extracts_leading_digits(self):
        result = FEATURE_FUNCTIONS["extract_street_number"](["address"])
        assert "REGEXP_EXTRACT" in result and "\\d" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["extract_street_number"](["addr_line"])
        assert "addr_line" in result


class TestExtractStreetName:
    def test_returns_trimmed_upper(self):
        result = FEATURE_FUNCTIONS["extract_street_name"](["address"])
        assert "TRIM" in result and "UPPER" in result

    def test_uses_regexp_extract(self):
        result = FEATURE_FUNCTIONS["extract_street_name"](["address"])
        assert "REGEXP_EXTRACT" in result


class TestExtractUnitNumber:
    def test_extracts_unit_patterns(self):
        result = FEATURE_FUNCTIONS["extract_unit_number"](["address"])
        assert "REGEXP_EXTRACT" in result
        assert "APT" in result or "SUITE" in result or "UNIT" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["extract_unit_number"](["full_address"])
        assert "full_address" in result

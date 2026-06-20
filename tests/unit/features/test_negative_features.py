"""Tests for hard-negative flag features."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestExtractGenerationalSuffix:
    """Tests for extract_generational_suffix feature."""
    def test_finds_jr_sr(self):
        result = FEATURE_FUNCTIONS["extract_generational_suffix"](["name"])
        assert isinstance(result, str) and "JR" in result and "SR" in result
    def test_finds_roman_style(self):
        result = FEATURE_FUNCTIONS["extract_generational_suffix"](["name"])
        assert "II" in result and "III" in result
    def test_returns_null_when_none(self):
        result = FEATURE_FUNCTIONS["extract_generational_suffix"](["name"])
        assert "REGEXP_EXTRACT" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["extract_generational_suffix"](["full_name"])
        assert "full_name" in result

class TestExtractRomanNumeral:
    """Tests for extract_roman_numeral feature."""
    def test_finds_roman_numerals(self):
        result = FEATURE_FUNCTIONS["extract_roman_numeral"](["name"])
        assert isinstance(result, str)
        assert "XII" in result or "VIII" in result
    def test_uses_regex_extract(self):
        result = FEATURE_FUNCTIONS["extract_roman_numeral"](["name"])
        assert "REGEXP_EXTRACT" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["extract_roman_numeral"](["entity_name"])
        assert "entity_name" in result

class TestIsHoaTrustCareof:
    """Tests for is_hoa_trust_careof feature."""
    def test_flags_hoa_patterns(self):
        result = FEATURE_FUNCTIONS["is_hoa_trust_careof"](["name"])
        assert isinstance(result, str) and "HOA" in result
    def test_flags_trust_patterns(self):
        result = FEATURE_FUNCTIONS["is_hoa_trust_careof"](["name"])
        assert "TRUST" in result and "ESTATE" in result
    def test_flags_care_of_patterns(self):
        result = FEATURE_FUNCTIONS["is_hoa_trust_careof"](["name"])
        assert "C/O" in result and "ATTN" in result
    def test_returns_0_or_1(self):
        result = FEATURE_FUNCTIONS["is_hoa_trust_careof"](["name"])
        assert "THEN 1" in result and "ELSE 0" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["is_hoa_trust_careof"](["insured_name"])
        assert "insured_name" in result

class TestExtractNumberedEntitySuffix:
    """Tests for extract_numbered_entity_suffix feature."""
    def test_finds_numbered_patterns(self):
        result = FEATURE_FUNCTIONS["extract_numbered_entity_suffix"](["name"])
        assert isinstance(result, str) and "REGEXP_EXTRACT" in result
    def test_matches_hash_number(self):
        result = FEATURE_FUNCTIONS["extract_numbered_entity_suffix"](["name"])
        assert "#" in result
    def test_matches_unit_suite(self):
        result = FEATURE_FUNCTIONS["extract_numbered_entity_suffix"](["name"])
        assert "UNIT" in result or "SUITE" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["extract_numbered_entity_suffix"](["addr"])
        assert "addr" in result

class TestGeographicQualifier:
    """Tests for geographic_qualifier feature."""
    def test_finds_cardinal_directions(self):
        result = FEATURE_FUNCTIONS["geographic_qualifier"](["name"])
        assert isinstance(result, str)
        assert "NORTH" in result and "SOUTH" in result and "EAST" in result and "WEST" in result
    def test_finds_compound_directions(self):
        result = FEATURE_FUNCTIONS["geographic_qualifier"](["name"])
        assert "NORTHEAST" in result or "NORTHWEST" in result
    def test_uses_regex_extract(self):
        result = FEATURE_FUNCTIONS["geographic_qualifier"](["name"])
        assert "REGEXP_EXTRACT" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["geographic_qualifier"](["branch_name"])
        assert "branch_name" in result

"""Tests for business/DBA features."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestDbaExtract:
    """Tests for dba_extract feature."""
    def test_extracts_dba_name(self):
        result = FEATURE_FUNCTIONS["dba_extract"](["biz_name"])
        assert isinstance(result, str) and "DBA" in result
    def test_matches_dba_variants(self):
        result = FEATURE_FUNCTIONS["dba_extract"](["name"])
        assert "D/B/A" in result and "AKA" in result
    def test_returns_null_when_no_dba(self):
        result = FEATURE_FUNCTIONS["dba_extract"](["name"])
        assert "ELSE NULL" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["dba_extract"](["company_name"])
        assert "company_name" in result

class TestDbaNormalize:
    """Tests for dba_normalize feature."""
    def test_strips_suffixes(self):
        result = FEATURE_FUNCTIONS["dba_normalize"](["name"])
        assert isinstance(result, str)
        assert "LLC" in result and "INC" in result and "CORP" in result
    def test_uppercases(self):
        result = FEATURE_FUNCTIONS["dba_normalize"](["name"])
        assert "UPPER" in result
    def test_strips_special_chars(self):
        result = FEATURE_FUNCTIONS["dba_normalize"](["name"])
        assert "REGEXP_REPLACE" in result

class TestBusinessTypeExtract:
    """Tests for business_type_extract feature."""
    def test_extracts_business_types(self):
        result = FEATURE_FUNCTIONS["business_type_extract"](["name"])
        assert isinstance(result, str)
        assert "LLC" in result and "INC" in result and "CORP" in result and "LTD" in result
    def test_returns_null_when_no_suffix(self):
        result = FEATURE_FUNCTIONS["business_type_extract"](["name"])
        assert "REGEXP_EXTRACT" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["business_type_extract"](["entity_name"])
        assert "entity_name" in result

class TestBusinessCoreName:
    """Tests for business_core_name feature."""
    def test_strips_dba_and_type(self):
        result = FEATURE_FUNCTIONS["business_core_name"](["name"])
        assert isinstance(result, str)
        assert "DBA" in result and "LLC" in result
    def test_uppercases_result(self):
        result = FEATURE_FUNCTIONS["business_core_name"](["name"])
        assert "UPPER" in result
    def test_strips_special_chars(self):
        result = FEATURE_FUNCTIONS["business_core_name"](["name"])
        assert "REGEXP_REPLACE" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["business_core_name"](["biz_name"])
        assert "biz_name" in result

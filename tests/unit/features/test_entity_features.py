"""Tests for entity classification features."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestEntityTypeClassify:
    """Tests for entity_type_classify feature."""
    def test_returns_sql_with_expected_cases(self):
        result = FEATURE_FUNCTIONS["entity_type_classify"](["name_col"])
        assert isinstance(result, str) and "CASE" in result
        assert "BUSINESS" in result and "ORGANIZATION" in result and "PERSON" in result
    def test_detects_business_keywords(self):
        result = FEATURE_FUNCTIONS["entity_type_classify"](["name_col"])
        assert "LLC" in result and "INC" in result and "CORP" in result
    def test_detects_organization_keywords(self):
        result = FEATURE_FUNCTIONS["entity_type_classify"](["name_col"])
        assert "TRUST" in result and "FOUNDATION" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["entity_type_classify"](["business_name"])
        assert "business_name" in result
    def test_handles_null_input(self):
        result = FEATURE_FUNCTIONS["entity_type_classify"](["name_col"])
        assert "IS NULL" in result and "THEN NULL" in result

class TestNameFormatDetect:
    """Tests for name_format_detect feature."""
    def test_returns_sql_with_format_cases(self):
        result = FEATURE_FUNCTIONS["name_format_detect"](["name"])
        assert isinstance(result, str) and "CASE" in result
        assert "NATURAL" in result and "REVERSED" in result
        assert "SINGLE" in result and "COMPOUND" in result
    def test_detects_reversed_format(self):
        result = FEATURE_FUNCTIONS["name_format_detect"](["name"])
        assert "," in result
    def test_detects_compound_format(self):
        result = FEATURE_FUNCTIONS["name_format_detect"](["name"])
        assert "AND" in result or "&" in result
    def test_handles_null(self):
        result = FEATURE_FUNCTIONS["name_format_detect"](["name"])
        assert "IS NULL" in result and "NULL" in result

class TestIsMultiPerson:
    """Tests for is_multi_person feature."""
    def test_returns_sql_with_0_1_output(self):
        result = FEATURE_FUNCTIONS["is_multi_person"](["name"])
        assert isinstance(result, str) and "CASE" in result
        assert "1" in result and "0" in result
    def test_detects_and_pattern(self):
        result = FEATURE_FUNCTIONS["is_multi_person"](["name"])
        assert "AND" in result
    def test_detects_slash_pattern(self):
        result = FEATURE_FUNCTIONS["is_multi_person"](["name"])
        assert "/" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["is_multi_person"](["full_name"])
        assert "full_name" in result

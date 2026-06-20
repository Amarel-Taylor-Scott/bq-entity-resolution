"""Tests for phonetic feature functions."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestMetaphone:
    def test_returns_sql_string(self):
        result = FEATURE_FUNCTIONS["metaphone"](["name"])
        assert isinstance(result, str)

    def test_calls_udf(self):
        result = FEATURE_FUNCTIONS["metaphone"](["name"])
        assert "metaphone" in result

    def test_handles_null(self):
        result = FEATURE_FUNCTIONS["metaphone"](["name"])
        assert "IS NOT NULL" in result and "NULL" in result

    def test_custom_udf_dataset(self):
        result = FEATURE_FUNCTIONS["metaphone"](["name"], udf_dataset="my_project.udfs")
        assert "my_project.udfs" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["metaphone"](["last_name"])
        assert "last_name" in result

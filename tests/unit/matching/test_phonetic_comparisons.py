"""Tests for phonetic comparison functions (Metaphone UDF-based)."""

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS
from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


def test_metaphone_match_registered():
    assert "metaphone_match" in COMPARISON_FUNCTIONS


def test_metaphone_match_generates_udf_call():
    result = COMPARISON_FUNCTIONS["metaphone_match"](
        "first_name", "first_name", udf_dataset="proj.er_udfs"
    )
    assert "metaphone" in result
    assert "proj.er_udfs" in result


def test_metaphone_match_null_checks():
    result = COMPARISON_FUNCTIONS["metaphone_match"]("name", "name")
    assert "l.name IS NOT NULL" in result
    assert "r.name IS NOT NULL" in result


def test_double_metaphone_match_registered():
    assert "double_metaphone_match" in COMPARISON_FUNCTIONS


def test_double_metaphone_match_checks_both_codes():
    result = COMPARISON_FUNCTIONS["double_metaphone_match"](
        "name", "name", udf_dataset="proj.udfs"
    )
    assert "double_metaphone_primary" in result
    assert "double_metaphone_alternate" in result
    assert "OR" in result


def test_metaphone_feature_registered():
    assert "metaphone" in FEATURE_FUNCTIONS
    result = FEATURE_FUNCTIONS["metaphone"](["first_name"], udf_dataset="proj.udfs")
    assert "metaphone" in result
    assert "proj.udfs" in result

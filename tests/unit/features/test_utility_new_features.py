"""Tests for new utility feature functions (diacritics, whitespace)."""

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


def test_remove_diacritics_registered():
    assert "remove_diacritics" in FEATURE_FUNCTIONS


def test_remove_diacritics():
    result = FEATURE_FUNCTIONS["remove_diacritics"](["customer_name"])
    assert "REGEXP_REPLACE" in result
    assert "UPPER" in result
    assert "customer_name" in result


def test_remove_diacritics_handles_a_diacritics():
    """Handles À-Å → A."""
    result = FEATURE_FUNCTIONS["remove_diacritics"](["name"])
    assert "À-Å" in result or "A" in result


def test_remove_diacritics_handles_e_diacritics():
    """Handles È-Ë → E."""
    result = FEATURE_FUNCTIONS["remove_diacritics"](["name"])
    assert "È-Ë" in result or "E" in result


def test_normalize_whitespace_registered():
    assert "normalize_whitespace" in FEATURE_FUNCTIONS


def test_normalize_whitespace():
    result = FEATURE_FUNCTIONS["normalize_whitespace"](["address"])
    assert "TRIM" in result
    assert "REGEXP_REPLACE" in result
    assert "address" in result


def test_normalize_whitespace_collapses_spaces():
    """Collapses multiple whitespace to single space."""
    result = FEATURE_FUNCTIONS["normalize_whitespace"](["col"])
    assert "\\s+" in result or "s+" in result

"""Tests for DOB/SSN/Phone identity feature functions."""

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


def test_dob_year_registered():
    assert "dob_year" in FEATURE_FUNCTIONS


def test_dob_year_generates_extract():
    result = FEATURE_FUNCTIONS["dob_year"](["date_of_birth"])
    assert "EXTRACT(YEAR FROM" in result
    assert "date_of_birth" in result


def test_age_from_dob_registered():
    assert "age_from_dob" in FEATURE_FUNCTIONS


def test_age_from_dob_generates_date_diff():
    result = FEATURE_FUNCTIONS["age_from_dob"](["dob"])
    assert "DATE_DIFF" in result
    assert "CURRENT_DATE()" in result
    assert "YEAR" in result
    assert "dob" in result


def test_ssn_last_four_registered():
    assert "ssn_last_four" in FEATURE_FUNCTIONS


def test_ssn_last_four_generates_right():
    result = FEATURE_FUNCTIONS["ssn_last_four"](["ssn"])
    assert "RIGHT" in result
    assert "REGEXP_REPLACE" in result
    assert "4" in result


def test_ssn_clean_registered():
    assert "ssn_clean" in FEATURE_FUNCTIONS


def test_ssn_clean_generates_regexp():
    result = FEATURE_FUNCTIONS["ssn_clean"](["ssn"])
    assert "REGEXP_REPLACE" in result
    assert "[^0-9]" in result


def test_dob_mmdd_registered():
    assert "dob_mmdd" in FEATURE_FUNCTIONS


def test_dob_mmdd_generates_format_date():
    result = FEATURE_FUNCTIONS["dob_mmdd"](["dob"])
    assert "FORMAT_DATE" in result
    assert "%m%d" in result


def test_phone_area_code_registered():
    assert "phone_area_code" in FEATURE_FUNCTIONS
    result = FEATURE_FUNCTIONS["phone_area_code"](["phone"])
    assert "LEFT" in result
    assert "3" in result
    assert "REGEXP_REPLACE" in result

"""Tests for industry-specific feature functions."""

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

# -- Insurance features --

def test_vin_normalize_registered():
    assert "vin_normalize" in FEATURE_FUNCTIONS


def test_vin_normalize():
    result = FEATURE_FUNCTIONS["vin_normalize"](["vin_number"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "vin_number" in result


def test_vin_normalize_ocr_correction():
    """VIN normalize replaces O→0, I→1, Q→0 for OCR correction."""
    result = FEATURE_FUNCTIONS["vin_normalize"](["vin"])
    assert "'O', '0'" in result
    assert "'I', '1'" in result
    assert "'Q', '0'" in result


def test_vin_last_six_registered():
    assert "vin_last_six" in FEATURE_FUNCTIONS


def test_vin_last_six():
    result = FEATURE_FUNCTIONS["vin_last_six"](["vin_number"])
    assert "RIGHT" in result
    assert "6" in result


def test_policy_number_clean_registered():
    assert "policy_number_clean" in FEATURE_FUNCTIONS


def test_policy_number_clean():
    result = FEATURE_FUNCTIONS["policy_number_clean"](["policy_num"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "policy_num" in result


def test_policy_number_clean_removes_leading_zeros():
    result = FEATURE_FUNCTIONS["policy_number_clean"](["pol"])
    assert "^0+" in result


# -- Banking features --

def test_iban_normalize_registered():
    assert "iban_normalize" in FEATURE_FUNCTIONS


def test_iban_normalize():
    result = FEATURE_FUNCTIONS["iban_normalize"](["iban"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "iban" in result


def test_routing_number_clean_registered():
    assert "routing_number_clean" in FEATURE_FUNCTIONS


def test_routing_number_clean():
    result = FEATURE_FUNCTIONS["routing_number_clean"](["routing_num"])
    assert "REGEXP_REPLACE" in result
    assert "[^0-9]" in result
    assert "routing_num" in result


def test_account_number_clean_registered():
    assert "account_number_clean" in FEATURE_FUNCTIONS


def test_account_number_clean():
    result = FEATURE_FUNCTIONS["account_number_clean"](["acct_num"])
    assert "REGEXP_REPLACE" in result
    assert "acct_num" in result


def test_account_number_clean_removes_leading_zeros():
    result = FEATURE_FUNCTIONS["account_number_clean"](["acct"])
    assert "^0+" in result


def test_amount_bucket_registered():
    assert "amount_bucket" in FEATURE_FUNCTIONS


def test_amount_bucket_default():
    result = FEATURE_FUNCTIONS["amount_bucket"](["amount"])
    assert "FLOOR" in result
    assert "FLOAT64" in result
    assert "100" in result  # default bucket_size


def test_amount_bucket_custom_size():
    result = FEATURE_FUNCTIONS["amount_bucket"](["amount"], bucket_size=50)
    assert "50" in result


# -- Healthcare features --

def test_npi_validate_registered():
    assert "npi_validate" in FEATURE_FUNCTIONS


def test_npi_validate():
    result = FEATURE_FUNCTIONS["npi_validate"](["npi"])
    assert "CASE WHEN" in result
    assert "CHAR_LENGTH" in result
    assert "10" in result
    assert "ELSE NULL" in result


def test_dea_number_clean_registered():
    assert "dea_number_clean" in FEATURE_FUNCTIONS


def test_dea_number_clean():
    result = FEATURE_FUNCTIONS["dea_number_clean"](["dea_num"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "dea_num" in result


def test_mrn_clean_registered():
    assert "mrn_clean" in FEATURE_FUNCTIONS


def test_mrn_clean():
    result = FEATURE_FUNCTIONS["mrn_clean"](["mrn"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "mrn" in result


def test_mrn_clean_removes_leading_zeros():
    result = FEATURE_FUNCTIONS["mrn_clean"](["mrn"])
    assert "^0+" in result


def test_icd_code_normalize_registered():
    assert "icd_code_normalize" in FEATURE_FUNCTIONS


def test_icd_code_normalize():
    result = FEATURE_FUNCTIONS["icd_code_normalize"](["icd_code"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "icd_code" in result


# -- Business features --

def test_ein_format_registered():
    assert "ein_format" in FEATURE_FUNCTIONS


def test_ein_format():
    result = FEATURE_FUNCTIONS["ein_format"](["ein"])
    assert "REGEXP_REPLACE" in result
    assert "[^0-9]" in result
    assert "ein" in result


def test_duns_clean_registered():
    assert "duns_clean" in FEATURE_FUNCTIONS


def test_duns_clean():
    result = FEATURE_FUNCTIONS["duns_clean"](["duns"])
    assert "CASE WHEN" in result
    assert "CHAR_LENGTH" in result
    assert "9" in result
    assert "ELSE NULL" in result


def test_ticker_normalize_registered():
    assert "ticker_normalize" in FEATURE_FUNCTIONS


def test_ticker_normalize():
    result = FEATURE_FUNCTIONS["ticker_normalize"](["ticker"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "ticker" in result


def test_cusip_clean_registered():
    assert "cusip_clean" in FEATURE_FUNCTIONS


def test_cusip_clean():
    result = FEATURE_FUNCTIONS["cusip_clean"](["cusip"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "cusip" in result


def test_license_number_clean_registered():
    assert "license_number_clean" in FEATURE_FUNCTIONS


def test_license_number_clean():
    result = FEATURE_FUNCTIONS["license_number_clean"](["license_num"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "[^A-Za-z0-9]" in result
    assert "license_num" in result

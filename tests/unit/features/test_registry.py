"""Tests for feature function registry."""


from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


def test_name_clean():
    result = FEATURE_FUNCTIONS["name_clean"](["raw_name"])
    assert "UPPER" in result
    assert "REGEXP_REPLACE" in result
    assert "raw_name" in result


def test_soundex():
    result = FEATURE_FUNCTIONS["soundex"](["col"])
    assert result == "SOUNDEX(col)"


def test_first_letter():
    result = FEATURE_FUNCTIONS["first_letter"](["col"])
    assert result == "LEFT(col, 1)"


def test_char_length():
    result = FEATURE_FUNCTIONS["char_length"](["col"])
    assert result == "CHAR_LENGTH(col)"


def test_extract_salutation():
    result = FEATURE_FUNCTIONS["extract_salutation"](["name"])
    assert "MR" in result
    assert "DR" in result
    assert "CASE" in result


def test_phone_standardize():
    result = FEATURE_FUNCTIONS["phone_standardize"](["phone"])
    assert "REGEXP_REPLACE" in result
    assert "10" in result


def test_email_domain():
    result = FEATURE_FUNCTIONS["email_domain"](["email"])
    assert "@" in result
    assert "LOWER" in result


def test_farm_fingerprint():
    result = FEATURE_FUNCTIONS["farm_fingerprint"](["col"])
    assert "FARM_FINGERPRINT" in result


def test_farm_fingerprint_concat():
    result = FEATURE_FUNCTIONS["farm_fingerprint_concat"](["a", "b", "c"])
    assert "FARM_FINGERPRINT" in result
    assert "CONCAT" in result
    assert "||" in result


def test_left():
    result = FEATURE_FUNCTIONS["left"](["col"], length=3)
    assert result == "LEFT(col, 3)"


def test_address_standardize():
    result = FEATURE_FUNCTIONS["address_standardize"](["addr"])
    assert "STREET" in result
    assert "ST" in result
    assert "UPPER" in result


def test_strip_business_suffix():
    result = FEATURE_FUNCTIONS["strip_business_suffix"](["name"])
    assert "LLC" in result
    assert "INC" in result
    assert "CORP" in result


def test_nickname_canonical():
    result = FEATURE_FUNCTIONS["nickname_canonical"](["first_name"])
    assert "ROBERT" in result
    assert "WILLIAM" in result
    assert "CASE" in result


def test_sorted_name_tokens():
    result = FEATURE_FUNCTIONS["sorted_name_tokens"](["full_name"])
    assert "STRING_AGG" in result
    assert "ORDER BY word" in result


def test_zip5():
    result = FEATURE_FUNCTIONS["zip5"](["zip"])
    assert "LEFT" in result
    assert "5" in result


def test_phone_last_four():
    result = FEATURE_FUNCTIONS["phone_last_four"](["phone"])
    assert "RIGHT" in result
    assert "4" in result


def test_all_functions_registered():
    """Ensure we have a good set of built-in functions."""
    expected = {
        "name_clean", "soundex", "first_letter", "char_length",
        "extract_salutation", "phone_standardize", "email_domain",
        "farm_fingerprint", "farm_fingerprint_concat", "left",
        "right", "upper_trim", "address_standardize", "identity",
        "concat", "coalesce", "nullif_empty",
        # New ER best practice functions
        "nickname_canonical", "nickname_match_key",
        "sorted_name_tokens", "sorted_name_fingerprint",
        "zip5", "zip3", "phone_last_four",
        "year_of_date", "date_to_string",
        "strip_business_suffix",
        # Geo-spatial features
        "geo_hash", "lat_lon_bucket", "haversine_distance",
        # DOB / SSN / Phone identity features
        "dob_year", "age_from_dob", "ssn_last_four", "ssn_clean",
        "dob_mmdd", "phone_area_code",
        # Phonetic features
        "metaphone",
    }
    assert expected.issubset(set(FEATURE_FUNCTIONS.keys()))

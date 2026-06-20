"""Tests for placeholder/sentinel value detection and nullification features."""

from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestIsPlaceholderPhone:
    """Tests for is_placeholder_phone feature function."""

    def test_registered(self):
        assert "is_placeholder_phone" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        assert "CASE WHEN" in sql
        assert "THEN 1 ELSE 0 END" in sql

    def test_detects_all_nines(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        assert "9999999999" in sql

    def test_detects_all_zeros(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        assert "0000000000" in sql

    def test_detects_sequential(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        assert "1234567890" in sql

    def test_strips_non_digits(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        assert "REGEXP_REPLACE" in sql
        assert "[^0-9]" in sql

    def test_detects_repeating_digits(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        # All single-digit repeats
        for d in range(10):
            assert f"{d}{{{{7,}}}}" in sql or f"{d}{{7,}}" in sql


class TestIsPlaceholderEmail:
    """Tests for is_placeholder_email feature function."""

    def test_registered(self):
        assert "is_placeholder_email" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_email"](["email"])
        assert "CASE WHEN" in sql
        assert "THEN 1 ELSE 0 END" in sql

    def test_detects_noemail_prefix(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_email"](["email"])
        assert "noemail" in sql.lower()

    def test_detects_test_prefix(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_email"](["email"])
        assert "test" in sql.lower()

    def test_detects_example_domain(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_email"](["email"])
        assert "example" in sql.lower()

    def test_case_insensitive_check(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_email"](["email"])
        assert "LOWER" in sql


class TestIsPlaceholderName:
    """Tests for is_placeholder_name feature function."""

    def test_registered(self):
        assert "is_placeholder_name" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "CASE WHEN" in sql
        assert "THEN 1 ELSE 0 END" in sql

    def test_detects_unknown(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "'UNKNOWN'" in sql

    def test_detects_na(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "'N/A'" in sql

    def test_detects_tbd(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "'TBD'" in sql

    def test_detects_deceased(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "'DECEASED'" in sql

    def test_detects_john_doe(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "'JOHN DOE'" in sql

    def test_detects_fnu_lnu(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "'FNU'" in sql
        assert "'LNU'" in sql

    def test_upper_trim_applied(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        assert "UPPER(TRIM(" in sql


class TestIsPlaceholderAddress:
    """Tests for is_placeholder_address feature function."""

    def test_registered(self):
        assert "is_placeholder_address" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_address"](["addr"])
        assert "CASE WHEN" in sql
        assert "THEN 1 ELSE 0 END" in sql

    def test_detects_123_main(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_address"](["addr"])
        assert "123 MAIN ST" in sql

    def test_detects_general_delivery(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_address"](["addr"])
        assert "GENERAL DELIVERY" in sql

    def test_detects_homeless(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_address"](["addr"])
        assert "HOMELESS" in sql

    def test_detects_all_zeros(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_address"](["addr"])
        assert "^0+$" in sql


class TestIsPlaceholderSsn:
    """Tests for is_placeholder_ssn feature function."""

    def test_registered(self):
        assert "is_placeholder_ssn" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_ssn"](["ssn"])
        assert "CASE WHEN" in sql
        assert "THEN 1 ELSE 0 END" in sql

    def test_detects_all_zeros(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_ssn"](["ssn"])
        assert "000000000" in sql

    def test_detects_all_nines(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_ssn"](["ssn"])
        assert "999999999" in sql

    def test_detects_sequential(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_ssn"](["ssn"])
        assert "123456789" in sql

    def test_detects_repeated_patterns(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_ssn"](["ssn"])
        assert "111111111" in sql
        assert "888888888" in sql

    def test_strips_non_digits(self):
        sql = FEATURE_FUNCTIONS["is_placeholder_ssn"](["ssn"])
        assert "REGEXP_REPLACE" in sql


class TestNullifyPlaceholder:
    """Tests for generic nullify_placeholder feature function."""

    def test_registered(self):
        assert "nullify_placeholder" in FEATURE_FUNCTIONS

    def test_no_patterns_returns_column(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder"](["col"])
        assert sql == "col"

    def test_empty_patterns_returns_column(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder"](["col"], patterns=[])
        assert sql == "col"

    def test_with_patterns_returns_case(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder"](
            ["account_id"], patterns=["UNKNOWN", "N/A"]
        )
        assert "CASE WHEN" in sql
        assert "THEN NULL ELSE account_id END" in sql

    def test_patterns_uppercased(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder"](
            ["col"], patterns=["unknown", "test"]
        )
        assert "'UNKNOWN'" in sql
        assert "'TEST'" in sql

    def test_uses_upper_trim(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder"](
            ["col"], patterns=["X"]
        )
        assert "UPPER(TRIM(" in sql


class TestNullifyPlaceholderPhone:
    """Tests for nullify_placeholder_phone feature function."""

    def test_registered(self):
        assert "nullify_placeholder_phone" in FEATURE_FUNCTIONS

    def test_returns_null_on_match(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_phone"](["phone"])
        assert "THEN NULL ELSE phone END" in sql

    def test_detects_same_patterns_as_flag(self):
        flag_sql = FEATURE_FUNCTIONS["is_placeholder_phone"](["phone"])
        null_sql = FEATURE_FUNCTIONS["nullify_placeholder_phone"](["phone"])
        # Both should contain the same repeating-digit patterns
        assert "9999999999" in null_sql
        assert "1234567890" in null_sql
        # Flag returns 1, nullify returns NULL
        assert "THEN 1" in flag_sql
        assert "THEN NULL" in null_sql


class TestNullifyPlaceholderEmail:
    """Tests for nullify_placeholder_email feature function."""

    def test_registered(self):
        assert "nullify_placeholder_email" in FEATURE_FUNCTIONS

    def test_returns_null_on_match(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_email"](["email"])
        assert "THEN NULL ELSE email END" in sql

    def test_detects_same_patterns_as_flag(self):
        flag_sql = FEATURE_FUNCTIONS["is_placeholder_email"](["email"])
        null_sql = FEATURE_FUNCTIONS["nullify_placeholder_email"](["email"])
        assert "noemail" in null_sql.lower()
        assert "THEN 1" in flag_sql
        assert "THEN NULL" in null_sql

    def test_case_insensitive(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_email"](["email"])
        assert "LOWER" in sql


class TestNullifyPlaceholderName:
    """Tests for nullify_placeholder_name feature function."""

    def test_registered(self):
        assert "nullify_placeholder_name" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_name"](["name"])
        assert "CASE WHEN" in sql
        assert "THEN NULL ELSE name END" in sql

    def test_detects_unknown(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_name"](["name"])
        assert "'UNKNOWN'" in sql

    def test_detects_john_doe(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_name"](["name"])
        assert "'JOHN DOE'" in sql

    def test_detects_fnu_lnu(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_name"](["name"])
        assert "'FNU'" in sql
        assert "'LNU'" in sql

    def test_uses_upper_trim(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_name"](["name"])
        assert "UPPER(TRIM(" in sql

    def test_matches_is_placeholder_name_patterns(self):
        flag_sql = FEATURE_FUNCTIONS["is_placeholder_name"](["name"])
        null_sql = FEATURE_FUNCTIONS["nullify_placeholder_name"](["name"])
        assert "THEN 1" in flag_sql
        assert "THEN NULL" in null_sql
        assert "'DECEASED'" in null_sql


class TestNullifyPlaceholderAddress:
    """Tests for nullify_placeholder_address feature function."""

    def test_registered(self):
        assert "nullify_placeholder_address" in FEATURE_FUNCTIONS

    def test_returns_case_expression(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_address"](["addr"])
        assert "CASE WHEN" in sql
        assert "THEN NULL ELSE addr END" in sql

    def test_detects_123_main_st(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_address"](["addr"])
        assert "'123 MAIN ST'" in sql

    def test_detects_homeless(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_address"](["addr"])
        assert "'HOMELESS'" in sql

    def test_detects_all_zeros(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_address"](["addr"])
        assert "^0+$" in sql

    def test_uses_upper_trim(self):
        sql = FEATURE_FUNCTIONS["nullify_placeholder_address"](["addr"])
        assert "UPPER(TRIM(" in sql

    def test_matches_is_placeholder_address_patterns(self):
        flag_sql = FEATURE_FUNCTIONS["is_placeholder_address"](["addr"])
        null_sql = FEATURE_FUNCTIONS["nullify_placeholder_address"](["addr"])
        assert "THEN 1" in flag_sql
        assert "THEN NULL" in null_sql
        assert "'GENERAL DELIVERY'" in null_sql

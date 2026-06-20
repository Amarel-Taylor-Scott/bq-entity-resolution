"""Tests for contact (phone and email) feature functions."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestPhoneStandardize:
    def test_returns_sql_string(self):
        result = FEATURE_FUNCTIONS["phone_standardize"](["phone"])
        assert isinstance(result, str)

    def test_strips_non_digits(self):
        result = FEATURE_FUNCTIONS["phone_standardize"](["phone"])
        assert "REGEXP_REPLACE" in result and "[^0-9]" in result

    def test_handles_country_codes(self):
        result = FEATURE_FUNCTIONS["phone_standardize"](["phone"])
        # Should check for leading '1' (US) or '0' (UK)
        assert "STARTS_WITH" in result

    def test_uses_case_expression(self):
        result = FEATURE_FUNCTIONS["phone_standardize"](["phone"])
        assert "CASE" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["phone_standardize"](["cell_phone"])
        assert "cell_phone" in result


class TestPhoneAreaCode:
    def test_extracts_first_3_digits(self):
        result = FEATURE_FUNCTIONS["phone_area_code"](["phone"])
        assert "LEFT" in result and "3" in result

    def test_normalizes_first(self):
        result = FEATURE_FUNCTIONS["phone_area_code"](["phone"])
        assert "REGEXP_REPLACE" in result


class TestPhoneLastFour:
    def test_extracts_last_4_digits(self):
        result = FEATURE_FUNCTIONS["phone_last_four"](["phone"])
        assert "RIGHT" in result and "4" in result


class TestEmailDomain:
    def test_extracts_after_at(self):
        result = FEATURE_FUNCTIONS["email_domain"](["email"])
        assert "@" in result and "LOWER" in result

    def test_uses_regexp_extract(self):
        result = FEATURE_FUNCTIONS["email_domain"](["email"])
        assert "REGEXP_EXTRACT" in result


class TestEmailLocalPart:
    def test_extracts_before_at(self):
        result = FEATURE_FUNCTIONS["email_local_part"](["email"])
        assert "@" in result and "LOWER" in result

    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["email_local_part"](["email_addr"])
        assert "email_addr" in result


class TestEmailDomainType:
    def test_classifies_free_providers(self):
        result = FEATURE_FUNCTIONS["email_domain_type"](["email"])
        assert "gmail.com" in result and "yahoo.com" in result and "FREE" in result

    def test_returns_business_for_others(self):
        result = FEATURE_FUNCTIONS["email_domain_type"](["email"])
        assert "BUSINESS" in result

    def test_uses_case_expression(self):
        result = FEATURE_FUNCTIONS["email_domain_type"](["email"])
        assert "CASE" in result

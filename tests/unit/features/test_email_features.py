"""Tests for email intelligence features."""
from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


class TestEmailLocalPartSafe:
    """Tests for email_local_part_safe feature."""
    def test_extracts_before_at(self):
        result = FEATURE_FUNCTIONS["email_local_part_safe"](["email"])
        assert isinstance(result, str)
        assert "@" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["email_local_part_safe"](["contact_email"])
        assert "contact_email" in result
    def test_handles_null(self):
        result = FEATURE_FUNCTIONS["email_local_part_safe"](["email"])
        assert "NULL" in result
    def test_null_safe_strpos(self):
        result = FEATURE_FUNCTIONS["email_local_part_safe"](["email"])
        assert "STRPOS" in result and "IS NOT NULL" in result

class TestEmailDomainSafe:
    """Tests for email_domain_safe feature."""
    def test_extracts_after_at(self):
        result = FEATURE_FUNCTIONS["email_domain_safe"](["email"])
        assert isinstance(result, str)
        assert "@" in result
    def test_lowercases_domain(self):
        result = FEATURE_FUNCTIONS["email_domain_safe"](["email"])
        assert "LOWER" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["email_domain_safe"](["work_email"])
        assert "work_email" in result
    def test_null_safe_strpos(self):
        result = FEATURE_FUNCTIONS["email_domain_safe"](["email"])
        assert "STRPOS" in result and "IS NOT NULL" in result

class TestEmailIsRoleAddress:
    """Tests for email_is_role_address feature."""
    def test_detects_role_patterns(self):
        result = FEATURE_FUNCTIONS["email_is_role_address"](["email"])
        assert isinstance(result, str)
        assert "info" in result and "admin" in result and "sales" in result
    def test_returns_0_or_1(self):
        result = FEATURE_FUNCTIONS["email_is_role_address"](["email"])
        assert "THEN 1" in result and "ELSE 0" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["email_is_role_address"](["contact_email"])
        assert "contact_email" in result

class TestEmailDomainCategory:
    """Tests for email_domain_category feature."""
    def test_classifies_domains(self):
        result = FEATURE_FUNCTIONS["email_domain_category"](["email"])
        assert isinstance(result, str)
        assert "FREE" in result and "CORPORATE" in result
    def test_detects_free_providers(self):
        result = FEATURE_FUNCTIONS["email_domain_category"](["email"])
        assert "gmail" in result and "yahoo" in result
    def test_detects_disposable_providers(self):
        result = FEATURE_FUNCTIONS["email_domain_category"](["email"])
        assert "DISPOSABLE" in result and "mailinator" in result
    def test_detects_government_domains(self):
        result = FEATURE_FUNCTIONS["email_domain_category"](["email"])
        assert "GOVERNMENT" in result and "gov" in result
    def test_uses_input_column(self):
        result = FEATURE_FUNCTIONS["email_domain_category"](["work_email"])
        assert "work_email" in result

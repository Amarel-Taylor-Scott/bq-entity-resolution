"""Tests for column role mappings."""

from bq_entity_resolution.config.roles import (
    BUSINESS_ROLES,
    PERSON_ROLES,
    ROLE_COMPARISONS,
    ROLE_FEATURES,
    blocking_keys_for_role,
    comparisons_for_role,
    detect_role,
    features_for_role,
)


class TestDetectRole:
    def test_exact_match(self):
        assert detect_role("first_name") == "first_name"
        assert detect_role("last_name") == "last_name"
        assert detect_role("email") == "email"

    def test_case_insensitive(self):
        assert detect_role("First_Name") == "first_name"
        assert detect_role("EMAIL") == "email"
        assert detect_role("DOB") == "date_of_birth"

    def test_common_aliases(self):
        assert detect_role("fname") == "first_name"
        assert detect_role("lname") == "last_name"
        assert detect_role("surname") == "last_name"
        assert detect_role("given_name") == "first_name"
        assert detect_role("birth_date") == "date_of_birth"

    def test_substring_match(self):
        assert detect_role("customer_email_address") == "email"
        assert detect_role("home_phone_number") == "phone"

    def test_unknown_returns_none(self):
        assert detect_role("foobar") is None
        assert detect_role("x") is None
        assert detect_role("record_count") is None

    def test_zip_patterns(self):
        assert detect_role("zip_code") == "zip_code"
        assert detect_role("postal_code") == "zip_code"

    def test_business_roles(self):
        assert detect_role("company_name") == "company_name"
        assert detect_role("business_name") == "company_name"
        assert detect_role("ein") == "ein"
        assert detect_role("tax_id") == "ein"


class TestFeaturesForRole:
    def test_first_name_features(self):
        features = features_for_role("first_name", "first_name")
        assert len(features) >= 2
        names = [f["name"] for f in features]
        assert "first_name_clean" in names
        assert "first_name_soundex" in names

    def test_email_features(self):
        features = features_for_role("email", "email")
        names = [f["name"] for f in features]
        assert "email_domain" in names
        assert "email_clean" in names

    def test_date_of_birth_features(self):
        features = features_for_role("dob", "date_of_birth")
        names = [f["name"] for f in features]
        assert "dob_year" in names

    def test_unknown_role_returns_empty(self):
        features = features_for_role("col", "unknown_role")
        assert features == []

    def test_feature_has_inputs(self):
        features = features_for_role("last_name", "last_name")
        for f in features:
            assert "inputs" in f
            assert f["inputs"] == ["last_name"]

    def test_state_has_no_features(self):
        features = features_for_role("state", "state")
        assert features == []


class TestBlockingKeysForRole:
    def test_last_name_blocking(self):
        keys = blocking_keys_for_role("last_name", "last_name")
        assert len(keys) >= 1
        assert keys[0]["name"] == "bk_last_soundex"

    def test_email_blocking(self):
        keys = blocking_keys_for_role("email", "email")
        assert len(keys) >= 1
        assert "email_domain" in keys[0]["name"]

    def test_no_blocking_keys(self):
        keys = blocking_keys_for_role("state", "state")
        assert keys == []


class TestComparisonsForRole:
    def test_first_name_comparisons(self):
        comps = comparisons_for_role("first_name", "first_name")
        assert len(comps) >= 2
        methods = [c["method"] for c in comps]
        assert "jaro_winkler" in methods
        assert "exact" in methods

    def test_email_comparisons(self):
        comps = comparisons_for_role("email", "email")
        methods = [c["method"] for c in comps]
        assert "exact" in methods

    def test_comparison_has_left_right(self):
        comps = comparisons_for_role("first_name", "first_name")
        for c in comps:
            assert "left" in c
            assert "right" in c
            assert c["left"] == c["right"]

    def test_comparison_has_weight(self):
        comps = comparisons_for_role("date_of_birth", "date_of_birth")
        for c in comps:
            assert "weight" in c
            assert c["weight"] > 0


class TestRoleConstants:
    def test_person_roles_defined(self):
        assert "first_name" in PERSON_ROLES
        assert "last_name" in PERSON_ROLES
        assert "date_of_birth" in PERSON_ROLES
        assert "email" in PERSON_ROLES

    def test_business_roles_defined(self):
        assert "company_name" in BUSINESS_ROLES
        assert "ein" in BUSINESS_ROLES

    def test_all_roles_have_features_or_comparisons(self):
        all_roles = PERSON_ROLES | BUSINESS_ROLES
        for role in all_roles:
            has_features = role in ROLE_FEATURES
            has_comparisons = role in ROLE_COMPARISONS
            assert has_features or has_comparisons, (
                f"Role '{role}' has neither features nor comparisons"
            )

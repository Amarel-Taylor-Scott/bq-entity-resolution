"""Tests for cross-industry role mappings in roles.py.

Covers telecom, logistics, retail, real estate, public sector,
education, travel, manufacturing, vendor master, and identity/fraud
role categories added for cross-industry entity resolution.
"""
from __future__ import annotations

import pytest

from bq_entity_resolution.config.roles import (
    EDUCATION_ROLES,
    IDENTITY_FRAUD_ROLES,
    LOGISTICS_ROLES,
    MANUFACTURING_ROLES,
    PUBLIC_SECTOR_ROLES,
    REAL_ESTATE_ROLES,
    RETAIL_ROLES,
    ROLE_BLOCKING_KEYS,
    ROLE_COMPARISONS,
    ROLE_FEATURES,
    TELECOM_ROLES,
    TRAVEL_ROLES,
    VENDOR_MASTER_ROLES,
    blocking_keys_for_role,
    comparisons_for_role,
    detect_role,
    features_for_role,
)

# ---------------------------------------------------------------------------
# Role set existence and contents
# ---------------------------------------------------------------------------


class TestRoleSetsExist:
    """Verify that all cross-industry role sets are defined and non-empty."""

    def test_telecom_roles_exist(self):
        assert isinstance(TELECOM_ROLES, frozenset)
        assert len(TELECOM_ROLES) > 0

    def test_logistics_roles_exist(self):
        assert isinstance(LOGISTICS_ROLES, frozenset)
        assert len(LOGISTICS_ROLES) > 0

    def test_retail_roles_exist(self):
        assert isinstance(RETAIL_ROLES, frozenset)
        assert len(RETAIL_ROLES) > 0

    def test_real_estate_roles_exist(self):
        assert isinstance(REAL_ESTATE_ROLES, frozenset)
        assert len(REAL_ESTATE_ROLES) > 0

    def test_public_sector_roles_exist(self):
        assert isinstance(PUBLIC_SECTOR_ROLES, frozenset)
        assert len(PUBLIC_SECTOR_ROLES) > 0

    def test_education_roles_exist(self):
        assert isinstance(EDUCATION_ROLES, frozenset)
        assert len(EDUCATION_ROLES) > 0

    def test_travel_roles_exist(self):
        assert isinstance(TRAVEL_ROLES, frozenset)
        assert len(TRAVEL_ROLES) > 0

    def test_manufacturing_roles_exist(self):
        assert isinstance(MANUFACTURING_ROLES, frozenset)
        assert len(MANUFACTURING_ROLES) > 0

    def test_vendor_master_roles_exist(self):
        assert isinstance(VENDOR_MASTER_ROLES, frozenset)
        assert len(VENDOR_MASTER_ROLES) > 0

    def test_identity_fraud_roles_exist(self):
        assert isinstance(IDENTITY_FRAUD_ROLES, frozenset)
        assert len(IDENTITY_FRAUD_ROLES) > 0


class TestRoleSetContents:
    """Verify specific roles are members of their expected role sets."""

    def test_telecom_contains_domain_roles(self):
        for role in [
            "subscriber_id", "imsi", "imei", "msisdn",
            "service_point_id", "meter_id", "circuit_id", "equipment_serial",
        ]:
            assert role in TELECOM_ROLES, f"{role} missing from TELECOM_ROLES"

    def test_logistics_contains_domain_roles(self):
        for role in [
            "duns_number", "mc_dot_number", "carrier_scac",
            "bill_of_lading", "container_id", "tracking_number",
        ]:
            assert role in LOGISTICS_ROLES, f"{role} missing from LOGISTICS_ROLES"

    def test_retail_contains_domain_roles(self):
        for role in [
            "loyalty_id", "customer_id", "order_id",
            "device_fingerprint_id", "payment_token_id",
        ]:
            assert role in RETAIL_ROLES, f"{role} missing from RETAIL_ROLES"

    def test_real_estate_contains_domain_roles(self):
        for role in ["parcel_number", "mls_id", "deed_reference"]:
            assert role in REAL_ESTATE_ROLES, f"{role} missing from REAL_ESTATE_ROLES"

    def test_public_sector_contains_domain_roles(self):
        for role in [
            "passport", "national_id", "voter_registration",
            "license_number", "case_number",
        ]:
            assert role in PUBLIC_SECTOR_ROLES, f"{role} missing from PUBLIC_SECTOR_ROLES"

    def test_education_contains_domain_roles(self):
        for role in ["student_id", "enrollment_id", "institution_code"]:
            assert role in EDUCATION_ROLES, f"{role} missing from EDUCATION_ROLES"

    def test_travel_contains_domain_roles(self):
        for role in ["guest_id", "booking_reference", "frequent_flyer_number"]:
            assert role in TRAVEL_ROLES, f"{role} missing from TRAVEL_ROLES"

    def test_manufacturing_contains_domain_roles(self):
        for role in ["device_id", "serial_number", "asset_tag", "mac_address"]:
            assert role in MANUFACTURING_ROLES, f"{role} missing from MANUFACTURING_ROLES"

    def test_vendor_master_contains_domain_roles(self):
        for role in ["vendor_id", "cage_code", "sam_uei"]:
            assert role in VENDOR_MASTER_ROLES, f"{role} missing from VENDOR_MASTER_ROLES"

    def test_identity_fraud_contains_domain_roles(self):
        for role in ["device_fingerprint_id", "ip_address", "user_agent"]:
            assert role in IDENTITY_FRAUD_ROLES, f"{role} missing from IDENTITY_FRAUD_ROLES"

    def test_telecom_includes_person_basics(self):
        """Telecom set should include common person roles for subscriber matching."""
        for role in ["first_name", "last_name", "phone", "email"]:
            assert role in TELECOM_ROLES

    def test_logistics_includes_business_basics(self):
        """Logistics set should include business roles for carrier matching."""
        for role in ["company_name", "ein"]:
            assert role in LOGISTICS_ROLES

    def test_vendor_master_includes_business_basics(self):
        """Vendor master should include organization basics."""
        for role in ["company_name", "ein"]:
            assert role in VENDOR_MASTER_ROLES


# ---------------------------------------------------------------------------
# detect_role() for new patterns
# ---------------------------------------------------------------------------


class TestDetectRoleTelecom:
    """Test detect_role() for telecom / utility column name patterns."""

    def test_subscriber_id(self):
        assert detect_role("subscriber_id") == "subscriber_id"

    def test_subscriber_number(self):
        assert detect_role("subscriber_number") == "subscriber_id"

    def test_imsi(self):
        assert detect_role("imsi") == "imsi"

    def test_imei(self):
        assert detect_role("imei") == "imei"

    def test_msisdn(self):
        assert detect_role("msisdn") == "msisdn"

    def test_service_point_id(self):
        assert detect_role("service_point_id") == "service_point_id"

    def test_service_point(self):
        assert detect_role("service_point") == "service_point_id"

    def test_meter_id(self):
        assert detect_role("meter_id") == "meter_id"

    def test_meter_number(self):
        assert detect_role("meter_number") == "meter_id"

    def test_meter_no(self):
        assert detect_role("meter_no") == "meter_id"

    def test_circuit_id(self):
        assert detect_role("circuit_id") == "circuit_id"

    def test_equipment_serial(self):
        assert detect_role("equipment_serial") == "equipment_serial"

    def test_equipment_serial_number(self):
        assert detect_role("equipment_serial_number") == "equipment_serial"


class TestDetectRoleLogistics:
    """Test detect_role() for logistics / supply chain patterns."""

    def test_duns_number(self):
        assert detect_role("duns_number") == "duns_number"

    def test_duns(self):
        assert detect_role("duns") == "duns_number"

    def test_duns_no(self):
        assert detect_role("duns_no") == "duns_number"

    def test_mc_dot_number(self):
        assert detect_role("mc_dot_number") == "mc_dot_number"

    def test_mc_number(self):
        assert detect_role("mc_number") == "mc_dot_number"

    def test_dot_number(self):
        assert detect_role("dot_number") == "mc_dot_number"

    def test_carrier_scac(self):
        assert detect_role("carrier_scac") == "carrier_scac"

    def test_scac(self):
        assert detect_role("scac") == "carrier_scac"

    def test_scac_code(self):
        assert detect_role("scac_code") == "carrier_scac"

    def test_bill_of_lading(self):
        assert detect_role("bill_of_lading") == "bill_of_lading"

    def test_bol(self):
        assert detect_role("bol") == "bill_of_lading"

    def test_bol_number(self):
        assert detect_role("bol_number") == "bill_of_lading"

    def test_container_id(self):
        assert detect_role("container_id") == "container_id"

    def test_container_number(self):
        assert detect_role("container_number") == "container_id"

    def test_tracking_number(self):
        assert detect_role("tracking_number") == "tracking_number"

    def test_tracking_no(self):
        assert detect_role("tracking_no") == "tracking_number"

    def test_shipment_tracking(self):
        assert detect_role("shipment_tracking") == "tracking_number"


class TestDetectRoleRetail:
    """Test detect_role() for retail / e-commerce patterns."""

    def test_loyalty_id(self):
        assert detect_role("loyalty_id") == "loyalty_id"

    def test_loyalty_number(self):
        assert detect_role("loyalty_number") == "loyalty_id"

    def test_loyalty_card(self):
        assert detect_role("loyalty_card") == "loyalty_id"

    def test_rewards_number(self):
        assert detect_role("rewards_number") == "loyalty_id"

    def test_customer_id(self):
        assert detect_role("customer_id") == "customer_id"

    def test_cust_id(self):
        assert detect_role("cust_id") == "customer_id"

    def test_order_id(self):
        assert detect_role("order_id") == "order_id"

    def test_order_number(self):
        assert detect_role("order_number") == "order_id"

    def test_order_no(self):
        assert detect_role("order_no") == "order_id"

    def test_device_fingerprint_id(self):
        assert detect_role("device_fingerprint_id") == "device_fingerprint_id"

    def test_device_fingerprint(self):
        assert detect_role("device_fingerprint") == "device_fingerprint_id"

    def test_payment_token_id(self):
        assert detect_role("payment_token_id") == "payment_token_id"

    def test_payment_token(self):
        assert detect_role("payment_token") == "payment_token_id"


class TestDetectRoleRealEstate:
    """Test detect_role() for real estate / property patterns."""

    def test_parcel_number(self):
        assert detect_role("parcel_number") == "parcel_number"

    def test_parcel_no(self):
        assert detect_role("parcel_no") == "parcel_number"

    def test_parcel_id(self):
        assert detect_role("parcel_id") == "parcel_number"

    def test_apn(self):
        assert detect_role("apn") == "parcel_number"

    def test_mls_id(self):
        assert detect_role("mls_id") == "mls_id"

    def test_mls_number(self):
        assert detect_role("mls_number") == "mls_id"

    def test_listing_id(self):
        assert detect_role("listing_id") == "mls_id"

    def test_deed_reference(self):
        assert detect_role("deed_reference") == "deed_reference"

    def test_deed_ref(self):
        assert detect_role("deed_ref") == "deed_reference"

    def test_deed_number(self):
        assert detect_role("deed_number") == "deed_reference"


class TestDetectRolePublicSector:
    """Test detect_role() for public sector patterns."""

    def test_passport(self):
        assert detect_role("passport") == "passport"

    def test_passport_number(self):
        assert detect_role("passport_number") == "passport"

    def test_passport_no(self):
        assert detect_role("passport_no") == "passport"

    def test_national_id(self):
        assert detect_role("national_id") == "national_id"

    def test_national_id_number(self):
        assert detect_role("national_id_number") == "national_id"

    def test_voter_registration(self):
        assert detect_role("voter_registration") == "voter_registration"

    def test_voter_id(self):
        assert detect_role("voter_id") == "voter_registration"

    def test_voter_reg(self):
        assert detect_role("voter_reg") == "voter_registration"

    def test_license_number(self):
        assert detect_role("license_number") == "license_number"

    def test_license_no(self):
        assert detect_role("license_no") == "license_number"

    def test_drivers_license(self):
        assert detect_role("drivers_license") == "license_number"

    def test_dl_number(self):
        assert detect_role("dl_number") == "license_number"

    def test_case_number(self):
        assert detect_role("case_number") == "case_number"

    def test_case_no(self):
        assert detect_role("case_no") == "case_number"

    def test_case_id(self):
        assert detect_role("case_id") == "case_number"

    def test_docket_number(self):
        assert detect_role("docket_number") == "case_number"


class TestDetectRoleEducation:
    """Test detect_role() for education patterns."""

    def test_student_id(self):
        assert detect_role("student_id") == "student_id"

    def test_student_number(self):
        assert detect_role("student_number") == "student_id"

    def test_enrollment_id(self):
        assert detect_role("enrollment_id") == "enrollment_id"

    def test_enrollment_number(self):
        assert detect_role("enrollment_number") == "enrollment_id"

    def test_institution_code(self):
        assert detect_role("institution_code") == "institution_code"

    def test_school_code(self):
        assert detect_role("school_code") == "institution_code"

    def test_ipeds_code(self):
        assert detect_role("ipeds_code") == "institution_code"


class TestDetectRoleTravel:
    """Test detect_role() for travel / hospitality patterns."""

    def test_guest_id(self):
        assert detect_role("guest_id") == "guest_id"

    def test_guest_number(self):
        assert detect_role("guest_number") == "guest_id"

    def test_booking_reference(self):
        assert detect_role("booking_reference") == "booking_reference"

    def test_booking_ref(self):
        assert detect_role("booking_ref") == "booking_reference"

    def test_reservation_number(self):
        assert detect_role("reservation_number") == "booking_reference"

    def test_confirmation_number(self):
        assert detect_role("confirmation_number") == "booking_reference"

    def test_pnr(self):
        assert detect_role("pnr") == "booking_reference"

    def test_frequent_flyer_number(self):
        assert detect_role("frequent_flyer_number") == "frequent_flyer_number"

    def test_frequent_flyer(self):
        assert detect_role("frequent_flyer") == "frequent_flyer_number"

    def test_ff_number(self):
        assert detect_role("ff_number") == "frequent_flyer_number"

    def test_mileage_number(self):
        assert detect_role("mileage_number") == "frequent_flyer_number"


class TestDetectRoleManufacturing:
    """Test detect_role() for manufacturing / IoT patterns."""

    def test_device_id(self):
        assert detect_role("device_id") == "device_id"

    def test_serial_number(self):
        assert detect_role("serial_number") == "serial_number"

    def test_serial_no(self):
        assert detect_role("serial_no") == "serial_number"

    def test_asset_tag(self):
        assert detect_role("asset_tag") == "asset_tag"

    def test_asset_id(self):
        assert detect_role("asset_id") == "asset_tag"

    def test_mac_address(self):
        assert detect_role("mac_address") == "mac_address"

    def test_mac_addr(self):
        assert detect_role("mac_addr") == "mac_address"


class TestDetectRoleVendorMaster:
    """Test detect_role() for vendor master patterns."""

    def test_vendor_id(self):
        assert detect_role("vendor_id") == "vendor_id"

    def test_vendor_number(self):
        assert detect_role("vendor_number") == "vendor_id"

    def test_vendor_no(self):
        assert detect_role("vendor_no") == "vendor_id"

    def test_supplier_id(self):
        assert detect_role("supplier_id") == "vendor_id"

    def test_cage_code(self):
        assert detect_role("cage_code") == "cage_code"

    def test_sam_uei(self):
        assert detect_role("sam_uei") == "sam_uei"

    def test_uei_number(self):
        assert detect_role("uei_number") == "sam_uei"


class TestDetectRoleIdentityFraud:
    """Test detect_role() for identity / fraud patterns."""

    def test_ip_address(self):
        assert detect_role("ip_address") == "ip_address"

    def test_ip_addr(self):
        assert detect_role("ip_addr") == "ip_address"

    def test_user_agent(self):
        assert detect_role("user_agent") == "user_agent"


class TestDetectRoleCaseInsensitive:
    """Verify detect_role() is case-insensitive for new roles."""

    def test_upper_case_subscriber_id(self):
        assert detect_role("SUBSCRIBER_ID") == "subscriber_id"

    def test_mixed_case_tracking_number(self):
        assert detect_role("Tracking_Number") == "tracking_number"

    def test_upper_case_mac_address(self):
        assert detect_role("MAC_ADDRESS") == "mac_address"

    def test_upper_case_pnr(self):
        assert detect_role("PNR") == "booking_reference"


# ---------------------------------------------------------------------------
# features_for_role() for new roles
# ---------------------------------------------------------------------------

# All new cross-industry roles that should appear in ROLE_FEATURES
_NEW_ROLES_WITH_FEATURES = [
    # Telecom
    "subscriber_id", "imsi", "imei", "msisdn",
    "service_point_id", "meter_id", "circuit_id", "equipment_serial",
    # Logistics
    "duns_number", "mc_dot_number", "carrier_scac",
    "bill_of_lading", "container_id", "tracking_number",
    # Retail
    "loyalty_id", "customer_id", "order_id",
    "device_fingerprint_id", "payment_token_id",
    # Real Estate
    "parcel_number", "mls_id", "deed_reference",
    # Public Sector
    "passport", "national_id", "voter_registration",
    "license_number", "case_number",
    # Education
    "student_id", "enrollment_id", "institution_code",
    # Travel
    "guest_id", "booking_reference", "frequent_flyer_number",
    # Manufacturing
    "device_id", "serial_number", "asset_tag", "mac_address",
    # Vendor Master
    "vendor_id", "cage_code", "sam_uei",
    # Identity / Fraud
    "ip_address",
]


class TestFeaturesForNewRoles:
    """Verify features_for_role() returns features for every new role."""

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_FEATURES)
    def test_role_in_feature_registry(self, role):
        """Each new role should be registered in ROLE_FEATURES."""
        assert role in ROLE_FEATURES, f"{role} missing from ROLE_FEATURES"

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_FEATURES)
    def test_features_generated(self, role):
        """features_for_role() should return at least one feature dict."""
        features = features_for_role(role, role)
        assert len(features) >= 1, f"No features generated for role '{role}'"

    def test_user_agent_has_no_features(self):
        """user_agent role produces no features (free text, no transform)."""
        assert "user_agent" in ROLE_FEATURES
        features = features_for_role("user_agent_col", "user_agent")
        assert len(features) == 0

    def test_subscriber_id_features(self):
        features = features_for_role("sub_id", "subscriber_id")
        assert len(features) == 1
        assert features[0]["name"] == "sub_id_clean"
        assert features[0]["function"] == "upper_trim"
        assert features[0]["inputs"] == ["sub_id"]

    def test_msisdn_features(self):
        """MSISDN uses phone_standardize and phone_last_four like phone."""
        features = features_for_role("msisdn_col", "msisdn")
        func_names = [f["function"] for f in features]
        assert "phone_standardize" in func_names
        assert "phone_last_four" in func_names

    def test_duns_number_features(self):
        features = features_for_role("duns_col", "duns_number")
        assert len(features) == 1
        assert features[0]["function"] == "duns_clean"

    def test_mac_address_features(self):
        features = features_for_role("mac_col", "mac_address")
        assert len(features) == 1
        assert features[0]["function"] == "lower_trim"

    def test_device_fingerprint_features(self):
        features = features_for_role("dfp_col", "device_fingerprint_id")
        assert len(features) == 1
        assert features[0]["function"] == "lower_trim"

    def test_license_number_features(self):
        features = features_for_role("lic_col", "license_number")
        assert len(features) == 1
        assert features[0]["function"] == "license_number_clean"


# ---------------------------------------------------------------------------
# blocking_keys_for_role() for new roles
# ---------------------------------------------------------------------------

# Roles that should produce blocking keys (all new roles except user_agent)
_NEW_ROLES_WITH_BLOCKING = [
    r for r in _NEW_ROLES_WITH_FEATURES
    # user_agent has no blocking key
]


class TestBlockingKeysForNewRoles:
    """Verify blocking_keys_for_role() returns blocking keys for new roles."""

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_BLOCKING)
    def test_role_in_blocking_registry(self, role):
        """Each new role should be registered in ROLE_BLOCKING_KEYS."""
        assert role in ROLE_BLOCKING_KEYS, f"{role} missing from ROLE_BLOCKING_KEYS"

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_BLOCKING)
    def test_blocking_keys_generated(self, role):
        """blocking_keys_for_role() should return at least one key dict."""
        keys = blocking_keys_for_role(role, role)
        assert len(keys) >= 1, f"No blocking keys generated for role '{role}'"

    def test_blocking_key_format(self):
        """Blocking keys should have the expected dict structure."""
        keys = blocking_keys_for_role("subscriber_col", "subscriber_id")
        assert len(keys) == 1
        k = keys[0]
        assert "name" in k
        assert "function" in k
        assert "inputs" in k
        assert k["name"].startswith("bk_")
        assert k["inputs"] == ["subscriber_col"]

    def test_telecom_uses_farm_fingerprint(self):
        """Telecom identifiers use farm_fingerprint for high-cardinality blocking."""
        for role in ["subscriber_id", "imsi", "imei", "service_point_id", "meter_id"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint", (
                f"{role} should use farm_fingerprint"
            )

    def test_msisdn_uses_phone_last_four(self):
        """MSISDN blocking uses phone_last_four (like phone)."""
        keys = blocking_keys_for_role("msisdn_col", "msisdn")
        assert keys[0]["function"] == "phone_last_four"

    def test_logistics_uses_farm_fingerprint(self):
        """Logistics identifiers use farm_fingerprint for exact-match blocking."""
        for role in ["duns_number", "mc_dot_number", "carrier_scac",
                      "bill_of_lading", "container_id", "tracking_number"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint", (
                f"{role} should use farm_fingerprint"
            )

    def test_retail_uses_farm_fingerprint(self):
        for role in ["loyalty_id", "customer_id", "order_id",
                      "device_fingerprint_id", "payment_token_id"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_real_estate_uses_farm_fingerprint(self):
        for role in ["parcel_number", "mls_id", "deed_reference"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_public_sector_uses_farm_fingerprint(self):
        for role in ["passport", "national_id", "voter_registration",
                      "license_number", "case_number"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_education_uses_farm_fingerprint(self):
        for role in ["student_id", "enrollment_id", "institution_code"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_travel_uses_farm_fingerprint(self):
        for role in ["guest_id", "booking_reference", "frequent_flyer_number"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_manufacturing_uses_farm_fingerprint(self):
        for role in ["device_id", "serial_number", "asset_tag", "mac_address"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_vendor_master_uses_farm_fingerprint(self):
        for role in ["vendor_id", "cage_code", "sam_uei"]:
            keys = blocking_keys_for_role(role, role)
            assert keys[0]["function"] == "farm_fingerprint"

    def test_ip_address_uses_farm_fingerprint(self):
        keys = blocking_keys_for_role("ip_col", "ip_address")
        assert keys[0]["function"] == "farm_fingerprint"


# ---------------------------------------------------------------------------
# comparisons_for_role() for new roles
# ---------------------------------------------------------------------------

# All new cross-industry roles that should produce comparisons
_NEW_ROLES_WITH_COMPARISONS = [
    "subscriber_id", "imsi", "imei", "msisdn",
    "service_point_id", "meter_id", "circuit_id", "equipment_serial",
    "duns_number", "mc_dot_number", "carrier_scac",
    "bill_of_lading", "container_id", "tracking_number",
    "loyalty_id", "customer_id", "order_id",
    "device_fingerprint_id", "payment_token_id",
    "parcel_number", "mls_id", "deed_reference",
    "passport", "national_id", "voter_registration",
    "license_number", "case_number",
    "student_id", "enrollment_id", "institution_code",
    "guest_id", "booking_reference", "frequent_flyer_number",
    "device_id", "serial_number", "asset_tag", "mac_address",
    "vendor_id", "cage_code", "sam_uei",
    "ip_address",
]


class TestComparisonsForNewRoles:
    """Verify comparisons_for_role() returns comparisons for new roles."""

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_COMPARISONS)
    def test_role_in_comparison_registry(self, role):
        """Each new role should be registered in ROLE_COMPARISONS."""
        assert role in ROLE_COMPARISONS, f"{role} missing from ROLE_COMPARISONS"

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_COMPARISONS)
    def test_comparisons_generated(self, role):
        """comparisons_for_role() should return at least one comparison dict."""
        comparisons = comparisons_for_role(role, role)
        assert len(comparisons) >= 1, f"No comparisons for role '{role}'"

    def test_comparison_dict_format(self):
        """Comparisons should have the expected dict structure."""
        comparisons = comparisons_for_role("sub_col", "subscriber_id")
        c = comparisons[0]
        assert "name" in c
        assert "left" in c
        assert "right" in c
        assert "method" in c
        assert "weight" in c
        assert "params" in c

    def test_most_identifiers_use_exact_method(self):
        """Most new identifier roles use 'exact' comparison method."""
        exact_roles = [
            "subscriber_id", "imsi", "imei", "service_point_id",
            "duns_number", "carrier_scac", "loyalty_id", "customer_id",
            "parcel_number", "passport", "national_id",
            "student_id", "device_id", "serial_number",
            "vendor_id", "cage_code", "sam_uei",
        ]
        for role in exact_roles:
            comparisons = comparisons_for_role(role, role)
            methods = [c["method"] for c in comparisons]
            assert "exact" in methods, f"{role} should have an 'exact' comparison"

    def test_high_confidence_identifiers_have_high_weight(self):
        """Government/unique identifiers should have weight >= 6.0."""
        high_weight_roles = [
            "imsi", "imei", "duns_number", "parcel_number",
            "passport", "national_id", "serial_number", "sam_uei",
        ]
        for role in high_weight_roles:
            comparisons = comparisons_for_role(role, role)
            max_weight = max(c["weight"] for c in comparisons)
            assert max_weight >= 6.0, (
                f"{role} expected weight >= 6.0, got {max_weight}"
            )

    def test_msisdn_uses_exact_on_std(self):
        """MSISDN comparison uses 'exact' on the standardized phone feature."""
        comparisons = comparisons_for_role("msisdn_col", "msisdn")
        c = comparisons[0]
        assert c["method"] == "exact"
        assert c["left"] == "msisdn_col_std"

    def test_ip_address_lower_weight(self):
        """IP address has lower weight (shared IPs are common)."""
        comparisons = comparisons_for_role("ip_col", "ip_address")
        assert comparisons[0]["weight"] <= 4.0

    def test_comparison_left_right_match(self):
        """Left and right columns should be the same (self-join comparison)."""
        comparisons = comparisons_for_role("vin_col", "subscriber_id")
        for c in comparisons:
            assert c["left"] == c["right"]


# ---------------------------------------------------------------------------
# Cross-cutting: all new roles registered in all three dictionaries
# ---------------------------------------------------------------------------


class TestAllNewRolesConsistent:
    """Verify all new roles are consistently registered across all mappings."""

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_FEATURES)
    def test_role_in_features(self, role):
        assert role in ROLE_FEATURES

    @pytest.mark.parametrize("role", _NEW_ROLES_WITH_COMPARISONS)
    def test_role_in_comparisons(self, role):
        assert role in ROLE_COMPARISONS

    def test_no_orphan_features(self):
        """Every role in ROLE_FEATURES should also be in ROLE_COMPARISONS or
        have an explicit reason (user_agent, state, transaction_amount)."""
        exempt = {"user_agent"}  # no comparison needed
        for role in ROLE_FEATURES:
            if role not in ROLE_COMPARISONS:
                assert role in exempt or ROLE_FEATURES[role] == [], (
                    f"Role '{role}' has features but no comparisons"
                )

    def test_every_comparison_role_has_features(self):
        """Every role in ROLE_COMPARISONS should be in ROLE_FEATURES."""
        for role in ROLE_COMPARISONS:
            assert role in ROLE_FEATURES, (
                f"Role '{role}' in ROLE_COMPARISONS but not in ROLE_FEATURES"
            )

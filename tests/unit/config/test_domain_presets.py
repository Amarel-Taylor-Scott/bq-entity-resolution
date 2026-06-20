"""Tests for cross-industry domain preset functions.

Each preset function should generate a valid PipelineConfig with
the correct project settings, matching tiers, features, and link_type.
"""
from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import (
    education_student_preset,
    identity_fraud_preset,
    logistics_carrier_preset,
    public_sector_preset,
    real_estate_property_preset,
    retail_customer_preset,
    telecom_subscriber_preset,
    travel_guest_preset,
    vendor_master_preset,
)
from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Telecom Subscriber Preset
# ---------------------------------------------------------------------------


class TestTelecomSubscriberPreset:
    def test_basic_creation(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={
                "subscriber_id": "subscriber_id",
                "first_name": "first_name",
                "email": "email",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={
                "subscriber_id": "subscriber_id",
                "first_name": "first_name",
                "email": "email",
            },
        )
        assert len(config.matching_tiers) == 2
        tier_names = [t.name for t in config.matching_tiers]
        assert "exact" in tier_names
        assert "fuzzy" in tier_names

    def test_link_type(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={"subscriber_id": "subscriber_id", "email": "email"},
        )
        assert config.link_type == "link_and_dedupe"

    def test_generates_features(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={
                "subscriber_id": "subscriber_id",
                "imsi": "imsi",
                "msisdn_col": "msisdn",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_generates_blocking_keys(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={"subscriber_id": "subscriber_id", "imei": "imei"},
        )
        bk_names = [bk.name for bk in config.feature_engineering.blocking_keys]
        assert len(bk_names) >= 2

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            telecom_subscriber_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.subscribers",
            )

    def test_empty_columns_raises(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            telecom_subscriber_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.subscribers",
                columns={},
            )

    def test_custom_project_name(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={"subscriber_id": "subscriber_id", "email": "email"},
            project_name="custom_telecom",
        )
        assert config.project.name == "custom_telecom"

    def test_default_project_name(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={"subscriber_id": "subscriber_id", "email": "email"},
        )
        assert config.project.name == "telecom_subscriber_match"

    def test_validates_as_pydantic(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.subscribers",
            columns={
                "subscriber_id": "subscriber_id",
                "first_name": "first_name",
                "email": "email",
            },
        )
        assert config.version == "1.0"
        assert len(config.sources) == 1


# ---------------------------------------------------------------------------
# Logistics Carrier Preset
# ---------------------------------------------------------------------------


class TestLogisticsCarrierPreset:
    def test_basic_creation(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.carriers",
            columns={
                "duns": "duns_number",
                "company": "company_name",
                "scac": "carrier_scac",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.carriers",
            columns={"duns": "duns_number", "company": "company_name"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.carriers",
            columns={"duns": "duns_number", "company": "company_name"},
        )
        assert config.link_type == "link_and_dedupe"

    def test_generates_features(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.carriers",
            columns={
                "duns": "duns_number",
                "mc_dot": "mc_dot_number",
                "company": "company_name",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            logistics_carrier_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.carriers",
            )

    def test_default_project_name(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.carriers",
            columns={"duns": "duns_number", "company": "company_name"},
        )
        assert config.project.name == "logistics_carrier_match"

    def test_validates_as_pydantic(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.carriers",
            columns={"duns": "duns_number", "company": "company_name"},
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Retail Customer Preset
# ---------------------------------------------------------------------------


class TestRetailCustomerPreset:
    def test_basic_creation(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.customers",
            columns={
                "loyalty": "loyalty_id",
                "first_name": "first_name",
                "email": "email",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.customers",
            columns={"loyalty": "loyalty_id", "email": "email"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.customers",
            columns={"loyalty": "loyalty_id", "email": "email"},
        )
        assert config.link_type == "link_and_dedupe"

    def test_generates_features(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.customers",
            columns={
                "loyalty": "loyalty_id",
                "customer": "customer_id",
                "email": "email",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            retail_customer_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.customers",
            )

    def test_default_project_name(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.customers",
            columns={"loyalty": "loyalty_id", "email": "email"},
        )
        assert config.project.name == "retail_customer_match"

    def test_validates_as_pydantic(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.customers",
            columns={"loyalty": "loyalty_id", "email": "email"},
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Real Estate Property Preset
# ---------------------------------------------------------------------------


class TestRealEstatePropertyPreset:
    def test_basic_creation(self):
        config = real_estate_property_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.properties",
            columns={
                "parcel": "parcel_number",
                "address": "address_line_1",
                "city": "city",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = real_estate_property_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.properties",
            columns={"parcel": "parcel_number", "mls": "mls_id"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = real_estate_property_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.properties",
            columns={"parcel": "parcel_number", "mls": "mls_id"},
        )
        assert config.link_type == "dedupe_only"

    def test_generates_features(self):
        config = real_estate_property_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.properties",
            columns={
                "parcel": "parcel_number",
                "mls": "mls_id",
                "deed": "deed_reference",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            real_estate_property_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.properties",
            )

    def test_default_project_name(self):
        config = real_estate_property_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.properties",
            columns={"parcel": "parcel_number", "mls": "mls_id"},
        )
        assert config.project.name == "property_match"

    def test_validates_as_pydantic(self):
        config = real_estate_property_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.properties",
            columns={"parcel": "parcel_number", "mls": "mls_id"},
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Public Sector Preset
# ---------------------------------------------------------------------------


class TestPublicSectorPreset:
    def test_basic_creation(self):
        config = public_sector_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.citizens",
            columns={
                "passport_no": "passport",
                "first_name": "first_name",
                "last_name": "last_name",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = public_sector_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.citizens",
            columns={"passport_no": "passport", "dl": "license_number"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = public_sector_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.citizens",
            columns={"passport_no": "passport", "dl": "license_number"},
        )
        assert config.link_type == "dedupe_only"

    def test_generates_features(self):
        config = public_sector_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.citizens",
            columns={
                "passport_no": "passport",
                "nat_id": "national_id",
                "first_name": "first_name",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            public_sector_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.citizens",
            )

    def test_default_project_name(self):
        config = public_sector_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.citizens",
            columns={"passport_no": "passport", "dl": "license_number"},
        )
        assert config.project.name == "public_sector_match"

    def test_validates_as_pydantic(self):
        config = public_sector_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.citizens",
            columns={
                "passport_no": "passport",
                "first_name": "first_name",
                "last_name": "last_name",
            },
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Education Student Preset
# ---------------------------------------------------------------------------


class TestEducationStudentPreset:
    def test_basic_creation(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.students",
            columns={
                "student_id": "student_id",
                "first_name": "first_name",
                "last_name": "last_name",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.students",
            columns={"student_id": "student_id", "email": "email"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.students",
            columns={"student_id": "student_id", "email": "email"},
        )
        assert config.link_type == "dedupe_only"

    def test_generates_features(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.students",
            columns={
                "student_id": "student_id",
                "enrollment": "enrollment_id",
                "inst": "institution_code",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            education_student_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.students",
            )

    def test_default_project_name(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.students",
            columns={"student_id": "student_id", "email": "email"},
        )
        assert config.project.name == "student_match"

    def test_validates_as_pydantic(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.students",
            columns={"student_id": "student_id", "email": "email"},
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Travel Guest Preset
# ---------------------------------------------------------------------------


class TestTravelGuestPreset:
    def test_basic_creation(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.guests",
            columns={
                "guest_id": "guest_id",
                "first_name": "first_name",
                "email": "email",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.guests",
            columns={"guest_id": "guest_id", "booking": "booking_reference"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.guests",
            columns={"guest_id": "guest_id", "booking": "booking_reference"},
        )
        assert config.link_type == "link_and_dedupe"

    def test_generates_features(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.guests",
            columns={
                "guest_id": "guest_id",
                "booking": "booking_reference",
                "ff_num": "frequent_flyer_number",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 3

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            travel_guest_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.guests",
            )

    def test_default_project_name(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.guests",
            columns={"guest_id": "guest_id", "booking": "booking_reference"},
        )
        assert config.project.name == "guest_match"

    def test_validates_as_pydantic(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.guests",
            columns={
                "guest_id": "guest_id",
                "first_name": "first_name",
                "email": "email",
            },
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Vendor Master Preset
# ---------------------------------------------------------------------------


class TestVendorMasterPreset:
    def test_basic_creation(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.vendors",
            columns={
                "vendor_id": "vendor_id",
                "company": "company_name",
                "duns": "duns_number",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.vendors",
            columns={"vendor_id": "vendor_id", "company": "company_name"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.vendors",
            columns={"vendor_id": "vendor_id", "company": "company_name"},
        )
        assert config.link_type == "link_and_dedupe"

    def test_generates_features(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.vendors",
            columns={
                "vendor_id": "vendor_id",
                "company": "company_name",
                "cage": "cage_code",
                "uei": "sam_uei",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 4

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            vendor_master_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.vendors",
            )

    def test_default_project_name(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.vendors",
            columns={"vendor_id": "vendor_id", "company": "company_name"},
        )
        assert config.project.name == "vendor_master_match"

    def test_validates_as_pydantic(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.vendors",
            columns={"vendor_id": "vendor_id", "company": "company_name"},
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Identity / Fraud Preset
# ---------------------------------------------------------------------------


class TestIdentityFraudPreset:
    def test_basic_creation(self):
        config = identity_fraud_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.identities",
            columns={
                "device_fp": "device_fingerprint_id",
                "ip": "ip_address",
                "email": "email",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_generates_two_tiers(self):
        config = identity_fraud_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.identities",
            columns={"device_fp": "device_fingerprint_id", "email": "email"},
        )
        assert len(config.matching_tiers) == 2

    def test_link_type(self):
        config = identity_fraud_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.identities",
            columns={"device_fp": "device_fingerprint_id", "email": "email"},
        )
        assert config.link_type == "link_and_dedupe"

    def test_generates_features(self):
        config = identity_fraud_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.identities",
            columns={
                "device_fp": "device_fingerprint_id",
                "ip": "ip_address",
                "email": "email",
                "first_name": "first_name",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 4

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            identity_fraud_preset(
                bq_project="test-proj",
                source_table="test-proj.ds.identities",
            )

    def test_default_project_name(self):
        config = identity_fraud_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.identities",
            columns={"device_fp": "device_fingerprint_id", "email": "email"},
        )
        assert config.project.name == "identity_fraud_match"

    def test_validates_as_pydantic(self):
        config = identity_fraud_preset(
            bq_project="test-proj",
            source_table="test-proj.ds.identities",
            columns={
                "device_fp": "device_fingerprint_id",
                "ip": "ip_address",
                "email": "email",
            },
        )
        assert config.version == "1.0"


# ---------------------------------------------------------------------------
# Cross-preset checks
# ---------------------------------------------------------------------------


class TestAllPresetsRaiseOnNoneColumns:
    """Every preset must raise ConfigurationError when columns is None."""

    _PRESETS = [
        ("telecom_subscriber_preset", telecom_subscriber_preset),
        ("logistics_carrier_preset", logistics_carrier_preset),
        ("retail_customer_preset", retail_customer_preset),
        ("real_estate_property_preset", real_estate_property_preset),
        ("public_sector_preset", public_sector_preset),
        ("education_student_preset", education_student_preset),
        ("travel_guest_preset", travel_guest_preset),
        ("vendor_master_preset", vendor_master_preset),
        ("identity_fraud_preset", identity_fraud_preset),
    ]

    @pytest.mark.parametrize("name,fn", _PRESETS, ids=[p[0] for p in _PRESETS])
    def test_raises_when_columns_none(self, name, fn):
        with pytest.raises(ConfigurationError):
            fn(
                bq_project="test-proj",
                source_table="test-proj.ds.table",
                columns=None,
            )

    @pytest.mark.parametrize("name,fn", _PRESETS, ids=[p[0] for p in _PRESETS])
    def test_raises_when_columns_empty(self, name, fn):
        with pytest.raises(ConfigurationError):
            fn(
                bq_project="test-proj",
                source_table="test-proj.ds.table",
                columns={},
            )


class TestAllPresetsGenerateValidConfig:
    """Every preset should produce a PipelineConfig that passes Pydantic validation."""

    def _minimal_columns(self, preset_name):
        """Return minimal column dict for each preset."""
        # Each preset needs at least 1-2 roles to generate blocking keys + comparisons
        mapping = {
            "telecom": {"sub_id": "subscriber_id", "email": "email"},
            "logistics": {"duns": "duns_number", "company": "company_name"},
            "retail": {"loyalty": "loyalty_id", "email": "email"},
            "real_estate": {"parcel": "parcel_number", "mls": "mls_id"},
            "public_sector": {"passport_no": "passport", "dl": "license_number"},
            "education": {"student": "student_id", "email": "email"},
            "travel": {"guest": "guest_id", "booking": "booking_reference"},
            "vendor_master": {"vendor": "vendor_id", "company": "company_name"},
            "identity_fraud": {"device_fp": "device_fingerprint_id", "email": "email"},
        }
        return mapping[preset_name]

    def test_telecom_valid(self):
        config = telecom_subscriber_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("telecom"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_logistics_valid(self):
        config = logistics_carrier_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("logistics"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_retail_valid(self):
        config = retail_customer_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("retail"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_real_estate_valid(self):
        config = real_estate_property_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("real_estate"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_public_sector_valid(self):
        config = public_sector_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("public_sector"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_education_valid(self):
        config = education_student_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("education"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_travel_valid(self):
        config = travel_guest_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("travel"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_vendor_master_valid(self):
        config = vendor_master_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("vendor_master"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_identity_fraud_valid(self):
        config = identity_fraud_preset(
            bq_project="p", source_table="p.d.t",
            columns=self._minimal_columns("identity_fraud"),
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1


class TestPresetSourceConfig:
    """Verify that preset-generated configs have correct source configuration."""

    def test_source_table_set(self):
        config = telecom_subscriber_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.subscribers",
            columns={"sub_id": "subscriber_id", "email": "email"},
        )
        assert config.sources[0].table == "test-proj.raw.subscribers"

    def test_source_columns_mapped(self):
        config = logistics_carrier_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.carriers",
            columns={"duns_col": "duns_number", "name_col": "company_name"},
        )
        col_names = [c.name for c in config.sources[0].columns]
        assert "duns_col" in col_names
        assert "name_col" in col_names

    def test_source_column_roles(self):
        config = retail_customer_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.customers",
            columns={"loyalty_col": "loyalty_id", "email_col": "email"},
        )
        role_map = {c.name: c.role for c in config.sources[0].columns}
        assert role_map["loyalty_col"] == "loyalty_id"
        assert role_map["email_col"] == "email"

    def test_unique_key_defaults(self):
        config = education_student_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.students",
            columns={"sid": "student_id", "email": "email"},
        )
        assert config.sources[0].unique_key == "id"

    def test_custom_unique_key(self):
        config = travel_guest_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.guests",
            columns={"gid": "guest_id", "email": "email"},
            unique_key="guest_pk",
        )
        assert config.sources[0].unique_key == "guest_pk"

    def test_custom_updated_at(self):
        config = vendor_master_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.vendors",
            columns={"vid": "vendor_id", "company": "company_name"},
            updated_at="modified_ts",
        )
        assert config.sources[0].updated_at == "modified_ts"

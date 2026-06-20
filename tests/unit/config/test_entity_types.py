"""Tests for entity type templates, registry, and schema.org aliases."""
from __future__ import annotations

import pytest

from bq_entity_resolution.config.entity_types import (
    ENTITY_TYPE_TEMPLATES,
    DefaultSignal,
    EntityTypeTemplate,
    _resolved_cache,
    get_entity_type,
    list_entity_types,
    register_entity_type,
    resolve_hierarchy,
)
from bq_entity_resolution.config.roles import detect_role, roles_for_entity_type

# -- Registry Tests ----------------------------------------------------------


class TestRegistry:
    def test_builtin_types_registered(self):
        names = list_entity_types()
        assert "Person" in names
        assert "Organization" in names
        assert "Thing" in names

    def test_builtin_types(self):
        expected = {
            "Thing", "Person", "Organization", "PostalAddress",
            "InsuredEntity", "FinancialAccount", "Patient",
            "Subscriber", "ServiceLocation", "Carrier", "Property",
            "Vehicle", "Device", "Merchant", "Student", "Guest",
            "Claimant", "Vendor", "DigitalIdentity",
        }
        assert expected <= set(ENTITY_TYPE_TEMPLATES.keys())

    def test_list_entity_types_sorted(self):
        names = list_entity_types()
        assert names == sorted(names)

    def test_get_entity_type_exact(self):
        t = get_entity_type("Person")
        assert t.name == "Person"

    def test_get_entity_type_case_insensitive(self):
        t = get_entity_type("person")
        assert t.name == "Person"

    def test_get_entity_type_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown entity type"):
            get_entity_type("NonExistent")


class TestRegisterEntityType:
    def test_register_custom_type(self):
        custom = EntityTypeTemplate(
            name="_TestCustomVehicle",
            valid_roles=frozenset({"vin"}),
            description="Test vehicle type",
        )
        register_entity_type(custom)
        assert get_entity_type("_TestCustomVehicle").name == "_TestCustomVehicle"
        # Cleanup
        ENTITY_TYPE_TEMPLATES.pop("_TestCustomVehicle", None)
        _resolved_cache.clear()

    def test_register_overwrites_existing(self):
        original = get_entity_type("Person")
        modified = EntityTypeTemplate(
            name="Person",
            valid_roles=frozenset({"first_name"}),
            description="Modified for test",
        )
        register_entity_type(modified)
        assert get_entity_type("Person").description == "Modified for test"
        # Restore original
        register_entity_type(original)


# -- Template Structure Tests ------------------------------------------------


class TestPersonTemplate:
    def test_has_person_roles(self):
        t = get_entity_type("Person")
        assert "first_name" in t.valid_roles
        assert "last_name" in t.valid_roles
        assert "email" in t.valid_roles
        assert "phone" in t.valid_roles
        assert "date_of_birth" in t.valid_roles
        assert "ssn" in t.valid_roles

    def test_required_roles(self):
        t = get_entity_type("Person")
        assert "first_name" in t.required_roles
        assert "last_name" in t.required_roles

    def test_parent_is_thing(self):
        t = get_entity_type("Person")
        assert t.parent == "Thing"

    def test_schema_org_type(self):
        t = get_entity_type("Person")
        assert t.schema_org_type == "https://schema.org/Person"

    def test_schema_org_aliases(self):
        t = get_entity_type("Person")
        assert t.schema_org_aliases["givenName"] == "first_name"
        assert t.schema_org_aliases["familyName"] == "last_name"
        assert t.schema_org_aliases["telephone"] == "phone"
        assert t.schema_org_aliases["birthDate"] == "date_of_birth"


class TestOrganizationTemplate:
    def test_has_business_roles(self):
        t = get_entity_type("Organization")
        assert "company_name" in t.valid_roles
        assert "ein" in t.valid_roles

    def test_required_roles(self):
        t = get_entity_type("Organization")
        assert "company_name" in t.required_roles

    def test_schema_org_aliases(self):
        t = get_entity_type("Organization")
        assert t.schema_org_aliases["legalName"] == "company_name"
        assert t.schema_org_aliases["taxID"] == "ein"


class TestPostalAddressTemplate:
    def test_has_address_roles(self):
        t = get_entity_type("PostalAddress")
        assert t.valid_roles == frozenset({
            "address_line_1", "city", "state", "zip_code",
        })

    def test_no_parent(self):
        t = get_entity_type("PostalAddress")
        assert t.parent is None

    def test_schema_org_aliases(self):
        t = get_entity_type("PostalAddress")
        assert t.schema_org_aliases["streetAddress"] == "address_line_1"
        assert t.schema_org_aliases["postalCode"] == "zip_code"


class TestDomainTemplates:
    def test_insured_entity_extends_person(self):
        t = get_entity_type("InsuredEntity")
        assert t.parent == "Person"
        assert "policy_number" in t.valid_roles
        assert "claim_number" in t.valid_roles

    def test_financial_account_extends_person(self):
        t = get_entity_type("FinancialAccount")
        assert t.parent == "Person"
        assert "account_number" in t.valid_roles

    def test_patient_extends_person(self):
        t = get_entity_type("Patient")
        assert t.parent == "Person"
        assert "mrn" in t.valid_roles
        assert "npi" in t.valid_roles


# -- Hierarchy Resolution Tests ----------------------------------------------


class TestResolveHierarchy:
    def test_thing_resolves_to_self(self):
        resolved = resolve_hierarchy("Thing")
        assert resolved.name == "Thing"
        assert "full_name" in resolved.valid_roles

    def test_person_inherits_thing_roles(self):
        resolved = resolve_hierarchy("Person")
        # Person has its own roles
        assert "first_name" in resolved.valid_roles
        # Plus Thing's roles
        assert "full_name" in resolved.valid_roles

    def test_patient_inherits_full_chain(self):
        resolved = resolve_hierarchy("Patient")
        # Patient's own roles
        assert "mrn" in resolved.valid_roles
        assert "npi" in resolved.valid_roles
        # Person's roles
        assert "first_name" in resolved.valid_roles
        assert "email" in resolved.valid_roles
        # Thing's roles
        assert "full_name" in resolved.valid_roles

    def test_schema_org_aliases_merge(self):
        resolved = resolve_hierarchy("Person")
        # Person's aliases
        assert "givenName" in resolved.schema_org_aliases
        # Thing's aliases
        assert "name" in resolved.schema_org_aliases

    def test_child_aliases_override_parent(self):
        """When both parent and child define an alias, child wins."""
        parent = EntityTypeTemplate(
            name="_TestParent",
            schema_org_aliases={"taxID": "ssn"},
        )
        child = EntityTypeTemplate(
            name="_TestChild",
            parent="_TestParent",
            schema_org_aliases={"taxID": "ein"},
        )
        register_entity_type(parent)
        register_entity_type(child)
        resolved = resolve_hierarchy("_TestChild")
        assert resolved.schema_org_aliases["taxID"] == "ein"
        # Cleanup
        ENTITY_TYPE_TEMPLATES.pop("_TestParent", None)
        ENTITY_TYPE_TEMPLATES.pop("_TestChild", None)
        _resolved_cache.clear()

    def test_insured_entity_has_person_plus_insurance(self):
        resolved = resolve_hierarchy("InsuredEntity")
        # Insurance-specific
        assert "policy_number" in resolved.valid_roles
        assert "claim_number" in resolved.valid_roles
        # Person-inherited
        assert "first_name" in resolved.valid_roles
        assert "date_of_birth" in resolved.valid_roles

    def test_caching(self):
        """resolve_hierarchy caches results for performance."""
        _resolved_cache.clear()
        resolve_hierarchy("Person")
        assert "Person" in _resolved_cache
        # Second call should use cache
        result = resolve_hierarchy("Person")
        assert result.name == "Person"


# -- DefaultSignal Tests -----------------------------------------------------


class TestDefaultSignal:
    def test_frozen(self):
        s = DefaultSignal(
            kind="hard_negative",
            left="test_col",
            method="different",
            category="test",
        )
        with pytest.raises(AttributeError):
            s.left = "other"

    def test_default_values(self):
        s = DefaultSignal(
            kind="soft_signal",
            left="test_col",
            method="exact",
            category="test",
        )
        assert s.action == "disqualify"
        assert s.severity == "hn2_structural"
        assert s.value == 0.0


# -- EntityTypeTemplate Tests ------------------------------------------------


class TestEntityTypeTemplate:
    def test_frozen(self):
        t = EntityTypeTemplate(name="Test")
        with pytest.raises(AttributeError):
            t.name = "Other"

    def test_defaults(self):
        t = EntityTypeTemplate(name="Test")
        assert t.valid_roles == frozenset()
        assert t.required_roles == frozenset()
        assert t.parent is None
        assert t.schema_org_type == ""
        assert t.schema_org_aliases == {}
        assert t.default_signals == ()
        assert t.default_link_type == "dedupe_only"
        assert t.description == ""


# -- Schema.org Alias Tests --------------------------------------------------


class TestSchemaOrgAliases:
    """Tests for schema.org property name aliases in detect_role()."""

    def test_givenname_maps_to_first_name(self):
        assert detect_role("givenname") == "first_name"

    def test_given_name_camel_case(self):
        # camelCase is lowered by detect_role()
        assert detect_role("givenName") == "first_name"

    def test_familyname_maps_to_last_name(self):
        assert detect_role("familyname") == "last_name"

    def test_telephone_maps_to_phone(self):
        assert detect_role("telephone") == "phone"

    def test_birthdate_maps_to_dob(self):
        assert detect_role("birthdate") == "date_of_birth"

    def test_legalname_maps_to_company_name(self):
        assert detect_role("legalname") == "company_name"

    def test_postalcode_maps_to_zip_code(self):
        assert detect_role("postalcode") == "zip_code"

    def test_streetaddress_maps_to_address_line_1(self):
        assert detect_role("streetaddress") == "address_line_1"

    def test_addresslocality_maps_to_city(self):
        assert detect_role("addresslocality") == "city"

    def test_addressregion_maps_to_state(self):
        assert detect_role("addressregion") == "state"

    def test_taxid_maps_to_ein(self):
        assert detect_role("taxid") == "ein"

    def test_existing_patterns_still_work(self):
        """Schema.org aliases don't break existing pattern detection."""
        assert detect_role("first_name") == "first_name"
        assert detect_role("last_name") == "last_name"
        assert detect_role("email") == "email"
        assert detect_role("phone") == "phone"


# -- roles_for_entity_type Tests --------------------------------------------


class TestRolesForEntityType:
    def test_person_returns_person_roles(self):
        roles = roles_for_entity_type("Person")
        assert "first_name" in roles
        assert "last_name" in roles
        assert "email" in roles

    def test_unknown_type_returns_all_roles(self):
        roles = roles_for_entity_type("NonExistent")
        # Falls back to all ROLE_FEATURES keys
        assert "first_name" in roles
        assert "company_name" in roles

    def test_patient_includes_inherited_roles(self):
        roles = roles_for_entity_type("Patient")
        # Patient's own
        assert "mrn" in roles
        # Inherited from Person
        assert "first_name" in roles


# -- New Cross-Industry Entity Type Tests -----------------------------------


class TestNewEntityTypes:
    """Tests for the 12 new cross-industry entity type templates."""

    # -- Registration checks -------------------------------------------------

    _NEW_TYPES = [
        "Subscriber", "ServiceLocation", "Carrier", "Property",
        "Vehicle", "Device", "Merchant", "Student", "Guest",
        "Claimant", "Vendor", "DigitalIdentity",
    ]

    def test_all_new_types_registered(self):
        """Every new entity type should be in the global registry."""
        registered = set(ENTITY_TYPE_TEMPLATES.keys())
        for name in self._NEW_TYPES:
            assert name in registered, f"{name} not registered"

    def test_get_entity_type_for_all_new_types(self):
        for name in self._NEW_TYPES:
            t = get_entity_type(name)
            assert t.name == name

    def test_case_insensitive_lookup_for_new_types(self):
        for name in self._NEW_TYPES:
            t = get_entity_type(name.lower())
            assert t.name == name

    # -- Parent inheritance checks -------------------------------------------

    def test_subscriber_extends_person(self):
        t = get_entity_type("Subscriber")
        assert t.parent == "Person"

    def test_service_location_extends_postal_address(self):
        t = get_entity_type("ServiceLocation")
        assert t.parent == "PostalAddress"

    def test_carrier_extends_organization(self):
        t = get_entity_type("Carrier")
        assert t.parent == "Organization"

    def test_property_extends_postal_address(self):
        t = get_entity_type("Property")
        assert t.parent == "PostalAddress"

    def test_vehicle_extends_thing(self):
        t = get_entity_type("Vehicle")
        assert t.parent == "Thing"

    def test_device_extends_thing(self):
        t = get_entity_type("Device")
        assert t.parent == "Thing"

    def test_merchant_extends_organization(self):
        t = get_entity_type("Merchant")
        assert t.parent == "Organization"

    def test_student_extends_person(self):
        t = get_entity_type("Student")
        assert t.parent == "Person"

    def test_guest_extends_person(self):
        t = get_entity_type("Guest")
        assert t.parent == "Person"

    def test_claimant_extends_person(self):
        t = get_entity_type("Claimant")
        assert t.parent == "Person"

    def test_vendor_extends_organization(self):
        t = get_entity_type("Vendor")
        assert t.parent == "Organization"

    def test_digital_identity_extends_person(self):
        t = get_entity_type("DigitalIdentity")
        assert t.parent == "Person"

    # -- resolve_hierarchy merges roles correctly ----------------------------

    def test_subscriber_inherits_person_and_thing_roles(self):
        resolved = resolve_hierarchy("Subscriber")
        # Subscriber's own telecom roles
        assert "subscriber_id" in resolved.valid_roles
        assert "imsi" in resolved.valid_roles
        assert "msisdn" in resolved.valid_roles
        # Inherited from Person
        assert "first_name" in resolved.valid_roles
        assert "email" in resolved.valid_roles
        # Inherited from Thing via Person
        assert "full_name" in resolved.valid_roles

    def test_carrier_inherits_organization_and_thing_roles(self):
        resolved = resolve_hierarchy("Carrier")
        # Carrier's own logistics roles
        assert "duns_number" in resolved.valid_roles
        assert "carrier_scac" in resolved.valid_roles
        assert "mc_dot_number" in resolved.valid_roles
        # Inherited from Organization
        assert "company_name" in resolved.valid_roles
        assert "ein" in resolved.valid_roles
        # Inherited from Thing via Organization
        assert "full_name" in resolved.valid_roles

    def test_property_inherits_postal_address_roles(self):
        resolved = resolve_hierarchy("Property")
        # Property's own roles
        assert "parcel_number" in resolved.valid_roles
        assert "mls_id" in resolved.valid_roles
        # Inherited from PostalAddress
        assert "address_line_1" in resolved.valid_roles
        assert "city" in resolved.valid_roles
        assert "state" in resolved.valid_roles
        assert "zip_code" in resolved.valid_roles

    def test_service_location_inherits_postal_address_roles(self):
        resolved = resolve_hierarchy("ServiceLocation")
        assert "service_point_id" in resolved.valid_roles
        assert "meter_id" in resolved.valid_roles
        # From PostalAddress
        assert "address_line_1" in resolved.valid_roles
        assert "zip_code" in resolved.valid_roles

    def test_vehicle_inherits_thing_roles(self):
        resolved = resolve_hierarchy("Vehicle")
        assert "vin" in resolved.valid_roles
        assert "full_name" in resolved.valid_roles  # from Thing

    def test_device_inherits_thing_roles(self):
        resolved = resolve_hierarchy("Device")
        assert "serial_number" in resolved.valid_roles
        assert "mac_address" in resolved.valid_roles
        assert "full_name" in resolved.valid_roles  # from Thing

    def test_merchant_inherits_organization_roles(self):
        resolved = resolve_hierarchy("Merchant")
        # Merchant's own retail roles
        assert "loyalty_id" in resolved.valid_roles
        assert "customer_id" in resolved.valid_roles
        # Inherited from Organization
        assert "company_name" in resolved.valid_roles
        assert "ein" in resolved.valid_roles
        # From Thing
        assert "full_name" in resolved.valid_roles

    def test_student_inherits_person_roles(self):
        resolved = resolve_hierarchy("Student")
        assert "student_id" in resolved.valid_roles
        assert "enrollment_id" in resolved.valid_roles
        # From Person
        assert "first_name" in resolved.valid_roles
        assert "date_of_birth" in resolved.valid_roles
        # From Thing
        assert "full_name" in resolved.valid_roles

    def test_guest_inherits_person_roles(self):
        resolved = resolve_hierarchy("Guest")
        assert "guest_id" in resolved.valid_roles
        assert "booking_reference" in resolved.valid_roles
        assert "frequent_flyer_number" in resolved.valid_roles
        # From Person
        assert "first_name" in resolved.valid_roles
        assert "email" in resolved.valid_roles

    def test_claimant_inherits_person_roles(self):
        resolved = resolve_hierarchy("Claimant")
        # Claimant has insurance + public sector roles
        assert "passport" in resolved.valid_roles
        assert "case_number" in resolved.valid_roles
        assert "policy_number" in resolved.valid_roles
        # From Person
        assert "first_name" in resolved.valid_roles
        assert "ssn" in resolved.valid_roles

    def test_vendor_inherits_organization_roles(self):
        resolved = resolve_hierarchy("Vendor")
        assert "vendor_id" in resolved.valid_roles
        assert "cage_code" in resolved.valid_roles
        assert "sam_uei" in resolved.valid_roles
        # From Organization
        assert "company_name" in resolved.valid_roles
        assert "ein" in resolved.valid_roles

    def test_digital_identity_inherits_person_roles(self):
        resolved = resolve_hierarchy("DigitalIdentity")
        assert "device_fingerprint_id" in resolved.valid_roles
        assert "ip_address" in resolved.valid_roles
        # From Person
        assert "first_name" in resolved.valid_roles
        assert "email" in resolved.valid_roles
        assert "ssn" in resolved.valid_roles

    # -- Required roles checks -----------------------------------------------

    def test_subscriber_required_roles(self):
        t = get_entity_type("Subscriber")
        assert "subscriber_id" in t.required_roles

    def test_carrier_required_roles(self):
        t = get_entity_type("Carrier")
        assert "company_name" in t.required_roles

    def test_property_required_roles(self):
        t = get_entity_type("Property")
        assert "address_line_1" in t.required_roles

    def test_vehicle_required_roles(self):
        t = get_entity_type("Vehicle")
        assert "vin" in t.required_roles

    def test_device_required_roles(self):
        t = get_entity_type("Device")
        assert "serial_number" in t.required_roles

    def test_merchant_required_roles(self):
        t = get_entity_type("Merchant")
        assert "company_name" in t.required_roles

    def test_student_required_roles(self):
        t = get_entity_type("Student")
        assert "student_id" in t.required_roles

    def test_vendor_required_roles(self):
        t = get_entity_type("Vendor")
        assert "company_name" in t.required_roles

    def test_digital_identity_required_roles(self):
        t = get_entity_type("DigitalIdentity")
        assert "email" in t.required_roles

    def test_service_location_required_roles(self):
        t = get_entity_type("ServiceLocation")
        assert "address_line_1" in t.required_roles

    # -- Default link type checks --------------------------------------------

    def test_subscriber_link_type(self):
        t = get_entity_type("Subscriber")
        assert t.default_link_type == "link_and_dedupe"

    def test_carrier_link_type(self):
        t = get_entity_type("Carrier")
        assert t.default_link_type == "link_and_dedupe"

    def test_property_link_type(self):
        t = get_entity_type("Property")
        assert t.default_link_type == "dedupe_only"

    def test_vehicle_link_type(self):
        t = get_entity_type("Vehicle")
        assert t.default_link_type == "dedupe_only"

    def test_device_link_type(self):
        t = get_entity_type("Device")
        assert t.default_link_type == "dedupe_only"

    def test_merchant_link_type(self):
        t = get_entity_type("Merchant")
        assert t.default_link_type == "link_and_dedupe"

    def test_student_link_type(self):
        t = get_entity_type("Student")
        assert t.default_link_type == "dedupe_only"

    def test_guest_link_type(self):
        t = get_entity_type("Guest")
        assert t.default_link_type == "link_and_dedupe"

    def test_claimant_link_type(self):
        t = get_entity_type("Claimant")
        assert t.default_link_type == "dedupe_only"

    def test_vendor_link_type(self):
        t = get_entity_type("Vendor")
        assert t.default_link_type == "link_and_dedupe"

    def test_digital_identity_link_type(self):
        t = get_entity_type("DigitalIdentity")
        assert t.default_link_type == "link_and_dedupe"

    # -- Vehicle schema.org alias check --------------------------------------

    def test_vehicle_schema_org_alias(self):
        t = get_entity_type("Vehicle")
        assert t.schema_org_aliases.get("vehicleIdentificationNumber") == "vin"

    def test_vehicle_schema_org_type(self):
        t = get_entity_type("Vehicle")
        assert t.schema_org_type == "https://schema.org/Vehicle"

    # -- roles_for_entity_type with new types --------------------------------

    def test_roles_for_subscriber(self):
        roles = roles_for_entity_type("Subscriber")
        assert "subscriber_id" in roles
        assert "first_name" in roles  # inherited

    def test_roles_for_carrier(self):
        roles = roles_for_entity_type("Carrier")
        assert "duns_number" in roles
        assert "company_name" in roles  # inherited

    def test_roles_for_device(self):
        roles = roles_for_entity_type("Device")
        assert "serial_number" in roles
        assert "mac_address" in roles

    def test_roles_for_vendor(self):
        roles = roles_for_entity_type("Vendor")
        assert "vendor_id" in roles
        assert "cage_code" in roles
        assert "sam_uei" in roles

    def test_roles_for_digital_identity(self):
        roles = roles_for_entity_type("DigitalIdentity")
        assert "ip_address" in roles
        assert "device_fingerprint_id" in roles
        assert "email" in roles  # inherited from Person

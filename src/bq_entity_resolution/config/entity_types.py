"""Entity type templates: schema.org-inspired type system for entity resolution.

Entity type templates provide named bundles of valid roles, required roles,
schema.org vocabulary mappings, and default signals. This enables:

1. Progressive disclosure: ``entity_type: Person`` auto-configures everything
2. Validation: warn when required roles are missing
3. Extensibility: define custom entity types in YAML
4. Interoperability: schema.org property names auto-map to internal roles

Built-in templates are aligned with schema.org types but use the internal
role vocabulary (first_name, last_name, etc.) for backward compatibility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from bq_entity_resolution.config.roles import (
    BUSINESS_ROLES,
    EDUCATION_ROLES,
    FINANCIAL_ROLES,
    HEALTHCARE_ROLES,
    IDENTITY_FRAUD_ROLES,
    INSURANCE_ROLES,
    LOGISTICS_ROLES,
    MANUFACTURING_ROLES,
    PERSON_ROLES,
    PUBLIC_SECTOR_ROLES,
    REAL_ESTATE_ROLES,
    RETAIL_ROLES,
    TELECOM_ROLES,
    TRAVEL_ROLES,
    VENDOR_MASTER_ROLES,
)

__all__ = [
    "DefaultSignal",
    "EntityTypeTemplate",
    "ENTITY_TYPE_TEMPLATES",
    "get_entity_type",
    "list_entity_types",
    "register_entity_type",
    "resolve_hierarchy",
]


@dataclass(frozen=True)
class DefaultSignal:
    """A default signal auto-injected when an entity type is declared.

    Used by entity type templates to define signals that are appropriate
    for the entity type. Signals are only injected if the referenced
    feature column exists in the pipeline's feature engineering config.
    """

    kind: Literal["hard_negative", "soft_signal"]
    left: str
    method: str
    action: str = "disqualify"
    severity: str = "hn2_structural"
    value: float = 0.0
    category: str = "general"


@dataclass(frozen=True)
class EntityTypeTemplate:
    """Named entity type with valid roles, defaults, and schema.org mapping.

    Templates follow a hierarchy (e.g., Person < Thing) where child types
    inherit valid roles from their parents. Use ``resolve_hierarchy()``
    to get the fully-resolved template with inherited roles.

    Attributes:
        name: Display name (e.g., "Person", "Organization").
        valid_roles: Roles that are semantically valid for this entity type.
        required_roles: Roles that should be present; a warning is issued
            if any are missing (not an error).
        parent: Parent template name for inheritance, or None.
        schema_org_type: Corresponding schema.org type name.
        schema_org_aliases: Mapping of schema.org property names to
            internal role names (e.g., ``{"givenName": "first_name"}``).
        default_signals: Signals auto-injected when this type is declared.
        default_link_type: Default link type for presets using this template.
        description: Human-readable description.
    """

    name: str
    valid_roles: frozenset[str] = field(default_factory=frozenset)
    required_roles: frozenset[str] = field(default_factory=frozenset)
    parent: str | None = None
    schema_org_type: str = ""
    schema_org_aliases: dict[str, str] = field(default_factory=dict)
    default_signals: tuple[DefaultSignal, ...] = ()
    default_link_type: str = "dedupe_only"
    description: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ENTITY_TYPE_TEMPLATES: dict[str, EntityTypeTemplate] = {}

# Cache for resolved hierarchies (cleared on registration)
_resolved_cache: dict[str, EntityTypeTemplate] = {}

# Track built-in type names so we can warn when user code overwrites them
_BUILTIN_TYPE_NAMES: set[str] = set()

_logger = logging.getLogger(__name__)


def register_entity_type(template: EntityTypeTemplate) -> None:
    """Register an entity type template.

    Overwrites any existing template with the same name (case-insensitive).
    Logs a warning if overwriting a built-in type.
    """
    if (
        template.name in _BUILTIN_TYPE_NAMES
        and template.name in ENTITY_TYPE_TEMPLATES
    ):
        _logger.warning(
            "Overwriting built-in entity type '%s' with a custom definition. "
            "This is allowed but may change default behavior for configs "
            "referencing this type.",
            template.name,
        )
    ENTITY_TYPE_TEMPLATES[template.name] = template
    _resolved_cache.clear()


def get_entity_type(name: str) -> EntityTypeTemplate:
    """Get a template by name (case-insensitive).

    Raises KeyError if not found.
    """
    # Exact match first
    if name in ENTITY_TYPE_TEMPLATES:
        return ENTITY_TYPE_TEMPLATES[name]
    # Case-insensitive fallback
    lower = name.lower()
    for key, template in ENTITY_TYPE_TEMPLATES.items():
        if key.lower() == lower:
            return template
    raise KeyError(f"Unknown entity type: {name!r}. Available: {sorted(ENTITY_TYPE_TEMPLATES)}")


def resolve_hierarchy(name: str) -> EntityTypeTemplate:
    """Resolve a template with inherited roles from the full parent chain.

    Returns a new ``EntityTypeTemplate`` whose ``valid_roles`` is the union
    of all roles up the inheritance chain, and whose ``schema_org_aliases``
    is merged (child overrides parent).
    """
    if name in _resolved_cache:
        return _resolved_cache[name]

    template = get_entity_type(name)

    if template.parent is None:
        _resolved_cache[name] = template
        return template

    parent = resolve_hierarchy(template.parent)

    merged_roles = template.valid_roles | parent.valid_roles
    merged_aliases = {**parent.schema_org_aliases, **template.schema_org_aliases}
    merged_signals = parent.default_signals + template.default_signals

    resolved = EntityTypeTemplate(
        name=template.name,
        valid_roles=merged_roles,
        required_roles=template.required_roles,
        parent=template.parent,
        schema_org_type=template.schema_org_type,
        schema_org_aliases=merged_aliases,
        default_signals=merged_signals,
        default_link_type=template.default_link_type,
        description=template.description,
    )
    _resolved_cache[name] = resolved
    return resolved


def list_entity_types() -> list[str]:
    """List all registered entity type names in alphabetical order."""
    return sorted(ENTITY_TYPE_TEMPLATES.keys())


# ---------------------------------------------------------------------------
# Built-in entity type templates (aligned with schema.org vocabulary)
# ---------------------------------------------------------------------------

_THING = EntityTypeTemplate(
    name="Thing",
    valid_roles=frozenset({"full_name"}),
    required_roles=frozenset(),
    parent=None,
    schema_org_type="https://schema.org/Thing",
    schema_org_aliases={"name": "full_name"},
    description="Base entity type (schema.org/Thing). All types inherit from this.",
)

_PERSON = EntityTypeTemplate(
    name="Person",
    valid_roles=PERSON_ROLES,
    required_roles=frozenset({"first_name", "last_name"}),
    parent="Thing",
    schema_org_type="https://schema.org/Person",
    schema_org_aliases={
        "givenName": "first_name",
        "familyName": "last_name",
        "email": "email",
        "telephone": "phone",
        "birthDate": "date_of_birth",
        "taxID": "ssn",
    },
    default_link_type="dedupe_only",
    description="A person (schema.org/Person). Core attributes: name, DOB, contact info.",
)

_ORGANIZATION = EntityTypeTemplate(
    name="Organization",
    valid_roles=BUSINESS_ROLES,
    required_roles=frozenset({"company_name"}),
    parent="Thing",
    schema_org_type="https://schema.org/Organization",
    schema_org_aliases={
        "legalName": "company_name",
        "taxID": "ein",
        "telephone": "phone",
        "email": "email",
    },
    default_link_type="dedupe_only",
    description="A business or organization (schema.org/Organization).",
)

_POSTAL_ADDRESS = EntityTypeTemplate(
    name="PostalAddress",
    valid_roles=frozenset({"address_line_1", "city", "state", "zip_code"}),
    required_roles=frozenset(),
    parent=None,
    schema_org_type="https://schema.org/PostalAddress",
    schema_org_aliases={
        "streetAddress": "address_line_1",
        "addressLocality": "city",
        "addressRegion": "state",
        "postalCode": "zip_code",
    },
    description="A postal address (schema.org/PostalAddress). Utility type for composition.",
)

_INSURED_ENTITY = EntityTypeTemplate(
    name="InsuredEntity",
    valid_roles=INSURANCE_ROLES,
    required_roles=frozenset({"policy_number"}),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="An insured entity. Extends Person with policy/claim attributes.",
)

_FINANCIAL_ACCOUNT = EntityTypeTemplate(
    name="FinancialAccount",
    valid_roles=FINANCIAL_ROLES,
    required_roles=frozenset({"account_number"}),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A financial account holder. Extends Person with account attributes.",
)

_PATIENT = EntityTypeTemplate(
    name="Patient",
    valid_roles=HEALTHCARE_ROLES,
    required_roles=frozenset({"mrn"}),
    parent="Person",
    schema_org_type="https://schema.org/Patient",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="A healthcare patient. Extends Person with NPI/MRN.",
)

_SUBSCRIBER = EntityTypeTemplate(
    name="Subscriber",
    valid_roles=TELECOM_ROLES,
    required_roles=frozenset({"subscriber_id"}),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A telecom/utility subscriber. Extends Person with service identifiers.",
)

_SERVICE_LOCATION = EntityTypeTemplate(
    name="ServiceLocation",
    valid_roles=frozenset({
        "service_point_id", "meter_id", "circuit_id",
        "address_line_1", "city", "state", "zip_code",
    }),
    required_roles=frozenset({"address_line_1"}),
    parent="PostalAddress",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="A utility service location. Extends PostalAddress with meter/service IDs.",
)

_CARRIER = EntityTypeTemplate(
    name="Carrier",
    valid_roles=LOGISTICS_ROLES,
    required_roles=frozenset({"company_name"}),
    parent="Organization",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A logistics carrier/shipper. Extends Organization with SCAC, MC/DOT, DUNS.",
)

_PROPERTY = EntityTypeTemplate(
    name="Property",
    valid_roles=REAL_ESTATE_ROLES,
    required_roles=frozenset({"address_line_1"}),
    parent="PostalAddress",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="A real estate property. Extends PostalAddress with parcel/MLS identifiers.",
)

_VEHICLE = EntityTypeTemplate(
    name="Vehicle",
    valid_roles=frozenset({"vin", "license_number", "full_name", "company_name"}),
    required_roles=frozenset({"vin"}),
    parent="Thing",
    schema_org_type="https://schema.org/Vehicle",
    schema_org_aliases={"vehicleIdentificationNumber": "vin"},
    default_link_type="dedupe_only",
    description="A vehicle identified by VIN (schema.org/Vehicle).",
)

_DEVICE = EntityTypeTemplate(
    name="Device",
    valid_roles=MANUFACTURING_ROLES,
    required_roles=frozenset({"serial_number"}),
    parent="Thing",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="An IoT device or manufactured asset. Identified by serial/MAC/asset tag.",
)

_MERCHANT = EntityTypeTemplate(
    name="Merchant",
    valid_roles=RETAIL_ROLES | BUSINESS_ROLES,
    required_roles=frozenset({"company_name"}),
    parent="Organization",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A retail merchant. Extends Organization with loyalty/payment identifiers.",
)

_STUDENT = EntityTypeTemplate(
    name="Student",
    valid_roles=EDUCATION_ROLES,
    required_roles=frozenset({"student_id"}),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="A student. Extends Person with student/enrollment/institution identifiers.",
)

_GUEST = EntityTypeTemplate(
    name="Guest",
    valid_roles=TRAVEL_ROLES,
    required_roles=frozenset(),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A travel/hospitality guest. Extends Person with booking/loyalty identifiers.",
)

_CLAIMANT = EntityTypeTemplate(
    name="Claimant",
    valid_roles=INSURANCE_ROLES | PUBLIC_SECTOR_ROLES,
    required_roles=frozenset(),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="dedupe_only",
    description="A claimant/applicant. Extends Person with claim/case/license identifiers.",
)

_VENDOR = EntityTypeTemplate(
    name="Vendor",
    valid_roles=VENDOR_MASTER_ROLES,
    required_roles=frozenset({"company_name"}),
    parent="Organization",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A vendor/supplier. Extends Organization with DUNS, CAGE, SAM UEI.",
)

_DIGITAL_IDENTITY = EntityTypeTemplate(
    name="DigitalIdentity",
    valid_roles=IDENTITY_FRAUD_ROLES,
    required_roles=frozenset({"email"}),
    parent="Person",
    schema_org_type="",
    schema_org_aliases={},
    default_link_type="link_and_dedupe",
    description="A digital identity for fraud detection. Extends Person with device/IP signals.",
)

# Register all built-in types
for _tmpl in [
    _THING,
    _PERSON,
    _ORGANIZATION,
    _POSTAL_ADDRESS,
    _INSURED_ENTITY,
    _FINANCIAL_ACCOUNT,
    _PATIENT,
    _SUBSCRIBER,
    _SERVICE_LOCATION,
    _CARRIER,
    _PROPERTY,
    _VEHICLE,
    _DEVICE,
    _MERCHANT,
    _STUDENT,
    _GUEST,
    _CLAIMANT,
    _VENDOR,
    _DIGITAL_IDENTITY,
]:
    register_entity_type(_tmpl)

# Snapshot built-in names after initial registration so that
# register_entity_type() can warn when user code overwrites them.
_BUILTIN_TYPE_NAMES.update(ENTITY_TYPE_TEMPLATES.keys())

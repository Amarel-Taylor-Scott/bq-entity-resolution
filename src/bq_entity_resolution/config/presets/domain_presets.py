"""Domain-specific presets for common entity resolution use cases.

Each function takes minimal inputs and returns a full PipelineConfig
using the entity type template system for role validation.
"""

from __future__ import annotations

from bq_entity_resolution.config.presets.helpers import (
    _build_default_tiers,
    _generate_from_roles,
    _preset_from_entity_type,
)
from bq_entity_resolution.config.schema import (
    ColumnMapping,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
)
from bq_entity_resolution.exceptions import ConfigurationError


def person_dedup_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "person_dedup",
) -> PipelineConfig:
    """Preset for person deduplication.

    Auto-generates features for person attributes: name, DOB, email,
    phone, address. Creates two tiers: exact (deterministic) and
    fuzzy (probabilistic with Jaro-Winkler).

    Args:
        bq_project: GCP project ID.
        source_table: Source table with person records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            first_name, last_name, date_of_birth, email, phone,
            address_line_1, city, state, zip_code, ssn.
        project_name: Project name for dataset naming.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: first_name, last_name, date_of_birth, "
            "email, phone, address_line_1, city, state, zip_code, ssn"
        )

    return _preset_from_entity_type(
        "Person", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def person_linkage_preset(
    bq_project: str,
    source_tables: list[dict[str, str]],
    columns: dict[str, str],
    unique_key: str = "id",
    updated_at: str = "updated_at",
    project_name: str = "person_linkage",
) -> PipelineConfig:
    """Preset for person record linkage across multiple sources.

    Args:
        bq_project: GCP project ID.
        source_tables: List of source table dicts, each with:
            {"name": "crm", "table": "proj.ds.table"}
        columns: {column_name: role} mapping (shared across sources).
        unique_key: Primary key column (same in all sources).
        updated_at: Timestamp column (same in all sources).
        project_name: Project name.
    """
    if not source_tables or len(source_tables) < 2:
        raise ConfigurationError("At least 2 source tables required for linkage")

    # Build column mappings
    col_mappings = [
        ColumnMapping(name=col, role=role)
        for col, role in columns.items()
    ]

    # Build sources
    sources = []
    for st in source_tables:
        sources.append(SourceConfig(
            name=st["name"],
            table=st["table"],
            unique_key=unique_key,
            updated_at=updated_at,
            columns=col_mappings,
        ))

    # Generate features, blocking, comparison pool from roles
    features, blocking_keys, comparison_pool = _generate_from_roles(columns)

    # Build tiers (using pool references)
    blocking_key_names = [bk.name for bk in blocking_keys]
    tiers = _build_default_tiers(blocking_key_names, comparison_pool)

    return PipelineConfig(
        project=ProjectConfig(name=project_name, bq_project=bq_project),
        sources=sources,
        feature_engineering=FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(features=features),
            blocking_keys=blocking_keys,
        ),
        comparison_pool=comparison_pool,
        matching_tiers=tiers,
        link_type="link_only",
    )


def insurance_dedup_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "insurance_dedup",
) -> PipelineConfig:
    """Preset for insurance entity resolution (claims, policies).

    Auto-generates features for insurance attributes: policy number,
    claim number, insured name, DOB, address, phone, SSN.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with insurance records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            policy_number, claim_number, first_name, last_name,
            date_of_birth, date_of_loss, address_line_1, city,
            state, zip_code, phone, email, ssn.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: policy_number, claim_number, first_name, "
            "last_name, date_of_birth, date_of_loss, ssn, phone, email"
        )

    return _preset_from_entity_type(
        "InsuredEntity", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def financial_transaction_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "financial_txn_match",
) -> PipelineConfig:
    """Preset for financial transaction matching.

    Auto-generates features for financial attributes: account number,
    routing number, transaction amount/date, customer name.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with transaction records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            account_number, routing_number, transaction_amount,
            transaction_date, first_name, last_name, email, phone.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: account_number, routing_number, "
            "transaction_amount, transaction_date, first_name, last_name"
        )

    return _preset_from_entity_type(
        "FinancialAccount", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )


def healthcare_patient_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "patient_match",
) -> PipelineConfig:
    """Preset for healthcare patient matching.

    Auto-generates features for healthcare attributes: NPI, MRN,
    patient name, DOB, address, phone, SSN.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with patient records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            npi, mrn, first_name, last_name, date_of_birth,
            address_line_1, city, state, zip_code, phone, email, ssn.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: npi, mrn, first_name, last_name, "
            "date_of_birth, address_line_1, city, state, zip_code, "
            "phone, email, ssn"
        )

    return _preset_from_entity_type(
        "Patient", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def business_dedup_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "business_dedup",
) -> PipelineConfig:
    """Preset for business/company deduplication.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with business records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            company_name, ein, address_line_1, city, state,
            zip_code, phone, email.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: company_name, ein, address_line_1, "
            "city, state, zip_code, phone, email"
        )

    return _preset_from_entity_type(
        "Organization", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def telecom_subscriber_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "telecom_subscriber_match",
) -> PipelineConfig:
    """Preset for telecom/utility subscriber matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with subscriber records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            subscriber_id, imsi, imei, msisdn, service_point_id,
            meter_id, first_name, last_name, address_line_1,
            city, state, zip_code, phone, email.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: subscriber_id, imsi, imei, msisdn, "
            "service_point_id, meter_id, first_name, last_name, phone, email"
        )

    return _preset_from_entity_type(
        "Subscriber", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )


def logistics_carrier_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "logistics_carrier_match",
) -> PipelineConfig:
    """Preset for logistics carrier/shipper matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with carrier records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            duns_number, mc_dot_number, carrier_scac, company_name,
            ein, address_line_1, city, state, zip_code, phone, email.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: duns_number, mc_dot_number, carrier_scac, "
            "company_name, ein, address_line_1, city, state, zip_code"
        )

    return _preset_from_entity_type(
        "Carrier", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )


def retail_customer_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "retail_customer_match",
) -> PipelineConfig:
    """Preset for retail/e-commerce customer matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with customer records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            loyalty_id, customer_id, first_name, last_name,
            email, phone, address_line_1, city, state, zip_code,
            device_fingerprint_id, payment_token_id.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: loyalty_id, customer_id, first_name, "
            "last_name, email, phone, address_line_1, city, state, zip_code"
        )

    return _preset_from_entity_type(
        "Merchant", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )


def real_estate_property_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "property_match",
) -> PipelineConfig:
    """Preset for real estate property matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with property records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            parcel_number, mls_id, deed_reference, address_line_1,
            city, state, zip_code, full_name, company_name.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: parcel_number, mls_id, deed_reference, "
            "address_line_1, city, state, zip_code"
        )

    return _preset_from_entity_type(
        "Property", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def public_sector_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "public_sector_match",
) -> PipelineConfig:
    """Preset for public sector identity matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with citizen/applicant records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            passport, national_id, voter_registration, license_number,
            case_number, first_name, last_name, date_of_birth, ssn,
            address_line_1, city, state, zip_code, phone, email.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: passport, national_id, license_number, "
            "first_name, last_name, date_of_birth, ssn, phone, email"
        )

    return _preset_from_entity_type(
        "Claimant", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def education_student_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "student_match",
) -> PipelineConfig:
    """Preset for education student record matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with student records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            student_id, enrollment_id, institution_code,
            first_name, last_name, date_of_birth, email, phone,
            address_line_1, city, state, zip_code.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: student_id, enrollment_id, institution_code, "
            "first_name, last_name, date_of_birth, email, phone"
        )

    return _preset_from_entity_type(
        "Student", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="dedupe_only",
    )


def travel_guest_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "guest_match",
) -> PipelineConfig:
    """Preset for travel/hospitality guest matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with guest records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            guest_id, booking_reference, frequent_flyer_number,
            first_name, last_name, email, phone, passport,
            date_of_birth.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: guest_id, booking_reference, "
            "frequent_flyer_number, first_name, last_name, email, phone"
        )

    return _preset_from_entity_type(
        "Guest", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )


def vendor_master_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "vendor_master_match",
) -> PipelineConfig:
    """Preset for vendor/supplier master data matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with vendor records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            vendor_id, duns_number, cage_code, sam_uei,
            company_name, ein, address_line_1, city, state,
            zip_code, phone, email.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: vendor_id, duns_number, cage_code, sam_uei, "
            "company_name, ein, address_line_1, city, state, zip_code"
        )

    return _preset_from_entity_type(
        "Vendor", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )


def identity_fraud_preset(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: dict[str, str] | None = None,
    project_name: str = "identity_fraud_match",
) -> PipelineConfig:
    """Preset for identity/fraud detection matching.

    Args:
        bq_project: GCP project ID.
        source_table: Source table with identity records.
        unique_key: Primary key column.
        updated_at: Timestamp column.
        columns: {column_name: role} mapping. Common roles:
            device_fingerprint_id, ip_address, email, phone,
            first_name, last_name, ssn, date_of_birth,
            address_line_1, city, state, zip_code.
        project_name: Project name.
    """
    if not columns:
        raise ConfigurationError(
            "columns dict required: {column_name: role}. "
            "Common roles: device_fingerprint_id, ip_address, email, "
            "phone, first_name, last_name, ssn, date_of_birth"
        )

    return _preset_from_entity_type(
        "DigitalIdentity", bq_project, source_table, unique_key, updated_at,
        columns, project_name, link_type="link_and_dedupe",
    )

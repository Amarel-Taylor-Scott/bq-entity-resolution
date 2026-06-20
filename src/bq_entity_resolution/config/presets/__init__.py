"""Configuration presets for common entity resolution use cases.

Presets provide progressive disclosure:
- Level 1: quick_config() — 5 lines, auto-detects roles from column names
- Level 2: role-based — assign semantic roles, auto-generate features
- Level 3: Full YAML control — complete manual configuration

Each preset function takes minimal inputs and returns a full
PipelineConfig.

Sub-modules:
- quick_config: quick_config() entry point
- domain_presets: 16 domain-specific presets (person, insurance, telecom, etc.)
- helpers: Internal config builders (not public API)
"""

from bq_entity_resolution.config.presets.domain_presets import (
    business_dedup_preset,
    education_student_preset,
    financial_transaction_preset,
    healthcare_patient_preset,
    identity_fraud_preset,
    insurance_dedup_preset,
    logistics_carrier_preset,
    person_dedup_preset,
    person_linkage_preset,
    public_sector_preset,
    real_estate_property_preset,
    retail_customer_preset,
    telecom_subscriber_preset,
    travel_guest_preset,
    vendor_master_preset,
)
from bq_entity_resolution.config.presets.quick_config import quick_config

__all__ = [
    "quick_config",
    "person_dedup_preset",
    "person_linkage_preset",
    "insurance_dedup_preset",
    "financial_transaction_preset",
    "healthcare_patient_preset",
    "business_dedup_preset",
    "telecom_subscriber_preset",
    "logistics_carrier_preset",
    "retail_customer_preset",
    "real_estate_property_preset",
    "public_sector_preset",
    "education_student_preset",
    "travel_guest_preset",
    "vendor_master_preset",
    "identity_fraud_preset",
]

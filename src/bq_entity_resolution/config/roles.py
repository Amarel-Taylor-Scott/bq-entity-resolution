"""Column role mappings: semantic roles drive auto-feature generation.

Roles are semantic labels like 'first_name', 'last_name', 'date_of_birth'.
Given a role, the system knows which features, blocking keys, and
comparisons to generate automatically.

This enables progressive disclosure: users assign roles to columns and
the system generates the full configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Role → Feature mapping
# ---------------------------------------------------------------------------

# Each role maps to a list of feature definitions.
# Format: (feature_name_suffix, function, input_override?)
# The actual feature name is constructed as: {column}_{suffix}

ROLE_FEATURES: dict[str, list[tuple[str, str]]] = {
    "first_name": [
        ("clean", "name_clean"),
        ("soundex", "soundex"),
        ("metaphone", "metaphone"),
    ],
    "last_name": [
        ("clean", "name_clean"),
        ("soundex", "soundex"),
        ("metaphone", "metaphone"),
    ],
    "full_name": [
        ("clean", "name_clean"),
        ("soundex", "soundex"),
    ],
    "date_of_birth": [
        ("year", "dob_year"),
    ],
    "email": [
        ("domain", "email_domain"),
        ("local", "email_local_part"),
        ("clean", "lower_trim"),
    ],
    "phone": [
        ("std", "phone_standardize"),
        ("last4", "phone_last_four"),
    ],
    "address_line_1": [
        ("std", "address_standardize"),
        ("street_number", "extract_street_number"),
    ],
    "city": [
        ("clean", "name_clean"),
        ("soundex", "soundex"),
    ],
    "state": [],  # No features needed — used directly
    "zip_code": [
        ("prefix3", "zip3"),
    ],
    "ssn": [
        ("last4", "ssn_last_four"),
    ],
    "company_name": [
        ("clean", "name_clean"),
        ("no_suffix", "strip_business_suffix"),
    ],
    "ein": [
        ("clean", "lower_trim"),
    ],
    # --- Insurance / Financial / Healthcare ---
    "policy_number": [
        ("clean", "upper_trim"),
    ],
    "claim_number": [
        ("clean", "upper_trim"),
    ],
    "account_number": [
        ("clean", "upper_trim"),
    ],
    "routing_number": [
        ("clean", "upper_trim"),
    ],
    "npi": [
        ("clean", "upper_trim"),
    ],
    "mrn": [
        ("clean", "upper_trim"),
    ],
    "vin": [
        ("clean", "upper_trim"),
    ],
    "transaction_amount": [],  # Numeric — no string transform
    "transaction_date": [
        ("year", "year_of_date"),
    ],
    "date_of_loss": [
        ("year", "year_of_date"),
    ],
    # --- Telecom / Utilities ---
    "subscriber_id": [
        ("clean", "upper_trim"),
    ],
    "imsi": [
        ("clean", "upper_trim"),
    ],
    "imei": [
        ("clean", "upper_trim"),
    ],
    "msisdn": [
        ("std", "phone_standardize"),
        ("last4", "phone_last_four"),
    ],
    "service_point_id": [
        ("clean", "upper_trim"),
    ],
    "meter_id": [
        ("clean", "upper_trim"),
    ],
    "circuit_id": [
        ("clean", "upper_trim"),
    ],
    "equipment_serial": [
        ("clean", "upper_trim"),
    ],
    # --- Logistics / Supply Chain ---
    "duns_number": [
        ("clean", "duns_clean"),
    ],
    "mc_dot_number": [
        ("clean", "upper_trim"),
    ],
    "carrier_scac": [
        ("clean", "upper_trim"),
    ],
    "bill_of_lading": [
        ("clean", "upper_trim"),
    ],
    "container_id": [
        ("clean", "upper_trim"),
    ],
    "tracking_number": [
        ("clean", "upper_trim"),
    ],
    # --- Retail / E-commerce ---
    "loyalty_id": [
        ("clean", "upper_trim"),
    ],
    "customer_id": [
        ("clean", "upper_trim"),
    ],
    "order_id": [
        ("clean", "upper_trim"),
    ],
    "device_fingerprint_id": [
        ("clean", "lower_trim"),
    ],
    "payment_token_id": [
        ("clean", "lower_trim"),
    ],
    # --- Real Estate / Property ---
    "parcel_number": [
        ("clean", "upper_trim"),
    ],
    "mls_id": [
        ("clean", "upper_trim"),
    ],
    "deed_reference": [
        ("clean", "upper_trim"),
    ],
    # --- Public Sector ---
    "passport": [
        ("clean", "upper_trim"),
    ],
    "national_id": [
        ("clean", "upper_trim"),
    ],
    "voter_registration": [
        ("clean", "upper_trim"),
    ],
    "license_number": [
        ("clean", "license_number_clean"),
    ],
    "case_number": [
        ("clean", "upper_trim"),
    ],
    # --- Education ---
    "student_id": [
        ("clean", "upper_trim"),
    ],
    "enrollment_id": [
        ("clean", "upper_trim"),
    ],
    "institution_code": [
        ("clean", "upper_trim"),
    ],
    # --- Travel / Hospitality ---
    "guest_id": [
        ("clean", "upper_trim"),
    ],
    "booking_reference": [
        ("clean", "upper_trim"),
    ],
    "frequent_flyer_number": [
        ("clean", "upper_trim"),
    ],
    # --- Manufacturing / IoT ---
    "device_id": [
        ("clean", "upper_trim"),
    ],
    "serial_number": [
        ("clean", "upper_trim"),
    ],
    "asset_tag": [
        ("clean", "upper_trim"),
    ],
    "mac_address": [
        ("clean", "lower_trim"),
    ],
    # --- Vendor Master ---
    "vendor_id": [
        ("clean", "upper_trim"),
    ],
    "cage_code": [
        ("clean", "upper_trim"),
    ],
    "sam_uei": [
        ("clean", "upper_trim"),
    ],
    # --- Identity / Fraud ---
    "ip_address": [
        ("clean", "lower_trim"),
    ],
    "user_agent": [],  # Free text — no transform
}

# ---------------------------------------------------------------------------
# Role → Blocking key mapping
# ---------------------------------------------------------------------------

# Each role maps to blocking keys to generate.
# Format: (key_name_suffix, function)
#
# BLOCKING KEY TYPE STRATEGY:
# We use two patterns based on the column semantics:
#
# 1. FARM_FINGERPRINT → INT64 (fp_ prefix) for HIGH-CARDINALITY identifiers:
#    policy_number, claim_number, account_number, npi, mrn
#    These are unique-ish values where exact-match blocking is desired.
#    INT64 equi-join is ~3-5x faster than STRING equi-join in BigQuery.
#
# 2. STRING functions for LOW-CARDINALITY phonetic/partial keys:
#    soundex (4 chars), email_domain, phone_last4, zip3, ssn_last4
#    These intentionally produce coarse buckets to enable fuzzy matching.
#    The join fanout is controlled by the low cardinality, not the type.
#
# 3. INT64 via EXTRACT for DATE columns:
#    dob_year, year_of_date → INT64 natively.
#
# For very large tables (>100M rows), consider upgrading STRING blocking
# keys to their INT64 equivalents via FARM_FINGERPRINT wrapping:
#    soundex → FARM_FINGERPRINT(SOUNDEX(col))  — same buckets, faster join
#    email_domain → FARM_FINGERPRINT(email_domain) — INT64 join

ROLE_BLOCKING_KEYS: dict[str, list[tuple[str, str]]] = {
    # STRING blocking keys — low cardinality, acceptable performance
    "first_name": [
        ("first_soundex", "soundex"),      # STRING(4) — ~7K distinct values
    ],
    "last_name": [
        ("last_soundex", "soundex"),       # STRING(4) — ~7K distinct values
    ],
    "full_name": [
        ("name_soundex", "soundex"),       # STRING(4)
    ],
    "date_of_birth": [
        ("dob_year", "dob_year"),          # INT64 — ~100 distinct values, fast
    ],
    "email": [
        ("email_domain", "email_domain"),  # STRING — ~10K distinct domains
    ],
    "phone": [
        ("phone_last4", "phone_last_four"),  # STRING(4) — 10K distinct values
    ],
    "zip_code": [
        ("zip3", "zip3"),                  # STRING(3) — ~1K distinct values
    ],
    "ssn": [
        ("ssn_last4", "ssn_last_four"),    # STRING(4) — 10K distinct values
    ],
    "company_name": [
        ("company_soundex", "soundex"),    # STRING(4)
    ],
    # --- Insurance / Financial / Healthcare ---
    # INT64 blocking keys — high cardinality, FARM_FINGERPRINT for speed
    "policy_number": [
        ("policy_fp", "farm_fingerprint"),    # INT64 — exact match on identifier
    ],
    "claim_number": [
        ("claim_fp", "farm_fingerprint"),     # INT64 — exact match on identifier
    ],
    "account_number": [
        ("account_fp", "farm_fingerprint"),   # INT64 — exact match on identifier
    ],
    "npi": [
        ("npi_fp", "farm_fingerprint"),       # INT64 — exact match on identifier
    ],
    "mrn": [
        ("mrn_fp", "farm_fingerprint"),       # INT64 — exact match on identifier
    ],
    "transaction_date": [
        ("txn_date_year", "year_of_date"),    # INT64 — year extraction
    ],
    "date_of_loss": [
        ("dol_year", "year_of_date"),         # INT64 — year extraction
    ],
    # --- Telecom / Utilities ---
    "subscriber_id": [
        ("subscriber_fp", "farm_fingerprint"),
    ],
    "imsi": [
        ("imsi_fp", "farm_fingerprint"),
    ],
    "imei": [
        ("imei_fp", "farm_fingerprint"),
    ],
    "msisdn": [
        ("msisdn_last4", "phone_last_four"),
    ],
    "service_point_id": [
        ("spi_fp", "farm_fingerprint"),
    ],
    "meter_id": [
        ("meter_fp", "farm_fingerprint"),
    ],
    "circuit_id": [
        ("circuit_fp", "farm_fingerprint"),
    ],
    "equipment_serial": [
        ("equip_serial_fp", "farm_fingerprint"),
    ],
    # --- Logistics / Supply Chain ---
    "duns_number": [
        ("duns_fp", "farm_fingerprint"),
    ],
    "mc_dot_number": [
        ("mc_dot_fp", "farm_fingerprint"),
    ],
    "carrier_scac": [
        ("scac_fp", "farm_fingerprint"),
    ],
    "bill_of_lading": [
        ("bol_fp", "farm_fingerprint"),
    ],
    "container_id": [
        ("container_fp", "farm_fingerprint"),
    ],
    "tracking_number": [
        ("tracking_fp", "farm_fingerprint"),
    ],
    # --- Retail / E-commerce ---
    "loyalty_id": [
        ("loyalty_fp", "farm_fingerprint"),
    ],
    "customer_id": [
        ("customer_fp", "farm_fingerprint"),
    ],
    "order_id": [
        ("order_fp", "farm_fingerprint"),
    ],
    "device_fingerprint_id": [
        ("device_fp", "farm_fingerprint"),
    ],
    "payment_token_id": [
        ("payment_fp", "farm_fingerprint"),
    ],
    # --- Real Estate / Property ---
    "parcel_number": [
        ("parcel_fp", "farm_fingerprint"),
    ],
    "mls_id": [
        ("mls_fp", "farm_fingerprint"),
    ],
    "deed_reference": [
        ("deed_fp", "farm_fingerprint"),
    ],
    # --- Public Sector ---
    "passport": [
        ("passport_fp", "farm_fingerprint"),
    ],
    "national_id": [
        ("national_id_fp", "farm_fingerprint"),
    ],
    "voter_registration": [
        ("voter_fp", "farm_fingerprint"),
    ],
    "license_number": [
        ("license_fp", "farm_fingerprint"),
    ],
    "case_number": [
        ("case_fp", "farm_fingerprint"),
    ],
    # --- Education ---
    "student_id": [
        ("student_fp", "farm_fingerprint"),
    ],
    "enrollment_id": [
        ("enrollment_fp", "farm_fingerprint"),
    ],
    "institution_code": [
        ("inst_code_fp", "farm_fingerprint"),
    ],
    # --- Travel / Hospitality ---
    "guest_id": [
        ("guest_fp", "farm_fingerprint"),
    ],
    "booking_reference": [
        ("booking_fp", "farm_fingerprint"),
    ],
    "frequent_flyer_number": [
        ("ff_fp", "farm_fingerprint"),
    ],
    # --- Manufacturing / IoT ---
    "device_id": [
        ("device_id_fp", "farm_fingerprint"),
    ],
    "serial_number": [
        ("serial_fp", "farm_fingerprint"),
    ],
    "asset_tag": [
        ("asset_tag_fp", "farm_fingerprint"),
    ],
    "mac_address": [
        ("mac_fp", "farm_fingerprint"),
    ],
    # --- Vendor Master ---
    "vendor_id": [
        ("vendor_fp", "farm_fingerprint"),
    ],
    "cage_code": [
        ("cage_fp", "farm_fingerprint"),
    ],
    "sam_uei": [
        ("sam_uei_fp", "farm_fingerprint"),
    ],
    # --- Identity / Fraud ---
    "ip_address": [
        ("ip_fp", "farm_fingerprint"),
    ],
}

# ---------------------------------------------------------------------------
# Role → Comparison mapping
# ---------------------------------------------------------------------------

# Each role maps to comparisons to generate.
# Format: (comparison_name, method, left_suffix, right_suffix, weight, params)

@dataclass(frozen=True)
class ComparisonSpec:
    """Specification for an auto-generated comparison."""
    name_suffix: str
    method: str
    feature_suffix: str  # Applied to both left and right columns
    weight: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)


ROLE_COMPARISONS: dict[str, list[ComparisonSpec]] = {
    "first_name": [
        ComparisonSpec("jw", "jaro_winkler", "clean", weight=2.0),
        ComparisonSpec("exact", "exact", "clean", weight=3.0),
    ],
    "last_name": [
        ComparisonSpec("jw", "jaro_winkler", "clean", weight=2.0),
        ComparisonSpec("exact", "exact", "clean", weight=3.0),
    ],
    "full_name": [
        ComparisonSpec("jw", "jaro_winkler", "clean", weight=2.5),
    ],
    "date_of_birth": [
        ComparisonSpec("exact", "exact", "", weight=4.0),
    ],
    "email": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),  # clean = lower_trim
        ComparisonSpec("domain_match", "exact", "domain", weight=0.5),
    ],
    "phone": [
        ComparisonSpec("exact", "exact", "std", weight=4.0),
    ],
    "address_line_1": [
        ComparisonSpec("lev", "levenshtein", "std", weight=1.5),
    ],
    "city": [
        ComparisonSpec("exact", "exact", "clean", weight=1.0),
    ],
    "state": [
        ComparisonSpec("exact", "exact", "", weight=0.5),
    ],
    "zip_code": [
        ComparisonSpec("exact", "exact", "", weight=1.5),
    ],
    "ssn": [
        ComparisonSpec("exact", "exact", "last4", weight=5.0),
    ],
    "company_name": [
        ComparisonSpec("jw", "jaro_winkler", "clean", weight=2.5),
        ComparisonSpec("exact", "exact", "clean", weight=4.0),
    ],
    "ein": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),  # clean = lower_trim
    ],
    # --- Insurance / Financial / Healthcare ---
    "policy_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "claim_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "account_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "routing_number": [
        ComparisonSpec("exact", "exact", "clean", weight=3.0),
    ],
    "npi": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "mrn": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "vin": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "transaction_amount": [
        ComparisonSpec("within", "numeric_within", "", weight=2.0,
                       params={"tolerance": 0.01}),
    ],
    "transaction_date": [
        ComparisonSpec("within", "date_within_days", "", weight=2.0,
                       params={"days": 1}),
    ],
    "date_of_loss": [
        ComparisonSpec("exact", "exact", "", weight=4.0),
    ],
    # --- Telecom / Utilities (identifier exact match) ---
    "subscriber_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "imsi": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "imei": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "msisdn": [
        ComparisonSpec("exact", "exact", "std", weight=5.0),
    ],
    "service_point_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "meter_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "circuit_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "equipment_serial": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    # --- Logistics / Supply Chain ---
    "duns_number": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "mc_dot_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "carrier_scac": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    "bill_of_lading": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "container_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "tracking_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    # --- Retail / E-commerce ---
    "loyalty_id": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    "customer_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "order_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "device_fingerprint_id": [
        ComparisonSpec("exact", "exact", "clean", weight=4.0),
    ],
    "payment_token_id": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    # --- Real Estate / Property ---
    "parcel_number": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "mls_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "deed_reference": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    # --- Public Sector ---
    "passport": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "national_id": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "voter_registration": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    "license_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "case_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    # --- Education ---
    "student_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "enrollment_id": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    "institution_code": [
        ComparisonSpec("exact", "exact", "clean", weight=4.0),
    ],
    # --- Travel / Hospitality ---
    "guest_id": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    "booking_reference": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "frequent_flyer_number": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    # --- Manufacturing / IoT ---
    "device_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "serial_number": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    "asset_tag": [
        ComparisonSpec("exact", "exact", "clean", weight=5.0),
    ],
    "mac_address": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    # --- Vendor Master ---
    "vendor_id": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "cage_code": [
        ComparisonSpec("exact", "exact", "clean", weight=6.0),
    ],
    "sam_uei": [
        ComparisonSpec("exact", "exact", "clean", weight=7.0),
    ],
    # --- Identity / Fraud ---
    "ip_address": [
        ComparisonSpec("exact", "exact", "clean", weight=3.0),
    ],
}


# ---------------------------------------------------------------------------
# Role detection from column names
# ---------------------------------------------------------------------------

# Common column name patterns that suggest a role.
# Keys are substrings to match (case-insensitive), values are roles.

_NAME_PATTERNS: dict[str, str] = {
    "first_name": "first_name",
    "fname": "first_name",
    "given_name": "first_name",
    "last_name": "last_name",
    "lname": "last_name",
    "surname": "last_name",
    "family_name": "last_name",
    "full_name": "full_name",
    "name": "full_name",
    "dob": "date_of_birth",
    "date_of_birth": "date_of_birth",
    "birth_date": "date_of_birth",
    "birthday": "date_of_birth",
    "email": "email",
    "email_address": "email",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "cell_phone": "phone",
    "address": "address_line_1",
    "address_line_1": "address_line_1",
    "street": "address_line_1",
    "city": "city",
    "state": "state",
    "zip": "zip_code",
    "zip_code": "zip_code",
    "postal_code": "zip_code",
    "ssn": "ssn",
    "social_security": "ssn",
    "company": "company_name",
    "company_name": "company_name",
    "business_name": "company_name",
    "org_name": "company_name",
    "ein": "ein",
    "tax_id": "ein",
    # Insurance
    "policy_number": "policy_number",
    "policy_no": "policy_number",
    "policy_num": "policy_number",
    "claim_number": "claim_number",
    "claim_no": "claim_number",
    "claim_num": "claim_number",
    "claim_id": "claim_number",
    "date_of_loss": "date_of_loss",
    "loss_date": "date_of_loss",
    # Financial
    "account_number": "account_number",
    "account_no": "account_number",
    "account_num": "account_number",
    "acct_number": "account_number",
    "acct_no": "account_number",
    "routing_number": "routing_number",
    "routing_no": "routing_number",
    "aba_number": "routing_number",
    "transaction_amount": "transaction_amount",
    "txn_amount": "transaction_amount",
    "amount": "transaction_amount",
    "transaction_date": "transaction_date",
    "txn_date": "transaction_date",
    # Healthcare
    "npi": "npi",
    "npi_number": "npi",
    "mrn": "mrn",
    "medical_record_number": "mrn",
    "patient_id": "mrn",
    # Automotive
    "vin": "vin",
    "vehicle_identification_number": "vin",
    # Telecom / Utilities
    "subscriber_id": "subscriber_id",
    "subscriber_number": "subscriber_id",
    "imsi": "imsi",
    "imei": "imei",
    "msisdn": "msisdn",
    "service_point_id": "service_point_id",
    "service_point": "service_point_id",
    "meter_id": "meter_id",
    "meter_number": "meter_id",
    "meter_no": "meter_id",
    "circuit_id": "circuit_id",
    "equipment_serial": "equipment_serial",
    "equipment_serial_number": "equipment_serial",
    # Logistics / Supply Chain
    "duns_number": "duns_number",
    "duns": "duns_number",
    "duns_no": "duns_number",
    "mc_dot_number": "mc_dot_number",
    "mc_number": "mc_dot_number",
    "dot_number": "mc_dot_number",
    "carrier_scac": "carrier_scac",
    "scac": "carrier_scac",
    "scac_code": "carrier_scac",
    "bill_of_lading": "bill_of_lading",
    "bol": "bill_of_lading",
    "bol_number": "bill_of_lading",
    "container_id": "container_id",
    "container_number": "container_id",
    "tracking_number": "tracking_number",
    "tracking_no": "tracking_number",
    "shipment_tracking": "tracking_number",
    # Retail / E-commerce
    "loyalty_id": "loyalty_id",
    "loyalty_number": "loyalty_id",
    "loyalty_card": "loyalty_id",
    "rewards_number": "loyalty_id",
    "customer_id": "customer_id",
    "cust_id": "customer_id",
    "order_id": "order_id",
    "order_number": "order_id",
    "order_no": "order_id",
    "device_fingerprint_id": "device_fingerprint_id",
    "device_fingerprint": "device_fingerprint_id",
    "payment_token_id": "payment_token_id",
    "payment_token": "payment_token_id",
    # Real Estate / Property
    "parcel_number": "parcel_number",
    "parcel_no": "parcel_number",
    "parcel_id": "parcel_number",
    "apn": "parcel_number",
    "mls_id": "mls_id",
    "mls_number": "mls_id",
    "listing_id": "mls_id",
    "deed_reference": "deed_reference",
    "deed_ref": "deed_reference",
    "deed_number": "deed_reference",
    # Public Sector
    "passport": "passport",
    "passport_number": "passport",
    "passport_no": "passport",
    "national_id": "national_id",
    "national_id_number": "national_id",
    "voter_registration": "voter_registration",
    "voter_id": "voter_registration",
    "voter_reg": "voter_registration",
    "license_number": "license_number",
    "license_no": "license_number",
    "drivers_license": "license_number",
    "dl_number": "license_number",
    "case_number": "case_number",
    "case_no": "case_number",
    "case_id": "case_number",
    "docket_number": "case_number",
    # Education
    "student_id": "student_id",
    "student_number": "student_id",
    "enrollment_id": "enrollment_id",
    "enrollment_number": "enrollment_id",
    "institution_code": "institution_code",
    "school_code": "institution_code",
    "ipeds_code": "institution_code",
    # Travel / Hospitality
    "guest_id": "guest_id",
    "guest_number": "guest_id",
    "booking_reference": "booking_reference",
    "booking_ref": "booking_reference",
    "reservation_number": "booking_reference",
    "confirmation_number": "booking_reference",
    "pnr": "booking_reference",
    "frequent_flyer_number": "frequent_flyer_number",
    "frequent_flyer": "frequent_flyer_number",
    "ff_number": "frequent_flyer_number",
    "mileage_number": "frequent_flyer_number",
    # Manufacturing / IoT
    "device_id": "device_id",
    "serial_number": "serial_number",
    "serial_no": "serial_number",
    "asset_tag": "asset_tag",
    "asset_id": "asset_tag",
    "mac_address": "mac_address",
    "mac_addr": "mac_address",
    # Vendor Master
    "vendor_id": "vendor_id",
    "vendor_number": "vendor_id",
    "vendor_no": "vendor_id",
    "supplier_id": "vendor_id",
    "cage_code": "cage_code",
    "sam_uei": "sam_uei",
    "uei_number": "sam_uei",
    # Identity / Fraud
    "ip_address": "ip_address",
    "ip_addr": "ip_address",
    "user_agent": "user_agent",
    # --- Schema.org property aliases (camelCase collapsed to lowercase) ---
    # See https://schema.org/Person, /Organization, /PostalAddress
    "givenname": "first_name",
    "familyname": "last_name",
    "legalname": "company_name",
    "telephone": "phone",
    "birthdate": "date_of_birth",
    "postalcode": "zip_code",
    "streetaddress": "address_line_1",
    "addresslocality": "city",
    "addressregion": "state",
    "addresscountry": "state",  # best-effort mapping
    "taxid": "ein",
}


def detect_role(column_name: str) -> str | None:
    """Detect a semantic role from a column name.

    Uses pattern matching on common naming conventions.
    Returns None if no role can be determined.
    """
    lower = column_name.lower().strip()

    # Exact match first
    if lower in _NAME_PATTERNS:
        return _NAME_PATTERNS[lower]

    # Word-boundary match: pattern must appear as a standalone token
    # separated by underscores, or at the start/end of the name.
    # Longest patterns first for specificity.
    for pattern in sorted(_NAME_PATTERNS.keys(), key=len, reverse=True):
        # Check if pattern appears as a complete word segment
        # Pattern must be bounded by start/end of string or underscores
        if re.search(rf'(?:^|_){re.escape(pattern)}(?:_|$)', lower):
            return _NAME_PATTERNS[pattern]

    return None


def features_for_role(
    column_name: str, role: str
) -> list[dict[str, Any]]:
    """Generate feature definitions for a column with a given role.

    Returns a list of dicts suitable for FeatureDef construction:
    [{"name": "first_name_clean", "function": "name_clean", "inputs": ["first_name"]}, ...]
    """
    specs = ROLE_FEATURES.get(role, [])
    features = []
    for suffix, function in specs:
        feat_name = f"{column_name}_{suffix}" if suffix else column_name
        features.append({
            "name": feat_name,
            "function": function,
            "inputs": [column_name],
        })
    return features


def blocking_keys_for_role(
    column_name: str, role: str
) -> list[dict[str, Any]]:
    """Generate blocking key definitions for a column with a given role.

    Returns a list of dicts suitable for BlockingKeyDef construction.
    """
    specs = ROLE_BLOCKING_KEYS.get(role, [])
    keys = []
    for suffix, function in specs:
        keys.append({
            "name": f"bk_{suffix}",
            "function": function,
            "inputs": [column_name],
        })
    return keys


def comparisons_for_role(
    column_name: str, role: str
) -> list[dict[str, Any]]:
    """Generate comparison definitions for a column with a given role.

    Returns a list of dicts suitable for ComparisonDef construction.
    The left and right columns are the feature-transformed version.
    """
    specs = ROLE_COMPARISONS.get(role, [])
    comparisons = []
    for spec in specs:
        feature_col = (
            f"{column_name}_{spec.feature_suffix}"
            if spec.feature_suffix
            else column_name
        )
        comparisons.append({
            "name": f"{column_name}_{spec.name_suffix}",
            "left": feature_col,
            "right": feature_col,
            "method": spec.method,
            "weight": spec.weight,
            "params": dict(spec.params),
        })
    return comparisons


# ---------------------------------------------------------------------------
# Available roles
# ---------------------------------------------------------------------------

PERSON_ROLES: frozenset[str] = frozenset({
    "first_name", "last_name", "full_name",
    "date_of_birth", "email", "phone",
    "address_line_1", "city", "state", "zip_code", "ssn",
})

BUSINESS_ROLES: frozenset[str] = frozenset({
    "company_name", "ein",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email",
})

INSURANCE_ROLES: frozenset[str] = frozenset({
    "policy_number", "claim_number",
    "first_name", "last_name", "full_name",
    "date_of_birth", "date_of_loss",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email", "ssn",
})

FINANCIAL_ROLES: frozenset[str] = frozenset({
    "account_number", "routing_number",
    "transaction_amount", "transaction_date",
    "first_name", "last_name", "full_name",
    "email", "phone", "ssn",
    "address_line_1", "city", "state", "zip_code",
})

HEALTHCARE_ROLES: frozenset[str] = frozenset({
    "npi", "mrn",
    "first_name", "last_name", "full_name",
    "date_of_birth",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email", "ssn",
})

TELECOM_ROLES: frozenset[str] = frozenset({
    "subscriber_id", "imsi", "imei", "msisdn",
    "service_point_id", "meter_id", "circuit_id", "equipment_serial",
    "first_name", "last_name", "full_name",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email",
})

LOGISTICS_ROLES: frozenset[str] = frozenset({
    "duns_number", "mc_dot_number", "carrier_scac",
    "bill_of_lading", "container_id", "tracking_number",
    "company_name", "ein",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email",
})

RETAIL_ROLES: frozenset[str] = frozenset({
    "loyalty_id", "customer_id", "order_id",
    "device_fingerprint_id", "payment_token_id",
    "first_name", "last_name", "full_name",
    "email", "phone",
    "address_line_1", "city", "state", "zip_code",
})

REAL_ESTATE_ROLES: frozenset[str] = frozenset({
    "parcel_number", "mls_id", "deed_reference",
    "address_line_1", "city", "state", "zip_code",
    "full_name", "company_name",
    "phone", "email",
})

PUBLIC_SECTOR_ROLES: frozenset[str] = frozenset({
    "passport", "national_id", "voter_registration",
    "license_number", "case_number",
    "first_name", "last_name", "full_name",
    "date_of_birth", "ssn",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email",
})

EDUCATION_ROLES: frozenset[str] = frozenset({
    "student_id", "enrollment_id", "institution_code",
    "first_name", "last_name", "full_name",
    "date_of_birth", "email", "phone",
    "address_line_1", "city", "state", "zip_code",
})

TRAVEL_ROLES: frozenset[str] = frozenset({
    "guest_id", "booking_reference", "frequent_flyer_number",
    "first_name", "last_name", "full_name",
    "email", "phone", "passport",
    "date_of_birth",
})

MANUFACTURING_ROLES: frozenset[str] = frozenset({
    "device_id", "serial_number", "asset_tag", "mac_address",
    "company_name", "vendor_id",
    "address_line_1", "city", "state", "zip_code",
})

VENDOR_MASTER_ROLES: frozenset[str] = frozenset({
    "vendor_id", "duns_number", "cage_code", "sam_uei",
    "company_name", "ein",
    "address_line_1", "city", "state", "zip_code",
    "phone", "email",
})

IDENTITY_FRAUD_ROLES: frozenset[str] = frozenset({
    "device_fingerprint_id", "ip_address", "user_agent",
    "first_name", "last_name", "full_name",
    "email", "phone", "ssn",
    "date_of_birth",
    "address_line_1", "city", "state", "zip_code",
})


def roles_for_entity_type(entity_type: str) -> frozenset[str]:
    """Return valid roles for a registered entity type.

    Falls back to all known roles if the entity type is not registered.
    Uses lazy import to avoid circular dependency with entity_types module.
    """
    from bq_entity_resolution.config.entity_types import resolve_hierarchy

    try:
        template = resolve_hierarchy(entity_type)
        return template.valid_roles
    except KeyError:
        return frozenset(ROLE_FEATURES.keys())

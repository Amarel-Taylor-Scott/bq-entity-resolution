"""Industry-specific feature functions.

Specialized normalization and validation for identifiers common in
insurance (VIN, policy numbers), banking (IBAN, routing numbers),
healthcare (NPI, DEA), and general business (EIN, DUNS).
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register

# ---------------------------------------------------------------------------
# Insurance / Automotive
# ---------------------------------------------------------------------------


@register("vin_normalize")
def vin_normalize(inputs: list[str], **_: Any) -> str:
    """Normalize Vehicle Identification Number (VIN).

    Removes non-alphanumeric chars, uppercases, strips common OCR
    errors (O→0, I→1, Q→0 per VIN specification which excludes I, O, Q).
    Standard VIN is 17 characters.

    OUTPUT TYPE: STRING (17 chars for valid VINs)
    When to use: Auto insurance, fleet management, vehicle registration matching.
    """
    col = inputs[0]
    return (
        f"REGEXP_REPLACE("
        f"REPLACE(REPLACE(REPLACE("
        f"UPPER(REGEXP_REPLACE({col}, r'[^A-Za-z0-9]', '')), "
        f"'O', '0'), 'I', '1'), 'Q', '0'), "
        f"r'[^A-HJ-NPR-Z0-9]', '')"
    )


@register("vin_last_six")
def vin_last_six(inputs: list[str], **_: Any) -> str:
    """Extract last 6 characters of VIN (serial number portion).

    The last 6 digits are the sequential production number — unique within
    a manufacturer/year/plant combination. Useful for blocking.

    OUTPUT TYPE: STRING (6 chars)
    """
    col = inputs[0]
    return (
        f"RIGHT(REGEXP_REPLACE("
        f"REPLACE(REPLACE(REPLACE("
        f"UPPER(REGEXP_REPLACE({col}, r'[^A-Za-z0-9]', '')), "
        f"'O', '0'), 'I', '1'), 'Q', '0'), "
        f"r'[^A-HJ-NPR-Z0-9]', ''), 6)"
    )


@register("policy_number_clean")
def policy_number_clean(inputs: list[str], **_: Any) -> str:
    """Clean and normalize an insurance policy number.

    Strips whitespace, dashes, leading zeros, uppercases.
    Handles common variations: 'POL-123-456' → 'POL123456'.

    OUTPUT TYPE: STRING
    When to use: Insurance policy matching across systems with
    different formatting conventions.
    """
    col = inputs[0]
    return (
        f"UPPER(REGEXP_REPLACE(REGEXP_REPLACE(TRIM({col}), "
        f"r'[-\\s]', ''), r'^0+', ''))"
    )


# ---------------------------------------------------------------------------
# Banking / Financial
# ---------------------------------------------------------------------------


@register("iban_normalize")
def iban_normalize(inputs: list[str], **_: Any) -> str:
    """Normalize International Bank Account Number (IBAN).

    Removes spaces and dashes, uppercases. Standard IBAN is 15-34 chars
    starting with 2-letter country code + 2 check digits.

    OUTPUT TYPE: STRING
    When to use: International banking entity resolution, KYC matching.
    """
    col = inputs[0]
    return f"UPPER(REGEXP_REPLACE(TRIM({col}), r'[\\s-]', ''))"


@register("routing_number_clean")
def routing_number_clean(inputs: list[str], **_: Any) -> str:
    """Clean US bank routing number (ABA RTN).

    Strips non-digits. Standard ABA RTN is 9 digits.

    OUTPUT TYPE: STRING (9 digits for valid RTNs)
    When to use: US banking entity resolution.
    """
    col = inputs[0]
    return f"REGEXP_REPLACE(TRIM({col}), r'[^0-9]', '')"


@register("account_number_clean")
def account_number_clean(inputs: list[str], **_: Any) -> str:
    """Clean bank account number.

    Strips spaces, dashes, leading zeros.

    OUTPUT TYPE: STRING
    When to use: Bank account matching across statements and systems.
    """
    col = inputs[0]
    return (
        f"REGEXP_REPLACE(REGEXP_REPLACE(TRIM({col}), "
        f"r'[\\s-]', ''), r'^0+', '')"
    )


@register("amount_bucket")
def amount_bucket(inputs: list[str], bucket_size: int = 100, **_: Any) -> str:
    """Bucket a monetary amount into fixed ranges for blocking.

    E.g., bucket_size=100: $150.50 → 100, $250.99 → 200.

    OUTPUT TYPE: INT64
    When to use: Blocking on approximate amount ranges for financial
    transaction matching.
    """
    col = inputs[0]
    return (
        f"CAST(FLOOR(CAST({col} AS FLOAT64) / {bucket_size}) "
        f"* {bucket_size} AS INT64)"
    )


# ---------------------------------------------------------------------------
# Healthcare
# ---------------------------------------------------------------------------


@register("npi_validate")
def npi_validate(inputs: list[str], **_: Any) -> str:
    """Validate and clean National Provider Identifier (NPI).

    NPI is a 10-digit number assigned to healthcare providers.
    Strips non-digits and validates length.

    OUTPUT TYPE: STRING (10 digits or NULL if invalid)
    When to use: Healthcare provider matching, claims resolution.
    """
    col = inputs[0]
    return (
        f"CASE WHEN CHAR_LENGTH(REGEXP_REPLACE({col}, r'[^0-9]', '')) = 10 "
        f"THEN REGEXP_REPLACE({col}, r'[^0-9]', '') ELSE NULL END"
    )


@register("dea_number_clean")
def dea_number_clean(inputs: list[str], **_: Any) -> str:
    """Clean DEA (Drug Enforcement Administration) registration number.

    DEA numbers are 9 characters: 2 letters + 7 digits.
    Uppercases and strips whitespace.

    OUTPUT TYPE: STRING
    When to use: Healthcare prescriber matching.
    """
    col = inputs[0]
    return f"UPPER(REGEXP_REPLACE(TRIM({col}), r'[\\s-]', ''))"


@register("mrn_clean")
def mrn_clean(inputs: list[str], **_: Any) -> str:
    """Clean Medical Record Number.

    Strips non-alphanumeric characters and leading zeros.

    OUTPUT TYPE: STRING
    When to use: Patient matching across healthcare facilities.
    """
    col = inputs[0]
    return (
        f"UPPER(REGEXP_REPLACE(REGEXP_REPLACE(TRIM({col}), "
        f"r'[^A-Za-z0-9]', ''), r'^0+', ''))"
    )


@register("icd_code_normalize")
def icd_code_normalize(inputs: list[str], **_: Any) -> str:
    """Normalize ICD-10 diagnosis code.

    Removes dots, uppercases. E.g., 'M54.5' → 'M545'.
    Handles both ICD-9 and ICD-10 formats.

    OUTPUT TYPE: STRING
    When to use: Healthcare claims matching on diagnosis codes.
    """
    col = inputs[0]
    return f"UPPER(REGEXP_REPLACE(TRIM({col}), r'[^A-Za-z0-9]', ''))"


# ---------------------------------------------------------------------------
# General Business
# ---------------------------------------------------------------------------


@register("ein_format")
def ein_format(inputs: list[str], **_: Any) -> str:
    """Clean and normalize Employer Identification Number (EIN).

    Strips dashes and non-digits. Standard EIN is 9 digits: XX-XXXXXXX.

    OUTPUT TYPE: STRING (9 digits)
    When to use: Business entity resolution, corporate matching, tax records.
    """
    col = inputs[0]
    return f"REGEXP_REPLACE(TRIM({col}), r'[^0-9]', '')"


@register("duns_clean")
def duns_clean(inputs: list[str], **_: Any) -> str:
    """Clean D-U-N-S number (Dun & Bradstreet).

    Strips dashes, spaces, and validates 9-digit format.

    OUTPUT TYPE: STRING (9 digits or NULL if invalid)
    When to use: Business-to-business entity resolution.
    """
    col = inputs[0]
    return (
        f"CASE WHEN CHAR_LENGTH(REGEXP_REPLACE({col}, r'[^0-9]', '')) = 9 "
        f"THEN REGEXP_REPLACE({col}, r'[^0-9]', '') ELSE NULL END"
    )


@register("ticker_normalize")
def ticker_normalize(inputs: list[str], **_: Any) -> str:
    """Normalize stock ticker symbol.

    Uppercases, strips whitespace and dots. E.g., 'brk.b' → 'BRKB'.

    OUTPUT TYPE: STRING
    When to use: Brokerage entity resolution, financial instrument matching.
    """
    col = inputs[0]
    return f"UPPER(REGEXP_REPLACE(TRIM({col}), r'[\\s.]', ''))"


@register("cusip_clean")
def cusip_clean(inputs: list[str], **_: Any) -> str:
    """Clean CUSIP security identifier.

    CUSIP is a 9-character alphanumeric code identifying securities.
    Strips spaces and uppercases.

    OUTPUT TYPE: STRING (9 chars)
    When to use: Securities/brokerage entity resolution.
    """
    col = inputs[0]
    return f"UPPER(REGEXP_REPLACE(TRIM({col}), r'[\\s-]', ''))"


@register("license_number_clean")
def license_number_clean(inputs: list[str], **_: Any) -> str:
    """Clean driver's license or professional license number.

    Strips non-alphanumeric characters, uppercases.

    OUTPUT TYPE: STRING
    When to use: Insurance (driver identification), professional licensing.
    """
    col = inputs[0]
    return f"UPPER(REGEXP_REPLACE(TRIM({col}), r'[^A-Za-z0-9]', ''))"

"""Placeholder/sentinel value detection and nullification feature functions.

Detects common non-informative placeholder values in source data that cause
cartesian explosions when they hash to the same blocking key. For example,
thousands of records with phone "9999999999" all hash to one FARM_FINGERPRINT
value, producing O(n^2) candidate pairs.

Detection functions return INT64 flags (0 or 1).
Nullification functions return the original value or NULL if a placeholder is
detected — NULLs are excluded from blocking via IS NOT NULL conditions.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register

# ---------------------------------------------------------------------------
# Detection flags (return INT64 0/1)
# ---------------------------------------------------------------------------


@register("is_placeholder_phone")
def is_placeholder_phone(inputs: list[str], **_: Any) -> str:
    """Detect placeholder phone numbers.

    Matches: all-same-digit repeating (0000000000, 1111111111, 9999999999),
    sequential digits (1234567890), common test numbers (5555555555),
    and short repeated patterns (123123, 000000).

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag phone numbers that should not participate in blocking
    to prevent cartesian explosions from thousands of records sharing the
    same placeholder phone.
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS("
        f"REGEXP_REPLACE(CAST({col} AS STRING), r'[^0-9]', ''), "
        f"r'^(0{{7,}}|1{{7,}}|2{{7,}}|3{{7,}}|4{{7,}}|5{{7,}}"
        f"|6{{7,}}|7{{7,}}|8{{7,}}|9{{7,}}"
        f"|1234567890|0123456789|9876543210"
        f"|5555555555|0000000000|9999999999)$') "
        f"THEN 1 ELSE 0 END"
    )


@register("is_placeholder_email")
def is_placeholder_email(inputs: list[str], **_: Any) -> str:
    """Detect placeholder email addresses.

    Matches: noemail@, test@, nobody@, placeholder@, noreply@,
    fake@, example@, invalid@, unknown@, na@, none@, null@,
    donotreply@, sample@, and common test domains.

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag email addresses that should not participate in blocking.
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS(LOWER(CAST({col} AS STRING)), "
        f"r'^(noemail|no[._-]?email|test|nobody|placeholder|noreply|"
        f"no[._-]?reply|fake|example|invalid|unknown|n/?a|none|null|"
        f"donotreply|do[._-]?not[._-]?reply|sample|temp|dummy|"
        f"abc|xxx|info|admin)@') "
        f"OR REGEXP_CONTAINS(LOWER(CAST({col} AS STRING)), "
        f"r'@(example\\.com|test\\.com|fake\\.com|invalid\\.com|"
        f"placeholder\\.com|noemail\\.com|mailinator\\.com)$') "
        f"THEN 1 ELSE 0 END"
    )


@register("is_placeholder_name")
def is_placeholder_name(inputs: list[str], **_: Any) -> str:
    """Detect placeholder name values.

    Matches: UNKNOWN, N/A, NA, TBD, PENDING, TEST, DECEASED,
    DO NOT USE, NONE, NULL, DUMMY, SAMPLE, TEMP, GENERAL DELIVERY,
    OCCUPANT, RESIDENT, and similar non-informative names.

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag name fields that should not participate in blocking.
    """
    col = inputs[0]
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) IN ("
        f"'UNKNOWN', 'N/A', 'NA', 'N A', 'TBD', 'TBA', 'PENDING', "
        f"'TEST', 'TESTING', 'DECEASED', 'DECEDENT', "
        f"'DO NOT USE', 'DO NOT MAIL', 'DO NOT CONTACT', "
        f"'NONE', 'NULL', 'DUMMY', 'SAMPLE', 'TEMP', 'TEMPORARY', "
        f"'GENERAL DELIVERY', 'OCCUPANT', 'CURRENT RESIDENT', 'RESIDENT', "
        f"'NOT PROVIDED', 'NOT AVAILABLE', 'UNAVAILABLE', 'BLANK', "
        f"'XXX', 'XXXX', 'XXXXX', 'ZZZ', 'ZZZZ', "
        f"'JOHN DOE', 'JANE DOE', 'BABY BOY', 'BABY GIRL', "
        f"'FNU', 'LNU', 'NMN', 'NFN'"
        f") THEN 1 ELSE 0 END"
    )


@register("is_placeholder_address")
def is_placeholder_address(inputs: list[str], **_: Any) -> str:
    """Detect placeholder address values.

    Matches: 123 MAIN ST, 000, GENERAL DELIVERY, PO BOX 0,
    NO ADDRESS, HOMELESS, and similar non-informative addresses.

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag address fields that should not participate in blocking.
    """
    col = inputs[0]
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) IN ("
        f"'123 MAIN ST', '123 MAIN STREET', '000', '0000', "
        f"'GENERAL DELIVERY', 'NO ADDRESS', 'NONE', 'N/A', 'NA', "
        f"'UNKNOWN', 'HOMELESS', 'TRANSIENT', 'REFUSED', "
        f"'NOT PROVIDED', 'NOT AVAILABLE', 'UNAVAILABLE', "
        f"'PO BOX 0', 'PO BOX 000', 'TEST', 'TEMP', 'TBD'"
        f") "
        f"OR REGEXP_CONTAINS(UPPER(TRIM(CAST({col} AS STRING))), "
        f"r'^0+$') "
        f"THEN 1 ELSE 0 END"
    )


@register("is_placeholder_ssn")
def is_placeholder_ssn(inputs: list[str], **_: Any) -> str:
    """Detect placeholder SSN/TIN values.

    Matches: 000-00-0000, 999-99-9999, 123-45-6789,
    111-11-1111 through 888-88-8888, and all-zeros/nines.

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag SSN/TIN fields that should not participate in blocking.
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS("
        f"REGEXP_REPLACE(CAST({col} AS STRING), r'[^0-9]', ''), "
        f"r'^(000000000|999999999|123456789"
        f"|111111111|222222222|333333333|444444444"
        f"|555555555|666666666|777777777|888888888"
        f"|987654321)$') "
        f"THEN 1 ELSE 0 END"
    )


# ---------------------------------------------------------------------------
# Nullification functions (return original value or NULL)
# ---------------------------------------------------------------------------


@register("nullify_placeholder")
def nullify_placeholder(inputs: list[str], **kwargs: Any) -> str:
    """Generic placeholder nullification using a custom value list.

    Returns NULL if the value (UPPER trimmed) matches any pattern in the
    ``patterns`` param list. Otherwise returns the original value.

    OUTPUT TYPE: Same as input column type
    Params:
        patterns: list[str] — UPPER-case exact match values to nullify.

    Example YAML::

        features:
          - name: account_id_safe
            function: nullify_placeholder
            input: account_id
            params:
              patterns: ["000000", "UNKNOWN", "N/A", "TEST"]
    """
    col = inputs[0]
    patterns: list[str] = kwargs.get("patterns", [])
    if not patterns:
        return col
    quoted = ", ".join(f"'{p.upper()}'" for p in patterns)
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) IN ({quoted}) "
        f"THEN NULL ELSE {col} END"
    )


@register("nullify_placeholder_phone")
def nullify_placeholder_phone(inputs: list[str], **_: Any) -> str:
    """Nullify placeholder phone numbers.

    Returns NULL if the phone matches a known placeholder pattern,
    otherwise returns the original value. Use as a blocking key input
    to exclude placeholder phones from candidate pair generation.

    OUTPUT TYPE: Same as input column type (STRING or INT64)
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS("
        f"REGEXP_REPLACE(CAST({col} AS STRING), r'[^0-9]', ''), "
        f"r'^(0{{7,}}|1{{7,}}|2{{7,}}|3{{7,}}|4{{7,}}|5{{7,}}"
        f"|6{{7,}}|7{{7,}}|8{{7,}}|9{{7,}}"
        f"|1234567890|0123456789|9876543210"
        f"|5555555555|0000000000|9999999999)$') "
        f"THEN NULL ELSE {col} END"
    )


@register("nullify_placeholder_name")
def nullify_placeholder_name(inputs: list[str], **_: Any) -> str:
    """Nullify placeholder name values.

    Returns NULL if the name matches a known placeholder pattern,
    otherwise returns the original value. Use as a blocking key input
    to exclude placeholder names from candidate pair generation.

    OUTPUT TYPE: Same as input column type (STRING or NULL)
    """
    col = inputs[0]
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) IN ("
        f"'UNKNOWN', 'N/A', 'NA', 'N A', 'TBD', 'TBA', 'PENDING', "
        f"'TEST', 'TESTING', 'DECEASED', 'DECEDENT', "
        f"'DO NOT USE', 'DO NOT MAIL', 'DO NOT CONTACT', "
        f"'NONE', 'NULL', 'DUMMY', 'SAMPLE', 'TEMP', 'TEMPORARY', "
        f"'GENERAL DELIVERY', 'OCCUPANT', 'CURRENT RESIDENT', 'RESIDENT', "
        f"'NOT PROVIDED', 'NOT AVAILABLE', 'UNAVAILABLE', 'BLANK', "
        f"'XXX', 'XXXX', 'XXXXX', 'ZZZ', 'ZZZZ', "
        f"'JOHN DOE', 'JANE DOE', 'BABY BOY', 'BABY GIRL', "
        f"'FNU', 'LNU', 'NMN', 'NFN'"
        f") THEN NULL ELSE {col} END"
    )


@register("nullify_placeholder_address")
def nullify_placeholder_address(inputs: list[str], **_: Any) -> str:
    """Nullify placeholder address values.

    Returns NULL if the address matches a known placeholder pattern,
    otherwise returns the original value. Use as a blocking key input
    to exclude placeholder addresses from candidate pair generation.

    OUTPUT TYPE: Same as input column type (STRING or NULL)
    """
    col = inputs[0]
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) IN ("
        f"'123 MAIN ST', '123 MAIN STREET', '000', '0000', "
        f"'GENERAL DELIVERY', 'NO ADDRESS', 'NONE', 'N/A', 'NA', "
        f"'UNKNOWN', 'HOMELESS', 'TRANSIENT', 'REFUSED', "
        f"'NOT PROVIDED', 'NOT AVAILABLE', 'UNAVAILABLE', "
        f"'PO BOX 0', 'PO BOX 000', 'TEST', 'TEMP', 'TBD'"
        f") "
        f"OR REGEXP_CONTAINS(UPPER(TRIM(CAST({col} AS STRING))), "
        f"r'^0+$') "
        f"THEN NULL ELSE {col} END"
    )


@register("nullify_placeholder_email")
def nullify_placeholder_email(inputs: list[str], **_: Any) -> str:
    """Nullify placeholder email addresses.

    Returns NULL if the email matches a known placeholder pattern,
    otherwise returns the original value.

    OUTPUT TYPE: STRING (or NULL)
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS(LOWER(CAST({col} AS STRING)), "
        f"r'^(noemail|no[._-]?email|test|nobody|placeholder|noreply|"
        f"no[._-]?reply|fake|example|invalid|unknown|n/?a|none|null|"
        f"donotreply|do[._-]?not[._-]?reply|sample|temp|dummy|"
        f"abc|xxx|info|admin)@') "
        f"OR REGEXP_CONTAINS(LOWER(CAST({col} AS STRING)), "
        f"r'@(example\\.com|test\\.com|fake\\.com|invalid\\.com|"
        f"placeholder\\.com|noemail\\.com|mailinator\\.com)$') "
        f"THEN NULL ELSE {col} END"
    )

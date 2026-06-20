"""Contact feature functions (phone and email)."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("phone_standardize")
def phone_standardize(inputs: list[str], **_: Any) -> str:
    """Normalize phone: strip non-digits, handle country codes.

    Strips leading '1' (US) or '0' (UK/EU) for consistent comparison.
    Falls back to last 10 digits for US-style numbers.
    """
    col = inputs[0]
    return (
        f"CASE "
        f"WHEN CHAR_LENGTH(REGEXP_REPLACE({col}, r'[^0-9]', '')) > 10 "
        f"AND STARTS_WITH(REGEXP_REPLACE({col}, r'[^0-9]', ''), '1') "
        f"THEN RIGHT(REGEXP_REPLACE({col}, r'[^0-9]', ''), "
        f"CHAR_LENGTH(REGEXP_REPLACE({col}, r'[^0-9]', '')) - 1) "
        f"WHEN CHAR_LENGTH(REGEXP_REPLACE({col}, r'[^0-9]', '')) > 10 "
        f"AND STARTS_WITH(REGEXP_REPLACE({col}, r'[^0-9]', ''), '0') "
        f"THEN RIGHT(REGEXP_REPLACE({col}, r'[^0-9]', ''), "
        f"CHAR_LENGTH(REGEXP_REPLACE({col}, r'[^0-9]', '')) - 1) "
        f"ELSE RIGHT(REGEXP_REPLACE({col}, r'[^0-9]', ''), 10) "
        f"END"
    )


@register("phone_area_code")
def phone_area_code(inputs: list[str], **_: Any) -> str:
    """Extract area code (first 3 digits of 10-digit normalized phone)."""
    col = inputs[0]
    return f"LEFT(RIGHT(REGEXP_REPLACE({col}, r'[^0-9]', ''), 10), 3)"


@register("phone_last_four")
def phone_last_four(inputs: list[str], **_: Any) -> str:
    """Extract last 4 digits of phone number (subscriber number)."""
    col = inputs[0]
    return f"RIGHT(REGEXP_REPLACE({col}, r'[^0-9]', ''), 4)"


@register("email_domain")
def email_domain(inputs: list[str], **_: Any) -> str:
    """Extract email domain (after @).

    OUTPUT TYPE: STRING (variable length, e.g. 'gmail.com')
    PERF: For blocking, FARM_FINGERPRINT(email_domain) produces INT64 and
    avoids byte-by-byte comparison on domains like 'nationwide.com'.
    """
    return f"LOWER(REGEXP_EXTRACT({inputs[0]}, r'@(.+)$'))"


@register("email_local_part")
def email_local_part(inputs: list[str], **_: Any) -> str:
    """Extract email local part (before @)."""
    return f"LOWER(REGEXP_EXTRACT({inputs[0]}, r'^([^@]+)'))"


@register("email_domain_type")
def email_domain_type(inputs: list[str], **_: Any) -> str:
    """Classify email domain as FREE, BUSINESS, or UNKNOWN."""
    col = inputs[0]
    return (
        f"CASE "
        f"WHEN LOWER(REGEXP_EXTRACT({col}, r'@(.+)$')) IN "
        f"('gmail.com','yahoo.com','hotmail.com','outlook.com','aol.com',"
        f"'icloud.com','mail.com','protonmail.com','live.com','msn.com') "
        f"THEN 'FREE' "
        f"WHEN REGEXP_EXTRACT({col}, r'@(.+)$') IS NOT NULL THEN 'BUSINESS' "
        f"ELSE NULL END"
    )

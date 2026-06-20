"""Email intelligence feature functions.

Extract and classify email components for matching: local part, domain,
role detection, and domain categorization.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("email_local_part_safe")
def email_local_part_safe(inputs: list[str], **_: Any) -> str:
    """Extract local part (before @) from email with NULL safety.

    Returns NULL when the email is NULL or has no @ sign. More robust
    than email_local_part (in contact_features) which uses REGEXP_EXTRACT.

    OUTPUT TYPE: STRING
    When to use: Compare email usernames independently of domain.
    """
    col = inputs[0]
    return (
        f"CASE WHEN {col} IS NOT NULL AND STRPOS({col}, '@') > 0 "
        f"THEN LOWER(SUBSTR({col}, 1, STRPOS({col}, '@') - 1)) "
        f"ELSE NULL END"
    )


@register("email_domain_safe")
def email_domain_safe(inputs: list[str], **_: Any) -> str:
    """Extract domain (after @) from email with NULL safety.

    Returns NULL when the email is NULL or has no @ sign. More robust
    than email_domain (in contact_features) which uses REGEXP_EXTRACT.

    OUTPUT TYPE: STRING
    When to use: Compare or block on email domains.
    """
    col = inputs[0]
    return (
        f"CASE WHEN {col} IS NOT NULL AND STRPOS({col}, '@') > 0 "
        f"THEN LOWER(SUBSTR({col}, STRPOS({col}, '@') + 1)) "
        f"ELSE NULL END"
    )


@register("email_is_role_address")
def email_is_role_address(inputs: list[str], **_: Any) -> str:
    """Detect role-based email addresses (info@, admin@, sales@, etc.).

    Role addresses should not be used as strong match evidence since
    they represent a function, not a person.

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Downweight or exclude email matching when email is role-based.
    """
    col = inputs[0]
    return (
        f"CASE WHEN {col} IS NOT NULL AND REGEXP_CONTAINS("
        f"LOWER(SUBSTR({col}, 1, COALESCE(NULLIF(STRPOS({col}, '@'), 0) - 1, 0))), "
        f"r'^(info|admin|sales|support|contact|help|service|billing|noreply|no-reply|"
        f"webmaster|postmaster|abuse|marketing|office|hr|jobs|careers|press|media|"
        f"team|hello|general|enquiries|inquiries)$') "
        f"THEN 1 ELSE 0 END"
    )


@register("email_domain_category")
def email_domain_category(inputs: list[str], **_: Any) -> str:
    """Categorize email domain: FREE, CORPORATE, DISPOSABLE, or GOVERNMENT.

    OUTPUT TYPE: STRING
    When to use: Adjust match evidence strength based on email category.
    Free/disposable emails provide weaker identity signal than corporate.
    """
    col = inputs[0]
    return (
        f"CASE "
        f"WHEN {col} IS NULL OR STRPOS({col}, '@') = 0 THEN NULL "
        f"WHEN REGEXP_CONTAINS(LOWER(SUBSTR({col}, STRPOS({col}, '@') + 1)), "
        f"r'^(gmail\\.com|yahoo\\.com|hotmail\\.com|outlook\\.com|aol\\.com|"
        f"icloud\\.com|mail\\.com|protonmail\\.com|zoho\\.com|yandex\\.com|"
        f"live\\.com|msn\\.com|me\\.com|gmx\\.com|inbox\\.com)$') "
        f"THEN 'FREE' "
        f"WHEN REGEXP_CONTAINS(LOWER(SUBSTR({col}, STRPOS({col}, '@') + 1)), "
        f"r'^(mailinator\\.com|guerrillamail\\.com|tempmail\\.com|throwaway\\.email|"
        f"sharklasers\\.com|dispostable\\.com|yopmail\\.com|trashmail\\.com)$') "
        f"THEN 'DISPOSABLE' "
        f"WHEN REGEXP_CONTAINS(LOWER(SUBSTR({col}, STRPOS({col}, '@') + 1)), "
        f"r'\\.(gov|mil|gov\\.[a-z]{{2}})$') "
        f"THEN 'GOVERNMENT' "
        f"ELSE 'CORPORATE' END"
    )

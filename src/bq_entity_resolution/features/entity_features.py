"""Entity classification feature functions.

Classify entities by type (person/business/org), detect name formats,
and identify multi-person records.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("entity_type_classify")
def entity_type_classify(inputs: list[str], **_: Any) -> str:
    """Classify entity as PERSON, BUSINESS, or ORGANIZATION from name patterns.

    Uses regex detection: corp suffixes (LLC, Inc, Corp, Ltd), personal titles
    (Mr, Mrs, Dr), organizational keywords (Trust, Estate, Foundation, Association).

    OUTPUT TYPE: STRING
    When to use: Entity-type-gated matching where different signal rules
    apply to personal vs business entities.
    """
    col = inputs[0]
    business_re = (
        "\\b(LLC|INC|CORP|LTD|LP|LLP|PLLC|PC|PA|COMPANY"
        "|CO|ENTERPRISES|PARTNERS|GROUP|HOLDINGS"
        "|INDUSTRIES|SERVICES|SOLUTIONS|ASSOCIATES"
        "|CONSULTING)\\b"
    )
    org_re = (
        "\\b(TRUST|ESTATE|FOUNDATION|ASSOCIATION|SOCIETY"
        "|INSTITUTE|CHURCH|MINISTRY|UNIVERSITY|COLLEGE"
        "|SCHOOL|HOSPITAL|COUNCIL|COMMISSION|AUTHORITY"
        "|BUREAU|DEPARTMENT|AGENCY|BOARD)\\b"
    )
    return (
        f"CASE "
        f"WHEN {col} IS NULL THEN NULL "
        f"WHEN REGEXP_CONTAINS(UPPER({col}), "
        f"r'{business_re}') "
        f"THEN 'BUSINESS' "
        f"WHEN REGEXP_CONTAINS(UPPER({col}), "
        f"r'{org_re}') "
        f"THEN 'ORGANIZATION' "
        f"ELSE 'PERSON' END"
    )


@register("name_format_detect")
def name_format_detect(inputs: list[str], **_: Any) -> str:
    """Detect name format: NATURAL, REVERSED, SINGLE, or COMPOUND.

    - NATURAL: "John Smith" (first last)
    - REVERSED: "Smith, John" (last comma first)
    - SINGLE: "Madonna" (one word)
    - COMPOUND: "John and Jane Smith" (multiple people)

    OUTPUT TYPE: STRING
    When to use: Pre-processing step to normalize name formats before matching.
    """
    col = inputs[0]
    return (
        f"CASE "
        f"WHEN {col} IS NULL THEN NULL "
        f"WHEN REGEXP_CONTAINS({col}, r',\\s*\\w') THEN 'REVERSED' "
        f"WHEN REGEXP_CONTAINS(UPPER({col}), r'\\b(AND|&)\\b') THEN 'COMPOUND' "
        f"WHEN ARRAY_LENGTH(SPLIT(TRIM({col}), ' ')) = 1 THEN 'SINGLE' "
        f"ELSE 'NATURAL' END"
    )


@register("is_multi_person")
def is_multi_person(inputs: list[str], **_: Any) -> str:
    """Detect multi-person patterns in a name field.

    Matches: "John and Jane", "Smith & Jones", "A/B", "John or Jane".

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag records that represent multiple people for compound
    record detection and splitting.
    """
    col = inputs[0]
    return (
        f"CASE WHEN {col} IS NULL THEN 0 "
        f"WHEN REGEXP_CONTAINS(UPPER({col}), "
        f"r'\\b(AND|&|OR)\\b|\\w\\s*/\\s*\\w') "
        f"THEN 1 ELSE 0 END"
    )

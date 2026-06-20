"""Business/DBA feature functions.

Extract and normalize business names, DBA names, and business type suffixes
for entity resolution in commercial contexts.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("dba_extract")
def dba_extract(inputs: list[str], **_: Any) -> str:
    """Extract DBA (Doing Business As) name from a business name field.

    Matches patterns: "Company DBA TradeName", "Company D/B/A TradeName",
    "Company T/A TradeName", "Company AKA TradeName".

    OUTPUT TYPE: STRING (the DBA name, or NULL if no DBA found)
    When to use: Insurance, business licensing — compare trade names independently.
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS(UPPER({col}), "
        f"r'\\b(DBA|D/B/A|T/A|AKA|A/K/A)\\b') "
        f"THEN TRIM(REGEXP_EXTRACT(UPPER({col}), "
        f"r'(?:DBA|D/B/A|T/A|AKA|A/K/A)[\\s:.\\-]*(.+)$')) "
        f"ELSE NULL END"
    )


@register("dba_normalize")
def dba_normalize(inputs: list[str], **_: Any) -> str:
    """Normalize a DBA/business name: strip type suffixes, noise words, uppercase.

    OUTPUT TYPE: STRING
    When to use: After dba_extract, normalize for fuzzy matching.
    """
    col = inputs[0]
    return (
        f"UPPER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE("
        f"REGEXP_REPLACE({col}, "
        f"r'\\b(LLC|INC|CORP|LTD|LP|LLP|PLLC|PC|PA|CO|COMPANY|THE)\\b', ''), "
        f"r'[^A-Za-z0-9 ]', ''), "
        f"r'\\s+', ' ')))"
    )


@register("business_type_extract")
def business_type_extract(inputs: list[str], **_: Any) -> str:
    """Extract business type suffix (LLC, Inc, Corp, LP, etc.).

    OUTPUT TYPE: STRING (the suffix, or NULL if none found)
    When to use: Compare business types — same entity should have same type.
    Mismatch could indicate different entities or a name change.
    """
    col = inputs[0]
    return (
        f"REGEXP_EXTRACT(UPPER({col}), "
        f"r'\\b(LLC|INC|INCORPORATED|CORP|CORPORATION|LTD|LIMITED|"
        f"LP|LLP|PLLC|PC|PA|COMPANY|CO)\\b')"
    )


@register("business_core_name")
def business_core_name(inputs: list[str], **_: Any) -> str:
    """Strip business type suffix and DBA to get core business name.

    "Acme Corp DBA Widget Co" -> "ACME"

    OUTPUT TYPE: STRING
    When to use: Fuzzy matching on the core business identity.
    """
    col = inputs[0]
    return (
        f"UPPER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE("
        f"UPPER({col}), "
        f"r'\\b(DBA|D/B/A|T/A|AKA|A/K/A)\\s+.+$', ''), "
        f"r'\\b(LLC|INC|INCORPORATED|CORP|CORPORATION|LTD|LIMITED|"
        f"LP|LLP|PLLC|PC|PA|COMPANY|CO|THE)\\b', ''), "
        f"r'[^A-Z0-9 ]', '')))"
    )

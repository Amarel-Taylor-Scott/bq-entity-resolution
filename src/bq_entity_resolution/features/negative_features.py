"""Hard-negative flag extraction feature functions.

Extract signals that indicate two records likely refer to different entities
despite superficial similarities: generational suffixes, roman numerals,
HOA/trust/c/o patterns, numbered entity suffixes, geographic qualifiers.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register


@register("extract_generational_suffix")
def extract_generational_suffix(inputs: list[str], **_: Any) -> str:
    """Extract generational suffix from a name (Jr, Sr, II, III, IV, V).

    OUTPUT TYPE: STRING (suffix or NULL)
    When to use: Different generational suffixes on otherwise identical names
    is a strong hard negative signal (father vs son).
    """
    col = inputs[0]
    return (
        f"REGEXP_EXTRACT(UPPER({col}), "
        f"r'\\b(JR|SR|JUNIOR|SENIOR|II|III|IV|V|VI|VII|VIII|2ND|3RD|4TH)\\b')"
    )


@register("extract_roman_numeral")
def extract_roman_numeral(inputs: list[str], **_: Any) -> str:
    """Extract standalone roman numeral from a name or entity identifier.

    Requires at least 2 characters to avoid false positives on single-letter
    middle initials (I, V). Matches II through XII.

    OUTPUT TYPE: STRING (numeral or NULL)
    When to use: Roman numerals in business names (e.g., "Phase II" vs "Phase III")
    indicate different entities.
    """
    col = inputs[0]
    return (
        f"REGEXP_EXTRACT(UPPER({col}), "
        f"r'\\b(II|III|IV|VI|VII|VIII|IX|XI|XII)\\b')"
    )


@register("is_hoa_trust_careof")
def is_hoa_trust_careof(inputs: list[str], **_: Any) -> str:
    """Detect HOA, Trust, C/O, ATTN, FBO patterns in a name field.

    These patterns indicate the name is not a direct entity identifier
    but a reference to another entity or relationship.

    OUTPUT TYPE: INT64 (0 or 1)
    When to use: Flag records that should not match against regular person/business
    names — matching "John Smith C/O ABC Corp" against "John Smith" requires caution.
    """
    col = inputs[0]
    return (
        f"CASE WHEN REGEXP_CONTAINS(UPPER({col}), "
        f"r'\\b(HOA|HOMEOWNERS|HOME OWNERS|TRUST|TRUSTEE|ESTATE OF|"
        f"C/O|CARE OF|ATTN|ATTENTION|FBO|FOR BENEFIT OF|"
        f"AS AGENT|AS TRUSTEE|AS CUSTODIAN|POA|POWER OF ATTORNEY)\\b') "
        f"THEN 1 ELSE 0 END"
    )


@register("extract_numbered_entity_suffix")
def extract_numbered_entity_suffix(inputs: list[str], **_: Any) -> str:
    """Extract numbered entity suffix like '#123', 'Unit 5', 'Suite 200'.

    OUTPUT TYPE: STRING (the number or NULL)
    When to use: "ABC Corp #1" vs "ABC Corp #2" are different entities.
    Different numbered suffixes on the same base name is a hard negative.
    """
    col = inputs[0]
    return (
        f"REGEXP_EXTRACT(UPPER({col}), "
        f"r'(?:#|NO\\.?|NUM(?:BER)?\\.?|UNIT|SUITE|STE|APT|BLDG|BUILDING)\\s*(\\d+)')"
    )


@register("geographic_qualifier")
def geographic_qualifier(inputs: list[str], **_: Any) -> str:
    """Extract geographic qualifier from a name (North, South, East, West, Central).

    OUTPUT TYPE: STRING (qualifier or NULL)
    When to use: "First National Bank North" vs "First National Bank South"
    are different branches. Geographic qualifiers are hard negative signals.
    """
    col = inputs[0]
    return (
        f"REGEXP_EXTRACT(UPPER({col}), "
        f"r'\\b(NORTH|SOUTH|EAST|WEST|CENTRAL|NORTHEAST|NORTHWEST|"
        f"SOUTHEAST|SOUTHWEST|NORTHERN|SOUTHERN|EASTERN|WESTERN)\\b')"
    )

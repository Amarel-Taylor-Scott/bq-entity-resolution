"""Centralized constants for compound record detection.

These constants define the patterns used to identify compound records —
entries that represent multiple individuals rather than one person.
"""

from __future__ import annotations

# Conjunctions that join two names: "Jane AND Joe", "Mr. & Mrs."
CONJUNCTIONS: tuple[str, ...] = ("AND", "&", "+")

# Title prefixes commonly seen in compound records
TITLE_PREFIXES: tuple[str, ...] = (
    "MR", "MRS", "MS", "MISS", "DR", "PROF", "REV",
)

# Suffixes indicating a family/household record
FAMILY_SUFFIXES: tuple[str, ...] = ("FAMILY", "HOUSEHOLD", "RESIDENCE")

# Regex fragments (BigQuery RE2 syntax) used in SQL generation
CONJUNCTION_RE = r"\b(AND|&|\+)\b"
TITLE_PAIR_RE = r"\b(MR|MRS|MS|DR)\.?\s*(AND|&)\s*(MR|MRS|MS|DR)\.?"
FAMILY_RE = r"^THE\s+\w+\s+FAMILY$"
SLASH_RE = r"\w+\s*/\s*\w+"

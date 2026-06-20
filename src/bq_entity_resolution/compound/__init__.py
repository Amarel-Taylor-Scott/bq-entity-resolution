"""Compound record detection and splitting.

Detects records that represent multiple people (e.g., "Mr. and Mrs. Smith",
"Jane and Joe Smith", "The Johnson Family") and optionally splits them into
individual rows.
"""

from __future__ import annotations

from bq_entity_resolution.compound.detector import CompoundDetector
from bq_entity_resolution.compound.patterns import (
    CONJUNCTIONS,
    FAMILY_SUFFIXES,
    TITLE_PREFIXES,
)
from bq_entity_resolution.compound.splitter import CompoundSplitter

__all__ = [
    "CompoundDetector",
    "CompoundSplitter",
    "CONJUNCTIONS",
    "FAMILY_SUFFIXES",
    "TITLE_PREFIXES",
]

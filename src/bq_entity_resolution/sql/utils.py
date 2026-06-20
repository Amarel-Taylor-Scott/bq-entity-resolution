"""Shared SQL utility functions.

Common SQL escaping, identifier validation, and safe column reference
helpers used across builders and comparison functions.
"""

from __future__ import annotations

import re
from typing import Any

from bq_entity_resolution.constants import BQ_RESERVED_WORDS

# Valid BQ identifier: letters, digits, underscores only
_VALID_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# Valid table reference: project.dataset.table with optional hyphens in project
_VALID_TABLE_REF = re.compile(r'^[a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$')

# Unified safe value pattern: alphanumeric, underscore, hyphen, dot, colon,
# slash, plus, T, space. Covers timestamps (including millisecond precision
# like 2024-01-01T00:00:00.123Z), ISO dates, paths, run IDs.
_SAFE_VALUE_RE = re.compile(r'^[\w.:/+\-T Z]+$')


def sql_escape(value: object) -> str:
    """Escape single quotes for SQL string literals."""
    return str(value).replace("'", "''")


def bq_escape(identifier: str) -> str:
    """Backtick-escape a BigQuery identifier if reserved or contains special chars."""
    if identifier.upper() in BQ_RESERVED_WORDS or "." in identifier or "-" in identifier:
        return f"`{identifier}`"
    return identifier


def validate_identifier(name: str, context: str = "identifier") -> str:
    """Validate that a string is a safe SQL identifier.

    Rejects names containing SQL injection characters (quotes, semicolons,
    comments, etc.). Returns the name unchanged if valid.

    Raises ValueError if the name contains unsafe characters.
    """
    if not _VALID_IDENTIFIER.match(name):
        raise ValueError(
            f"Invalid SQL {context}: {name!r}. "
            f"Identifiers must contain only letters, digits, and underscores."
        )
    return name


def validate_table_ref(name: str) -> str:
    """Validate that a string is a safe fully-qualified table reference.

    Expected format: project.dataset.table or `project.dataset.table`.

    Raises ValueError if the format is invalid.
    """
    # Strip backtick quoting
    clean = name.strip('`')
    if not _VALID_TABLE_REF.match(clean):
        raise ValueError(
            f"Invalid table reference: {name!r}. "
            f"Expected format: project.dataset.table"
        )
    return name


def validate_safe_value(value: str, label: str = "value") -> str:
    """Validate and escape a string for safe SQL interpolation.

    Unified sanitization for watermark values, run IDs, stage names,
    and other user-supplied strings embedded in SQL literals.

    Returns the value with single quotes escaped (ANSI ``''``).

    Raises ValueError if the value contains characters outside the
    safe set (alphanumeric, underscore, hyphen, dot, colon, slash,
    plus, T, space).
    """
    if not _SAFE_VALUE_RE.match(value):
        raise ValueError(
            f"Unsafe characters in {label}: {value!r}. "
            f"Only alphanumeric, underscore, hyphen, dot, colon, "
            f"slash, plus, T, and space are allowed."
        )
    return value.replace("'", "''")


def format_watermark_value(val: Any) -> str:
    """Format a watermark value for safe SQL embedding.

    Handles NULL, numeric, timestamp, and string values with strict
    validation against injection vectors.

    Returns a SQL literal string (e.g., ``42``, ``'active'``,
    ``TIMESTAMP('2024-01-01T00:00:00')``).
    """
    if val is None:
        return "NULL"
    s = str(val)
    try:
        float(s)
        return s
    except (ValueError, TypeError):
        pass
    safe = validate_safe_value(s, "watermark value")
    if "T" in s or ("-" in s and ":" in s):
        return f"TIMESTAMP('{safe}')"
    return f"'{safe}'"


def safe_col(side: str, name: str) -> str:
    """Generate a validated column reference for SQL (e.g., ``l.first_name``).

    Validates that ``name`` is a safe SQL identifier and ``side`` is
    one of ``l`` or ``r`` (left/right table alias).

    This is the single entry point for all comparison and builder code
    that interpolates column names into SQL.

    Raises ValueError if the column name contains unsafe characters.
    """
    if side not in ("l", "r"):
        raise ValueError(f"side must be 'l' or 'r', got {side!r}")
    validate_identifier(name, context="column name")
    return f"{side}.{name}"


def null_check(left: str, right: str) -> str:
    """Generate a NOT NULL guard for a left/right column pair.

    Returns SQL fragment: ``l.{left} IS NOT NULL AND r.{right} IS NOT NULL``
    with both column names validated.
    """
    return f"{safe_col('l', left)} IS NOT NULL AND {safe_col('r', right)} IS NOT NULL"

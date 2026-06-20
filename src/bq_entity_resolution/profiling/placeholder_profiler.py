"""Placeholder profiler: scan source data to recommend custom placeholder patterns.

Generates SQL that counts values matching known placeholder patterns per column,
plus top-N frequency analysis for suspected new placeholders (high-frequency,
low-cardinality values that might be non-informative).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_identifier, validate_table_ref

logger = logging.getLogger(__name__)


@dataclass
class PlaceholderFinding:
    """A single placeholder detection finding."""

    column_name: str
    value: str
    count: int
    pattern_type: str  # "known" or "suspected"
    suggestion: str = ""


@dataclass
class PlaceholderProfileResult:
    """Complete profiling result for a source table."""

    source_table: str
    findings: list[PlaceholderFinding] = field(default_factory=list)
    yaml_snippet: str = ""


# Maps role names to detection function names
_ROLE_TO_DETECTION: dict[str, str] = {
    "phone": "is_placeholder_phone",
    "mobile_phone": "is_placeholder_phone",
    "home_phone": "is_placeholder_phone",
    "work_phone": "is_placeholder_phone",
    "email": "is_placeholder_email",
    "personal_email": "is_placeholder_email",
    "work_email": "is_placeholder_email",
    "first_name": "is_placeholder_name",
    "last_name": "is_placeholder_name",
    "middle_name": "is_placeholder_name",
    "full_name": "is_placeholder_name",
    "address_line_1": "is_placeholder_address",
    "address_line_2": "is_placeholder_address",
    "ssn": "is_placeholder_ssn",
    "tin": "is_placeholder_ssn",
}


class PlaceholderProfiler:
    """Scan source data and recommend custom placeholder patterns."""

    def __init__(self, backend: Any):
        self.backend = backend

    def build_known_pattern_sql(
        self,
        source_table: str,
        columns_with_roles: list[tuple[str, str]],
    ) -> SQLExpression | None:
        """Generate SQL to count values matching known placeholder patterns.

        Args:
            source_table: Fully-qualified source table.
            columns_with_roles: List of (column_name, role) tuples.

        Returns:
            SQLExpression or None if no detectable columns.
        """
        validate_table_ref(source_table)

        union_parts: list[str] = []
        for col_name, role in columns_with_roles:
            validate_identifier(col_name, context="profiling column")
            fn_name = _ROLE_TO_DETECTION.get(role)
            if not fn_name:
                continue
            func = FEATURE_FUNCTIONS.get(fn_name)
            if func is None:
                continue
            try:
                detection_sql = func([col_name])
            except Exception:
                continue

            escaped_col = sql_escape(col_name)
            escaped_role = sql_escape(role)
            part = (
                f"SELECT\n"
                f"  '{escaped_col}' AS column_name,\n"
                f"  CAST({col_name} AS STRING) AS value,\n"
                f"  COUNT(*) AS match_count,\n"
                f"  '{escaped_role}' AS role,\n"
                f"  'known' AS pattern_type\n"
                f"FROM `{source_table}`\n"
                f"WHERE {detection_sql} = 1\n"
                f"  AND {col_name} IS NOT NULL\n"
                f"GROUP BY {col_name}\n"
                f"HAVING COUNT(*) >= 2"
            )
            union_parts.append(part)

        if not union_parts:
            return None

        sql = "\nUNION ALL\n".join(union_parts)
        sql += "\nORDER BY match_count DESC"
        return SQLExpression.from_raw(sql)

    def build_suspected_pattern_sql(
        self,
        source_table: str,
        columns: list[str],
        top_n: int = 20,
    ) -> SQLExpression:
        """Generate SQL to find high-frequency values that may be placeholders.

        Looks for values that appear disproportionately often (>0.1% of total
        records) which might be non-informative data worth investigating.
        """
        validate_table_ref(source_table)

        union_parts: list[str] = []
        for col in columns:
            validate_identifier(col, context="profiling column")
            escaped_col = sql_escape(col)
            part = (
                f"SELECT\n"
                f"  '{escaped_col}' AS column_name,\n"
                f"  CAST({col} AS STRING) AS value,\n"
                f"  COUNT(*) AS match_count,\n"
                f"  SAFE_DIVIDE(COUNT(*),"
                f" (SELECT COUNT(*) FROM `{source_table}`))"
                f" AS frequency_ratio\n"
                f"FROM `{source_table}`\n"
                f"WHERE {col} IS NOT NULL\n"
                f"GROUP BY {col}\n"
                f"HAVING COUNT(*) >= 10\n"
                f"  AND SAFE_DIVIDE(COUNT(*),"
                f" (SELECT COUNT(*) FROM `{source_table}`)) > 0.001\n"
                f"ORDER BY match_count DESC\n"
                f"LIMIT {int(top_n)}"
            )
            union_parts.append(part)

        sql = "\nUNION ALL\n".join(union_parts)
        return SQLExpression.from_raw(sql)

    def analyze_results(
        self,
        known_rows: list[dict[str, Any]],
        suspected_rows: list[dict[str, Any]],
    ) -> list[PlaceholderFinding]:
        """Process query results into PlaceholderFinding objects."""
        findings: list[PlaceholderFinding] = []

        for row in known_rows:
            findings.append(PlaceholderFinding(
                column_name=row.get("column_name", ""),
                value=row.get("value", ""),
                count=int(row.get("match_count", 0)),
                pattern_type="known",
                suggestion=(
                    f"Already detected by built-in {row.get('role', '')} pattern"
                ),
            ))

        known_values = {(f.column_name, f.value) for f in findings}

        for row in suspected_rows:
            col = row.get("column_name", "")
            val = row.get("value", "")
            if (col, val) in known_values:
                continue
            freq = float(row.get("frequency_ratio", 0))
            findings.append(PlaceholderFinding(
                column_name=col,
                value=val,
                count=int(row.get("match_count", 0)),
                pattern_type="suspected",
                suggestion=(
                    f"High frequency ({freq:.2%}) — consider adding to "
                    f"custom_patterns if non-informative"
                ),
            ))

        return findings

    def generate_yaml_snippet(self, findings: list[PlaceholderFinding]) -> str:
        """Generate recommended YAML config for custom_patterns."""
        by_column: dict[str, list[str]] = {}
        for f in findings:
            if f.pattern_type == "suspected":
                by_column.setdefault(f.column_name, []).append(f.value)

        if not by_column:
            return "# No additional custom patterns recommended."

        lines = ["feature_engineering:", "  placeholder:", "    custom_patterns:"]
        for col, values in sorted(by_column.items()):
            lines.append(f"      {col}:")
            lines.append(f"        name: {col}_custom")
            lines.append("        values:")
            for v in values[:10]:
                lines.append(f'          - "{v}"')
        return "\n".join(lines)

    def format_report(self, findings: list[PlaceholderFinding]) -> str:
        """Format findings into a human-readable report."""
        lines = ["Placeholder Profiling Report", "=" * 60]

        known = [f for f in findings if f.pattern_type == "known"]
        suspected = [f for f in findings if f.pattern_type == "suspected"]

        if known:
            lines.append(f"\nKnown Placeholders ({len(known)} found):")
            for f in known[:20]:
                lines.append(
                    f"  {f.column_name}: '{f.value}' (count={f.count:,})"
                )

        if suspected:
            lines.append(f"\nSuspected Placeholders ({len(suspected)} found):")
            for f in suspected[:20]:
                lines.append(
                    f"  {f.column_name}: '{f.value}'"
                    f" (count={f.count:,}) — {f.suggestion}"
                )

        if not known and not suspected:
            lines.append("\nNo placeholder values detected.")

        return "\n".join(lines)

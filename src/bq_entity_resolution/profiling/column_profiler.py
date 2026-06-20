"""Column profiler: data-driven weight initialization.

Computes column statistics (cardinality, null rate, value distribution)
from BigQuery source data and derives principled comparison weights
using information content: weight = log2(m / u).

This eliminates trial-and-error weight tuning by grounding weights
in actual data distributions. No labeled data required.

All computation runs in BigQuery — no data leaves the warehouse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnProfile:
    """Statistical profile of a single column."""

    column_name: str
    cardinality: int = 0
    total_rows: int = 0
    null_count: int = 0
    null_rate: float = 0.0
    avg_frequency: float = 0.0
    max_frequency: int = 0
    top_values: list[tuple[str, int]] = field(default_factory=list)

    @property
    def suggested_u(self) -> float:
        """P(coincidental match) ≈ 1/cardinality for exact match.

        Floor at 1e-9 prevents log(0) while preserving ordering
        across high-cardinality columns (SSN > email > name).
        """
        if self.cardinality <= 0:
            return 1.0
        return max(1e-9, min(0.999, 1.0 / self.cardinality))

    @property
    def suggested_m(self) -> float:
        """P(agreement | true match) ≈ 1 - null_rate."""
        return max(0.001, min(0.999, 1.0 - self.null_rate))

    @property
    def suggested_weight(self) -> float:
        """Information content in bits: log2(m/u)."""
        return round(math.log2(self.suggested_m / self.suggested_u), 2)

    @property
    def discriminative_power(self) -> str:
        """Classify column discriminative power."""
        w = self.suggested_weight
        if w >= 10:
            return "HIGH"
        if w >= 5:
            return "MEDIUM"
        return "LOW"


class ColumnProfiler:
    """Generates SQL to profile columns and derives comparison weights."""

    def generate_profile_sql(self, table: str, columns: list[str]) -> str:
        """Generate a single BigQuery SQL query that profiles all columns.

        Returns one row per column with cardinality, null count, total rows,
        average frequency, and max frequency.
        """
        from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref

        validate_table_ref(table)
        for col in columns:
            validate_identifier(col, context="profiling column")
        unions = []
        for col in columns:
            unions.append(
                f"SELECT\n"
                f"  '{col}' AS column_name,\n"
                f"  COUNT(DISTINCT {col}) AS cardinality,\n"
                f"  COUNT(*) AS total_rows,\n"
                f"  COUNTIF({col} IS NULL) AS null_count,\n"
                f"  SAFE_DIVIDE(COUNT(*), NULLIF(COUNT(DISTINCT {col}), 0))"
                f" AS avg_frequency,\n"
                f"  (SELECT COUNT(*) FROM `{table}` GROUP BY {col}"
                f" ORDER BY COUNT(*) DESC LIMIT 1) AS max_frequency\n"
                f"FROM `{table}`"
            )
        return "\nUNION ALL\n".join(unions)

    def generate_top_values_sql(
        self, table: str, column: str, top_k: int = 10
    ) -> str:
        """Generate SQL to get top-K most frequent values for a column."""
        from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref

        validate_table_ref(table)
        validate_identifier(column, context="profiling column")
        return (
            f"SELECT CAST({column} AS STRING) AS value, COUNT(*) AS freq\n"
            f"FROM `{table}`\n"
            f"WHERE {column} IS NOT NULL\n"
            f"GROUP BY {column}\n"
            f"ORDER BY freq DESC\n"
            f"LIMIT {top_k}"
        )

    def parse_profile_results(self, rows: list[dict[str, Any]]) -> list[ColumnProfile]:
        """Parse BigQuery result rows into ColumnProfile objects."""
        profiles = []
        for row in rows:
            total = row.get("total_rows", 0) or 0
            null_count = row.get("null_count", 0) or 0
            profiles.append(ColumnProfile(
                column_name=row["column_name"],
                cardinality=row.get("cardinality", 0) or 0,
                total_rows=total,
                null_count=null_count,
                null_rate=null_count / total if total > 0 else 0.0,
                avg_frequency=row.get("avg_frequency", 0.0) or 0.0,
                max_frequency=row.get("max_frequency", 0) or 0,
            ))
        return profiles

    def suggest_weights(
        self, profiles: list[ColumnProfile]
    ) -> dict[str, float]:
        """Return {column_name: suggested_weight} based on information content."""
        return {p.column_name: p.suggested_weight for p in profiles}

    def suggest_comparisons(
        self, profiles: list[ColumnProfile]
    ) -> list[dict[str, Any]]:
        """Suggest comparison methods based on column profile.

        High cardinality → exact match (identifiers).
        Medium cardinality → fuzzy match (names).
        Low cardinality → exact match but low weight (state, gender).
        """
        suggestions = []
        for p in profiles:
            if p.cardinality == 0:
                continue

            # High cardinality: identifier-like columns
            if p.cardinality > 10000:
                suggestions.append({
                    "column": p.column_name,
                    "method": "exact",
                    "weight": p.suggested_weight,
                    "rationale": (
                        f"High cardinality ({p.cardinality:,}) — "
                        f"exact match provides {p.suggested_weight:.1f} bits of evidence"
                    ),
                    "discriminative_power": p.discriminative_power,
                })
            # Medium cardinality: name-like columns
            elif p.cardinality > 100:
                suggestions.append({
                    "column": p.column_name,
                    "method": "jaro_winkler",
                    "weight": p.suggested_weight,
                    "rationale": (
                        f"Medium cardinality ({p.cardinality:,}) — "
                        f"fuzzy match recommended, {p.suggested_weight:.1f} bits"
                    ),
                    "discriminative_power": p.discriminative_power,
                })
            # Low cardinality: categorical columns
            else:
                suggestions.append({
                    "column": p.column_name,
                    "method": "exact",
                    "weight": p.suggested_weight,
                    "rationale": (
                        f"Low cardinality ({p.cardinality:,}) — "
                        f"exact match, weak discriminator ({p.suggested_weight:.1f} bits)"
                    ),
                    "discriminative_power": p.discriminative_power,
                })

            # Warn about high null rate
            if p.null_rate > 0.3:
                suggestions[-1]["warning"] = (
                    f"High null rate ({p.null_rate:.0%}) — "
                    f"consider null handling strategy"
                )

        return suggestions

    def format_report(self, profiles: list[ColumnProfile]) -> str:
        """Format profiles into a human-readable report."""
        lines = ["Column Profiling Report", "=" * 60]

        for p in profiles:
            lines.append(f"\n{p.column_name}:")
            lines.append(f"  Cardinality:    {p.cardinality:>12,}")
            lines.append(f"  Null rate:      {p.null_rate:>12.1%}")
            lines.append(f"  Avg frequency:  {p.avg_frequency:>12.1f}")
            lines.append(f"  Max frequency:  {p.max_frequency:>12,}")
            lines.append(f"  Suggested u:    {p.suggested_u:>12.6f}")
            lines.append(f"  Suggested m:    {p.suggested_m:>12.6f}")
            lines.append(f"  Suggested wt:   {p.suggested_weight:>12.2f} bits")
            lines.append(f"  Discriminative:  {p.discriminative_power:>11}")

        lines.append("\n" + "=" * 60)
        lines.append("Weight interpretation:")
        lines.append("  HIGH (>=10 bits):  Strong identifier (SSN, email, policy#)")
        lines.append("  MEDIUM (5-10 bits): Good discriminator (name, DOB, phone)")
        lines.append("  LOW (<5 bits):     Weak discriminator (state, city, gender)")

        return "\n".join(lines)

"""CompoundDetector: generates BigQuery SQL for compound record detection.

This class wraps the compound detection feature functions and provides
a structured API for generating detection expressions and filter clauses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.compound.patterns import (
    CONJUNCTION_RE,
    FAMILY_RE,
    SLASH_RE,
    TITLE_PAIR_RE,
)


@dataclass
class CompoundDetectionConfig:
    """Configuration for the CompoundDetector.

    This is a lightweight dataclass for the detector itself.
    The Pydantic config model in config/models/features.py handles
    validation and YAML parsing.
    """

    name_column: str = "first_name"
    last_name_column: str = "last_name"
    flag_column: str = "is_compound_name"
    custom_patterns: list[str] = field(default_factory=list)


class CompoundDetector:
    """Generates BigQuery SQL expressions for compound record detection."""

    def __init__(self, config: CompoundDetectionConfig | None = None):
        self.config = config or CompoundDetectionConfig()

    def detection_expression(self, name_col: str | None = None) -> str:
        """Generate a 0/1 INT64 expression that detects compound names.

        Args:
            name_col: Column to check. Defaults to config.name_column.

        Returns:
            A BigQuery CASE expression returning 1 for compounds.
        """
        col = name_col or self.config.name_column
        conditions = [
            f"REGEXP_CONTAINS(UPPER({col}), r'{CONJUNCTION_RE}')",
            f"REGEXP_CONTAINS(UPPER({col}), r'{TITLE_PAIR_RE}')",
            f"REGEXP_CONTAINS(UPPER({col}), r'{FAMILY_RE}')",
            f"REGEXP_CONTAINS({col}, r'{SLASH_RE}')",
        ]
        for pat in self.config.custom_patterns:
            conditions.append(f"REGEXP_CONTAINS(UPPER({col}), r'{pat}')")

        or_clause = " OR ".join(conditions)
        return f"CASE WHEN {or_clause} THEN 1 ELSE 0 END"

    def pattern_expression(self, name_col: str | None = None) -> str:
        """Generate a STRING expression classifying the compound type.

        Returns one of: 'title_pair', 'family', 'slash', 'conjunction', NULL.
        """
        col = name_col or self.config.name_column
        return (
            "CASE "
            f"WHEN REGEXP_CONTAINS(UPPER({col}), r'{TITLE_PAIR_RE}') "
            "THEN 'title_pair' "
            f"WHEN REGEXP_CONTAINS(UPPER({col}), r'{FAMILY_RE}') "
            "THEN 'family' "
            f"WHEN REGEXP_CONTAINS({col}, r'{SLASH_RE}') "
            "THEN 'slash' "
            f"WHEN REGEXP_CONTAINS(UPPER({col}), r'{CONJUNCTION_RE}') "
            "THEN 'conjunction' "
            "ELSE NULL END"
        )

    def detection_columns(self, name_col: str | None = None) -> dict[str, str]:
        """Return {column_name: sql_expression} for all compound detection columns.

        Returns:
            Dict with flag column and pattern column expressions.
        """
        col = name_col or self.config.name_column
        return {
            self.config.flag_column: self.detection_expression(col),
            "compound_pattern": self.pattern_expression(col),
        }

    def filter_sql(self, alias: str = "") -> str:
        """Generate a WHERE clause fragment to exclude compound records.

        Args:
            alias: Table alias prefix (e.g., "t" produces "t.is_compound_name").

        Returns:
            SQL fragment like "alias.is_compound_name = 0 OR alias.is_compound_name IS NULL".
        """
        prefix = f"{alias}." if alias else ""
        flag = self.config.flag_column
        return f"({prefix}{flag} = 0 OR {prefix}{flag} IS NULL)"

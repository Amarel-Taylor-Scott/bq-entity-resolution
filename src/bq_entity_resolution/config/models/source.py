"""
Source-related configuration models.

Defines the schema for source tables, column mappings, and join
configurations that feed entities into the pipeline.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from bq_entity_resolution.sql.utils import validate_identifier

__all__ = [
    "ColumnMapping",
    "JoinConfig",
    "SourceConfig",
]

# Valid BigQuery column types
_VALID_BQ_TYPES = frozenset({
    "STRING", "BYTES", "INT64", "INTEGER", "FLOAT64", "FLOAT",
    "NUMERIC", "BIGNUMERIC", "DECIMAL", "BIGDECIMAL",
    "BOOL", "BOOLEAN", "TIMESTAMP", "DATE", "TIME", "DATETIME",
    "GEOGRAPHY", "JSON", "STRUCT", "ARRAY", "RECORD",
})


class ColumnMapping(BaseModel):
    """Maps a source column to a semantic role for automatic feature engineering."""

    name: str
    type: str = "STRING"
    role: str | None = None  # first_name, last_name, address_line_1, etc.
    nullable: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name_identifier(cls, v: str) -> str:
        validate_identifier(v, context="column mapping name")
        return v

    @field_validator("type")
    @classmethod
    def _valid_bq_type(cls, v: str) -> str:
        base = v.split("<")[0].split("(")[0].strip().upper()
        if base not in _VALID_BQ_TYPES:
            raise ValueError(
                f"Unknown BigQuery type: {v!r}. "
                f"Valid types: {', '.join(sorted(_VALID_BQ_TYPES))}"
            )
        return v


_SQL_INJECTION_PATTERN = re.compile(
    r";\s*|--\s|/\*|\bDROP\b|\bALTER\b|\bCREATE\b|\bTRUNCATE\b|\bGRANT\b|\bREVOKE\b",
    re.IGNORECASE,
)


class JoinConfig(BaseModel):
    """Defines how to join a supplemental source to the primary source."""

    table: str
    alias: str = ""
    on: str  # SQL join condition
    type: Literal["LEFT", "INNER"] = "LEFT"

    @field_validator("table")
    @classmethod
    def _validate_table(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("join table must be a non-empty string")
        if "${" not in v:
            parts = v.replace("`", "").split(".")
            if len(parts) > 3:
                raise ValueError(f"join table must be project.dataset.table format, got: {v!r}")
        return v

    @field_validator("alias")
    @classmethod
    def _validate_alias(cls, v: str) -> str:
        if v:
            validate_identifier(v, context="join alias")
        return v

    @field_validator("on")
    @classmethod
    def _validate_on(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("join ON condition must be a non-empty string")
        if _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "join ON condition contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v


class SourceConfig(BaseModel):
    """A source table that feeds entities into the pipeline."""

    name: str
    table: str
    unique_key: str
    updated_at: str
    partition_column: str | None = None
    columns: list[ColumnMapping]
    passthrough_columns: list[str] = Field(default_factory=list)
    joins: list[JoinConfig] = Field(default_factory=list)
    filter: str | None = None  # optional WHERE clause fragment
    entity_type: str | None = None  # e.g. "Person", "Organization"
    entity_type_column: str | None = None
    batch_size: int = 2_000_000

    @field_validator("table")
    @classmethod
    def _validate_table_format(cls, v: str) -> str:
        """Validate table reference format (project.dataset.table or dataset.table)."""
        if not v or not v.strip():
            raise ValueError("table must be a non-empty string")
        # Allow env var placeholders like ${BQ_PROJECT}.dataset.table
        if "${" in v:
            return v  # Skip validation for env var interpolated values
        parts = v.split(".")
        if len(parts) > 3:
            raise ValueError(
                f"table must be in format 'project.dataset.table' or 'dataset.table', "
                f"got '{v}' ({len(parts)} parts)"
            )
        return v

    @field_validator("name", "unique_key", "updated_at")
    @classmethod
    def _validate_safe_identifier(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        validate_identifier(v, context="source field")
        return v

    @field_validator("passthrough_columns")
    @classmethod
    def _validate_passthrough_columns(cls, v: list[str]) -> list[str]:
        for col in v:
            validate_identifier(col, context="passthrough column")
        return v

    @field_validator("partition_column")
    @classmethod
    def _validate_partition_column(cls, v: str | None) -> str | None:
        if v:
            validate_identifier(v, context="partition column")
        return v

    @field_validator("entity_type_column")
    @classmethod
    def _validate_entity_type_column(cls, v: str | None) -> str | None:
        if v:
            validate_identifier(v, context="entity_type_column")
        return v

    @field_validator("filter")
    @classmethod
    def _validate_filter_safe(cls, v: str | None) -> str | None:
        if v is not None and _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "filter expression contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v

    @field_validator("batch_size")
    @classmethod
    def _positive_batch_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("batch_size must be >= 1")
        if v > 100_000_000:
            raise ValueError(
                f"batch_size must be <= 100,000,000, got {v:,}"
            )
        return v

    @field_validator("columns")
    @classmethod
    def unique_column_names(cls, v: list[ColumnMapping]) -> list[ColumnMapping]:
        names = [c.name for c in v]
        dupes = [n for n in names if names.count(n) > 1]
        if dupes:
            raise ValueError(f"Duplicate column names: {set(dupes)}")
        return v

    @model_validator(mode="after")
    def _validate_column_names(self) -> SourceConfig:
        """Validate that column names are safe SQL identifiers."""
        from bq_entity_resolution.sql.utils import validate_identifier
        for col in self.columns:
            try:
                validate_identifier(col.name, "column name")
            except ValueError as e:
                raise ValueError(str(e)) from e
        return self

    @classmethod
    def from_table(
        cls,
        table: str,
        backend: Any = None,
        unique_key: str = "id",
        updated_at: str = "updated_at",
        name: str | None = None,
        exclude_columns: set[str] | None = None,
        auto_roles: bool = True,
    ) -> SourceConfig:
        """Create a SourceConfig by discovering columns from a live table.

        Auto-detects column types from BigQuery INFORMATION_SCHEMA and
        assigns semantic roles from column names. Reduces boilerplate when
        setting up new sources.

        Args:
            table: Fully-qualified BigQuery table (project.dataset.table).
            backend: A Backend instance (BigQuery or DuckDB) for schema
                introspection. If None, columns must be provided manually.
            unique_key: Primary key column name.
            updated_at: Timestamp column for incremental processing.
            name: Source name (derived from table if not set).
            exclude_columns: Column names to skip (e.g. internal audit cols).
            auto_roles: If True, auto-detect roles from column names.

        Example:
            from bq_entity_resolution.backends.bigquery import BigQueryBackend
            backend = BigQueryBackend(project="my-project")
            source = SourceConfig.from_table(
                "my-project.raw.customers",
                backend=backend,
            )
        """
        from bq_entity_resolution.config.roles import detect_role

        if not name:
            name = table.rsplit(".", 1)[-1]

        exclude = exclude_columns or set()

        columns: list[ColumnMapping] = []
        partition_col = None

        if backend is not None:
            schema = backend.get_table_schema(table)
            for col_def in schema.columns:
                if col_def.name in exclude:
                    continue
                role = detect_role(col_def.name) if auto_roles else None
                columns.append(ColumnMapping(
                    name=col_def.name,
                    type=col_def.type,
                    role=role,
                    nullable=col_def.nullable,
                ))
                # Auto-detect partition column
                if col_def.type in ("TIMESTAMP", "DATE", "DATETIME"):
                    if col_def.name == updated_at:
                        partition_col = col_def.name
        else:
            raise ValueError(
                "backend is required for SourceConfig.from_table(). "
                "Pass a BigQueryBackend or DuckDBBackend instance."
            )

        return cls(
            name=name,
            table=table,
            unique_key=unique_key,
            updated_at=updated_at,
            partition_column=partition_col,
            columns=columns,
        )

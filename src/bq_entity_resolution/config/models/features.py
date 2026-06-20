"""
Feature engineering configuration models.

Defines feature definitions, feature groups, blocking/composite keys,
enrichment joins, and the top-level feature engineering config.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from bq_entity_resolution.config.models.source import JoinConfig
from bq_entity_resolution.sql.utils import validate_identifier

_SQL_INJECTION_PATTERN = re.compile(
    r";\s*|--\s|/\*|\bDROP\b|\bALTER\b|\bCREATE\b|\bTRUNCATE\b|\bGRANT\b|\bREVOKE\b",
    re.IGNORECASE,
)

__all__ = [
    "FeatureDef",
    "FeatureGroupConfig",
    "BlockingKeyDef",
    "CompositeKeyDef",
    "EnrichmentJoinConfig",
    "CompoundDetectionConfig",
    "PlaceholderPatternDef",
    "PlaceholderConfig",
    "FeatureEngineeringConfig",
]


class FeatureDef(BaseModel):
    """A single engineered feature."""

    name: str
    function: str  # registered function name (e.g. 'name_clean', 'soundex')
    input: str | None = None  # single-input functions
    inputs: list[str] | None = None  # multi-input functions
    params: dict[str, Any] = Field(default_factory=dict)
    sql: str | None = None  # raw SQL override (for custom features)
    depends_on: list[str] = Field(default_factory=list)
    join: JoinConfig | None = None

    @field_validator("name")
    @classmethod
    def _validate_name_identifier(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        validate_identifier(v, context="feature name")
        return v

    @field_validator("function")
    @classmethod
    def _non_empty_function(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("sql")
    @classmethod
    def _validate_sql_safe(cls, v: str | None) -> str | None:
        if v is not None and _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "sql expression contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v

    @model_validator(mode="after")
    def _normalize_input(self) -> FeatureDef:
        """Normalize singular 'input' into 'inputs' list."""
        if self.input and not self.inputs:
            object.__setattr__(self, "inputs", [self.input])
        return self

    @model_validator(mode="after")
    def _validate_inputs_identifiers(self) -> FeatureDef:
        """Validate that input column names are safe SQL identifiers."""
        if self.sql:
            return self  # Raw SQL bypasses validation
        for col in self.inputs or []:
            try:
                validate_identifier(col, context="feature input")
            except ValueError as e:
                raise ValueError(str(e)) from e
        return self


class FeatureGroupConfig(BaseModel):
    """A logical group of related features (e.g. name features, address features)."""

    enabled: bool = True
    features: list[FeatureDef] = Field(default_factory=list)


class BlockingKeyDef(BaseModel):
    """A blocking key used for candidate pair generation."""

    name: str
    function: str  # farm_fingerprint, farm_fingerprint_concat, etc.
    inputs: list[str]

    @field_validator("name")
    @classmethod
    def _validate_name_identifier(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        validate_identifier(v, context="blocking key name")
        return v

    @field_validator("function")
    @classmethod
    def _non_empty_function(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("inputs")
    @classmethod
    def _validate_input_identifiers(cls, v: list[str]) -> list[str]:
        for col in v:
            validate_identifier(col, context="blocking key input")
        return v


class CompositeKeyDef(BaseModel):
    """A composite key for exact-match tiers."""

    name: str
    function: str
    inputs: list[str]

    @field_validator("name")
    @classmethod
    def _validate_name_identifier(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        validate_identifier(v, context="composite key name")
        return v

    @field_validator("function")
    @classmethod
    def _non_empty_function(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("inputs")
    @classmethod
    def _validate_input_identifiers(cls, v: list[str]) -> list[str]:
        for col in v:
            validate_identifier(col, context="composite key input")
        return v


class EnrichmentJoinConfig(BaseModel):
    """A lookup table join for enriching entities with external data.

    Used during feature engineering to bring in standardized addresses,
    GPS coordinates, or any reference data from an external BigQuery table.

    The join key is computed from source columns using a registered feature
    function (e.g., farm_fingerprint_concat). The lookup table must have a
    column matching the computed key's output type (typically INT64 for
    FARM_FINGERPRINT-based keys).

    PERF: When source_key_function produces INT64 (e.g., farm_fingerprint),
    the enrichment join runs at INT64 speed — ~3-5x faster than STRING joins.

    Example YAML::

        enrichment_joins:
          - name: "census_geocode"
            table: "${BQ_PROJECT}.census.address_lookup"
            lookup_key: "address_fp"
            source_key_function: "farm_fingerprint_concat"
            source_key_inputs: ["address_line_1", "city", "state"]
            columns: ["matched_address", "latitude", "longitude"]
            column_prefix: "census_"
            match_flag: "has_census_match"
    """

    name: str  # Human-readable name, also used as JOIN alias
    table: str  # Fully-qualified BQ table (e.g., "project.dataset.table")
    lookup_key: str  # Column in lookup table to join on
    source_key_function: str  # Registered feature function name
    source_key_inputs: list[str]  # Source columns passed to the function
    source_key_params: dict[str, Any] = Field(default_factory=dict)
    columns: list[str]  # Columns to pull from the lookup table
    column_prefix: str = ""  # Prefix for pulled columns (avoids collisions)
    match_flag: str = ""  # If set, auto-generates a 0/1 INT64 match flag column
    type: Literal["LEFT", "INNER"] = "LEFT"

    @field_validator("name", "table", "lookup_key")
    @classmethod
    def _non_empty_string(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v


class CompoundDetectionConfig(BaseModel):
    """Compound record detection and handling configuration.

    When enabled, automatically injects compound detection features
    (is_compound_name, compound_pattern) into feature engineering.

    Actions:
        flag:  Add detection columns only (default).
        split: Expand compound rows into individual records.
        both:  Split first, then flag the originals.
    """

    enabled: bool = False
    name_column: str = "first_name"
    last_name_column: str = "last_name"
    action: Literal["flag", "split", "both"] = "flag"
    flag_column: str = "is_compound_name"
    custom_patterns: list[str] = Field(default_factory=list)

    @field_validator("name_column", "last_name_column", "flag_column")
    @classmethod
    def _validate_column_identifiers(cls, v: str) -> str:
        validate_identifier(v, context="compound detection column")
        return v


class PlaceholderPatternDef(BaseModel):
    """A custom placeholder pattern for sentinel value detection.

    Defines exact-match values and/or a regex pattern that should be
    treated as placeholder (non-informative) data. Values are compared
    in UPPER case.
    """

    name: str
    values: list[str] = Field(default_factory=list)
    regex: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        validate_identifier(v, context="placeholder pattern name")
        return v


class PlaceholderConfig(BaseModel):
    """Placeholder/sentinel value detection and nullification.

    When enabled, automatically injects feature functions that detect
    and optionally nullify common placeholder values (e.g., phone
    "9999999999", email "noemail@email.com", name "UNKNOWN") to
    prevent cartesian explosions in blocking.

    ``auto_nullify_blocking_inputs`` wraps blocking key input columns
    with nullification functions so placeholder values hash to NULL
    and are excluded from candidate pair generation via existing
    IS NOT NULL conditions in blocking SQL.
    """

    enabled: bool = False
    auto_nullify_blocking_inputs: bool = True
    detect_phone: bool = True
    detect_email: bool = True
    detect_name: bool = True
    detect_address: bool = True
    detect_ssn: bool = True
    custom_patterns: dict[str, PlaceholderPatternDef] = Field(default_factory=dict)


class FeatureEngineeringConfig(BaseModel):
    """All feature engineering configuration."""

    name_features: FeatureGroupConfig = Field(default_factory=FeatureGroupConfig)
    address_features: FeatureGroupConfig = Field(default_factory=FeatureGroupConfig)
    contact_features: FeatureGroupConfig = Field(default_factory=FeatureGroupConfig)
    extra_groups: dict[str, FeatureGroupConfig] = Field(default_factory=dict)
    blocking_keys: list[BlockingKeyDef] = Field(default_factory=list)
    composite_keys: list[CompositeKeyDef] = Field(default_factory=list)
    custom_features: list[FeatureDef] = Field(default_factory=list)
    enrichment_joins: list[EnrichmentJoinConfig] = Field(default_factory=list)
    compound_detection: CompoundDetectionConfig = Field(
        default_factory=CompoundDetectionConfig
    )
    placeholder: PlaceholderConfig = Field(default_factory=PlaceholderConfig)
    entity_type_column: str = ""  # Feature column for entity type gating

    @field_validator("entity_type_column")
    @classmethod
    def _validate_entity_type_column(cls, v: str) -> str:
        if v:
            validate_identifier(v, context="entity_type_column")
        return v

    def all_groups(self) -> list[FeatureGroupConfig]:
        """Return all feature groups (built-in + extra) for iteration."""
        groups = [self.name_features, self.address_features, self.contact_features]
        groups.extend(self.extra_groups.values())
        return groups

    def all_feature_names(self) -> set[str]:
        """Return all feature names across all groups + custom features.

        Includes auto-injected compound detection columns and enrichment
        join output columns so validators can resolve them.
        """
        names: set[str] = set()
        for group in self.all_groups():
            for feat in group.features:
                names.add(feat.name)
        for feat in self.custom_features:
            names.add(feat.name)
        for bk in self.blocking_keys:
            names.add(bk.name)
        for ck in self.composite_keys:
            names.add(ck.name)
        # Auto-injected compound detection columns
        if self.compound_detection.enabled:
            names.add(self.compound_detection.flag_column)
            names.add("compound_pattern")
        # Enrichment join output columns (with prefix applied)
        for ej in self.enrichment_joins:
            for col in ej.columns:
                names.add(f"{ej.column_prefix}{col}")
            if ej.match_flag:
                names.add(ej.match_flag)
        return names

"""quick_config() — Level 1 progressive disclosure entry point.

Generate a complete PipelineConfig from minimal inputs (project, table,
columns). Auto-detects roles from column names.
"""

from __future__ import annotations

from bq_entity_resolution.config.presets.helpers import _build_config
from bq_entity_resolution.config.roles import detect_role
from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.exceptions import ConfigurationError


def quick_config(
    bq_project: str,
    source_table: str,
    unique_key: str = "id",
    updated_at: str = "updated_at",
    columns: list[str] | None = None,
    column_roles: dict[str, str] | None = None,
    project_name: str | None = None,
    entity_type: str | None = None,
) -> PipelineConfig:
    """Generate a complete PipelineConfig from minimal inputs.

    This is Level 1 progressive disclosure: provide a source table
    and column list, and the system auto-detects roles and generates
    all features, blocking keys, comparisons, and tiers.

    Args:
        bq_project: GCP project ID.
        source_table: Fully-qualified BigQuery source table.
        unique_key: Primary key column name.
        updated_at: Timestamp column for incremental processing.
        columns: Column names to include. If None, must provide
            column_roles.
        column_roles: Explicit role assignments {column_name: role}.
            Overrides auto-detection.
        project_name: Optional project name (derived from table if not set).
        entity_type: Optional entity type (e.g. "Person", "Organization").
            When set, enables schema.org alias detection, type-driven
            defaults, and role validation.
    """
    # Resolve column roles
    role_map = _resolve_roles(columns, column_roles)
    if not role_map:
        raise ConfigurationError(
            "No columns with recognized roles. Provide column_roles "
            "explicitly or use column names that match common patterns "
            "(first_name, last_name, email, etc.)."
        )

    # Derive project name
    if not project_name:
        parts = source_table.split(".")
        project_name = parts[-1] if parts else "er_pipeline"

    return _build_config(
        bq_project=bq_project,
        project_name=project_name,
        source_table=source_table,
        unique_key=unique_key,
        updated_at=updated_at,
        role_map=role_map,
        entity_type=entity_type,
    )


def _resolve_roles(
    columns: list[str] | None,
    column_roles: dict[str, str] | None,
) -> dict[str, str]:
    """Resolve column-to-role mapping.

    Explicit roles take priority. Auto-detection fills in the rest.
    """
    result: dict[str, str] = {}

    if column_roles:
        result.update(column_roles)

    if columns:
        for col in columns:
            if col not in result:
                role = detect_role(col)
                if role:
                    result[col] = role

    return result

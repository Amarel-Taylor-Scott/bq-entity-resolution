"""Internal helpers for building PipelineConfig from roles and templates.

These functions are shared by quick_config() and the domain presets.
They are not part of the public API.
"""

from __future__ import annotations

from typing import Literal, cast

from bq_entity_resolution.config.roles import (
    blocking_keys_for_role,
    comparisons_for_role,
    features_for_role,
)
from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.exceptions import ConfigurationError


def _build_config(
    bq_project: str,
    project_name: str,
    source_table: str,
    unique_key: str,
    updated_at: str,
    role_map: dict[str, str],
    link_type: str = "link_and_dedupe",
    entity_type: str | None = None,
) -> PipelineConfig:
    """Build a full PipelineConfig from a role map."""
    # Column mappings
    col_mappings = [
        ColumnMapping(name=col, role=role)
        for col, role in role_map.items()
    ]

    # Source
    source = SourceConfig(
        name=source_table.rsplit(".", 1)[-1],
        table=source_table,
        unique_key=unique_key,
        updated_at=updated_at,
        entity_type=entity_type,
        columns=col_mappings,
    )

    # Generate features, blocking keys, comparison pool
    features, blocking_keys, comparison_pool = _generate_from_roles(role_map)

    # Build tiers (using pool references)
    blocking_key_names = [bk.name for bk in blocking_keys]
    tiers = _build_default_tiers(blocking_key_names, comparison_pool)

    return PipelineConfig(
        project=ProjectConfig(name=project_name, bq_project=bq_project),
        sources=[source],
        feature_engineering=FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(features=features),
            blocking_keys=blocking_keys,
        ),
        comparison_pool=comparison_pool,
        matching_tiers=tiers,
        link_type=cast(Literal["link_and_dedupe", "dedupe_only", "link_only"], link_type),
    )


def _preset_from_entity_type(
    entity_type: str,
    bq_project: str,
    source_table: str,
    unique_key: str,
    updated_at: str,
    columns: dict[str, str],
    project_name: str,
    link_type: str | None = None,
) -> PipelineConfig:
    """Build a PipelineConfig from an entity type template and column roles.

    Looks up the template for role validation warnings and default link_type.
    """
    import warnings

    from bq_entity_resolution.config.entity_types import resolve_hierarchy

    try:
        template = resolve_hierarchy(entity_type)
        resolved_link_type = link_type or template.default_link_type
        # Warn about roles not in the template's valid set
        for col, role in columns.items():
            if role not in template.valid_roles:
                warnings.warn(
                    f"Role '{role}' for column '{col}' is not in the "
                    f"'{entity_type}' entity type's valid roles.",
                    stacklevel=3,
                )
    except KeyError:
        resolved_link_type = link_type or "dedupe_only"

    return _build_config(
        bq_project=bq_project,
        project_name=project_name,
        source_table=source_table,
        unique_key=unique_key,
        updated_at=updated_at,
        role_map=columns,
        link_type=resolved_link_type,
        entity_type=entity_type,
    )


def _generate_from_roles(
    role_map: dict[str, str],
) -> tuple[list[FeatureDef], list[BlockingKeyDef], dict[str, ComparisonDef]]:
    """Generate features, blocking keys, and comparison pool from roles.

    Returns comparison pool as a dict keyed by name (e.g. "email_exact")
    instead of a flat list.  Tiers reference these by name via ``ref``.
    """
    all_features: list[FeatureDef] = []
    all_blocking_keys: list[BlockingKeyDef] = []
    comparison_pool: dict[str, ComparisonDef] = {}
    seen_bk_names: set[str] = set()

    for col, role in role_map.items():
        # Features
        for feat_dict in features_for_role(col, role):
            all_features.append(FeatureDef(
                name=feat_dict["name"],
                function=feat_dict["function"],
                inputs=feat_dict["inputs"],
            ))

        # Blocking keys (deduplicate by name)
        for bk_dict in blocking_keys_for_role(col, role):
            if bk_dict["name"] not in seen_bk_names:
                all_blocking_keys.append(BlockingKeyDef(
                    name=bk_dict["name"],
                    function=bk_dict["function"],
                    inputs=bk_dict["inputs"],
                ))
                seen_bk_names.add(bk_dict["name"])

        # Comparisons → pool entries keyed by name
        for comp_dict in comparisons_for_role(col, role):
            pool_name = comp_dict["name"]
            comparison_pool[pool_name] = ComparisonDef(
                left=comp_dict["left"],
                right=comp_dict["right"],
                method=comp_dict["method"],
                weight=comp_dict["weight"],
            )

    return all_features, all_blocking_keys, comparison_pool


def _build_default_tiers(
    blocking_key_names: list[str],
    comparison_pool: dict[str, ComparisonDef],
) -> list[MatchingTierConfig]:
    """Build default matching tiers using comparison pool references.

    Creates two tiers:
    1. "exact" — high-confidence exact matches using all blocking keys
    2. "fuzzy" — lower-threshold fuzzy matches

    Tiers reference the comparison pool by name.  The PipelineConfig
    ``_resolve_comparison_refs`` validator hydrates them at load time.

    If only one blocking key exists, both tiers use the same key.
    """
    if not blocking_key_names:
        raise ConfigurationError("No blocking keys generated from roles")
    if not comparison_pool:
        raise ConfigurationError("No comparisons generated from roles")

    # Build pool ref comparisons (tier references the pool by name)
    pool_refs = [ComparisonDef(ref=name) for name in comparison_pool]

    # Compute total weight from pool entries for threshold calculation
    total_weight = sum(c.weight for c in comparison_pool.values())

    # Split blocking keys across tiers if we have enough
    if len(blocking_key_names) >= 2:
        exact_keys = blocking_key_names[:len(blocking_key_names) // 2]
        fuzzy_keys = blocking_key_names[len(blocking_key_names) // 2:]
    else:
        exact_keys = blocking_key_names
        fuzzy_keys = blocking_key_names

    # Exact tier: higher threshold
    exact_tier = MatchingTierConfig(
        name="exact",
        description="High-confidence exact matches",
        blocking=TierBlockingConfig(
            paths=[BlockingPathDef(keys=exact_keys)],
        ),
        comparisons=pool_refs,
        threshold=ThresholdConfig(
            method="sum",
            min_score=total_weight * 0.7,
        ),
    )

    # Fuzzy tier: lower threshold, different blocking path
    fuzzy_tier = MatchingTierConfig(
        name="fuzzy",
        description="Fuzzy probabilistic matches",
        blocking=TierBlockingConfig(
            paths=[BlockingPathDef(keys=fuzzy_keys)],
        ),
        comparisons=list(pool_refs),  # fresh copy
        threshold=ThresholdConfig(
            method="sum",
            min_score=total_weight * 0.4,
        ),
    )

    return [exact_tier, fuzzy_tier]

"""
Root pipeline configuration model.

Defines PipelineConfig, the top-level Pydantic model that composes
all domain-specific configuration models into a single validated schema.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from bq_entity_resolution.config.models.features import FeatureEngineeringConfig
from bq_entity_resolution.config.models.infrastructure import (
    DeploymentConfig,
    EmbeddingConfig,
    ExecutionConfig,
    IncrementalConfig,
    MonitoringConfig,
    ProjectConfig,
    ScaleConfig,
)
from bq_entity_resolution.config.models.matching import (
    ComparisonDef,
    HardNegativeDef,
    HardPositiveDef,
    MatchingTierConfig,
    SoftSignalDef,
    TrainingConfig,
)
from bq_entity_resolution.config.models.reconciliation import ReconciliationConfig
from bq_entity_resolution.config.models.source import SourceConfig

__all__ = [
    "PipelineConfig",
]


class PipelineConfig(BaseModel):
    """Root configuration for the entire entity resolution pipeline."""

    version: str = "1.0"

    @field_validator("version")
    @classmethod
    def _validate_version_format(cls, v: str) -> str:
        import re
        if not re.fullmatch(r'\d{1,2}\.\d{1,2}', v):
            raise ValueError(
                f"version must match pattern 'X.Y' where X and Y are 1-2 digits, got '{v}'"
            )
        return v

    project: ProjectConfig
    sources: list[SourceConfig]
    feature_engineering: FeatureEngineeringConfig = Field(
        default_factory=FeatureEngineeringConfig
    )
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    comparison_pool: dict[str, ComparisonDef] = Field(default_factory=dict)
    matching_tiers: list[MatchingTierConfig]
    global_hard_negatives: list[HardNegativeDef] = Field(default_factory=list)
    global_hard_positives: list[HardPositiveDef] = Field(default_factory=list)
    global_soft_signals: list[SoftSignalDef] = Field(default_factory=list)
    reconciliation: ReconciliationConfig = Field(default_factory=ReconciliationConfig)
    incremental: IncrementalConfig = Field(default_factory=IncrementalConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)  # global default
    scale: ScaleConfig = Field(default_factory=lambda: ScaleConfig())
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    link_type: Literal["link_and_dedupe", "dedupe_only", "link_only"] = "link_and_dedupe"
    custom_entity_types: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _register_custom_entity_types(self) -> PipelineConfig:
        """Register custom entity types from YAML before other validators.

        Allows users to define new entity types (e.g. Vehicle, RealEstate)
        without editing Python source code.
        """
        if not self.custom_entity_types:
            return self

        from bq_entity_resolution.config.entity_types import (
            DefaultSignal,
            EntityTypeTemplate,
            register_entity_type,
        )

        for name, spec in self.custom_entity_types.items():
            template = EntityTypeTemplate(
                name=name,
                valid_roles=frozenset(spec.get("valid_roles", [])),
                required_roles=frozenset(spec.get("required_roles", [])),
                parent=spec.get("parent"),
                schema_org_type=spec.get("schema_org_type", ""),
                schema_org_aliases=spec.get("schema_org_aliases", {}),
                default_signals=tuple(
                    DefaultSignal(**s) for s in spec.get("default_signals", [])
                ),
                default_link_type=spec.get("default_link_type", "dedupe_only"),
                description=spec.get("description", ""),
            )
            register_entity_type(template)
        return self

    @model_validator(mode="after")
    def _inject_entity_type_signals(self) -> PipelineConfig:
        """Auto-inject default signals from entity type templates.

        When a source declares ``entity_type``, the corresponding template's
        ``default_signals`` are injected into global hard negatives or soft
        signals. Signals are only injected if:

        1. The signal's referenced feature column exists in
           ``feature_engineering.all_feature_names()``.
        2. No signal with the same (category, left) already exists
           (user-defined signals take precedence).
        """
        from bq_entity_resolution.config.entity_types import get_entity_type

        known_features = self.feature_engineering.all_feature_names()

        for source in self.sources:
            if not source.entity_type:
                continue
            try:
                template = get_entity_type(source.entity_type)
            except KeyError:
                continue

            existing_hn = {
                (hn.category, hn.left) for hn in self.global_hard_negatives
            }
            existing_ss = {
                (ss.category, ss.left) for ss in self.global_soft_signals
            }

            for signal in template.default_signals:
                if signal.left not in known_features:
                    continue

                if signal.kind == "hard_negative":
                    if (signal.category, signal.left) in existing_hn:
                        continue
                    self.global_hard_negatives.append(HardNegativeDef(
                        left=signal.left,
                        method=signal.method,
                        action=signal.action,  # type: ignore[arg-type]
                        severity=signal.severity,  # type: ignore[arg-type]
                        penalty=signal.value,
                        entity_type_condition=source.entity_type.lower(),
                        category=signal.category,
                    ))
                    existing_hn.add((signal.category, signal.left))
                elif signal.kind == "soft_signal":
                    if (signal.category, signal.left) in existing_ss:
                        continue
                    self.global_soft_signals.append(SoftSignalDef(
                        left=signal.left,
                        method=signal.method,
                        bonus=signal.value,
                        entity_type_condition=source.entity_type.lower(),
                        category=signal.category,
                    ))
                    existing_ss.add((signal.category, signal.left))
        return self

    @model_validator(mode="after")
    def _resolve_comparison_refs(self) -> PipelineConfig:
        """Resolve comparison pool references in tier comparisons.

        When a ComparisonDef has ``ref`` set, it is resolved against
        the ``comparison_pool`` dict.  Any fields set alongside ``ref``
        act as tier-level overrides (e.g. weight).
        """
        for tier in self.matching_tiers:
            resolved: list[ComparisonDef] = []
            for comp in tier.comparisons:
                if comp.ref:
                    pool_entry = self.comparison_pool.get(comp.ref)
                    if not pool_entry:
                        raise ValueError(
                            f"Tier '{tier.name}' references unknown "
                            f"comparison_pool ref '{comp.ref}'. "
                            f"Available: {sorted(self.comparison_pool.keys())}"
                        )
                    # Merge: pool base + any tier-level overrides
                    overrides = comp.model_dump(
                        exclude_unset=True, exclude={"ref"}
                    )
                    merged_data = pool_entry.model_dump()
                    merged_data.update(overrides)
                    merged_data.pop("ref", None)  # resolved refs don't carry ref
                    resolved.append(ComparisonDef(**merged_data))
                else:
                    resolved.append(comp)
            tier.comparisons = resolved
        return self

    @model_validator(mode="after")
    def unique_tier_names(self) -> PipelineConfig:
        names = [t.name for t in self.matching_tiers]
        dupes = [n for n in names if names.count(n) > 1]
        if dupes:
            raise ValueError(f"Duplicate tier names: {set(dupes)}")
        return self

    @model_validator(mode="after")
    def blocking_keys_exist(self) -> PipelineConfig:
        """Verify all blocking keys referenced in tiers are defined."""
        defined = {bk.name for bk in self.feature_engineering.blocking_keys}
        defined |= {ck.name for ck in self.feature_engineering.composite_keys}
        if self.embeddings.enabled:
            for i in range(self.embeddings.lsh.num_hash_tables):
                defined.add(f"{self.embeddings.lsh.bucket_column_prefix}_{i}")
        for tier in self.matching_tiers:
            if not tier.enabled:
                continue
            for path in tier.blocking.paths:
                for key in path.keys:
                    if key not in defined:
                        raise ValueError(
                            f"Tier '{tier.name}' references undefined "
                            f"blocking key '{key}'. Defined keys: {sorted(defined)}"
                        )
        return self

    @model_validator(mode="after")
    def at_least_one_source(self) -> PipelineConfig:
        if not self.sources:
            raise ValueError("At least one source must be defined")
        return self

    def enabled_tiers(self) -> list[MatchingTierConfig]:
        """Return only enabled matching tiers in order."""
        return [t for t in self.matching_tiers if t.enabled]

    def effective_hard_negatives(self, tier: MatchingTierConfig) -> list[HardNegativeDef]:
        """Return combined global + tier-level hard negatives for a tier.

        Global hard negatives are applied first, then tier-specific ones.
        This enables defining disqualification rules once and reusing
        across all tiers.
        """
        return list(self.global_hard_negatives) + list(tier.hard_negatives)

    def effective_hard_positives(self, tier: MatchingTierConfig) -> list[HardPositiveDef]:
        """Return combined global + tier-level hard positives for a tier."""
        return list(self.global_hard_positives) + list(tier.hard_positives)

    def effective_soft_signals(self, tier: MatchingTierConfig) -> list[SoftSignalDef]:
        """Return combined global + tier-level soft signals for a tier.

        Global soft signals are applied first, then tier-specific ones.
        """
        return list(self.global_soft_signals) + list(tier.soft_signals)

    def effective_training_config(self, tier: MatchingTierConfig) -> TrainingConfig:
        """Return the effective training config for a tier.

        Resolution order:
        1. Tier-level training config (if method != "none")
        2. Auto-retrain from label feedback (if enabled + auto_retrain)
        3. Global training config
        """
        # Tier-level explicit training takes priority
        if tier.training.method != "none":
            return tier.training

        # Auto-retrain: when label feedback is enabled and auto_retrain=True,
        # wire the labels table as the training source for the next run
        feedback = tier.active_learning.label_feedback
        if feedback.enabled and feedback.auto_retrain:
            from bq_entity_resolution.naming import labels_table
            return TrainingConfig(
                method="labeled",
                labeled_pairs_table=labels_table(self),
            )

        # Fall back to global training config
        return self.training

    def fq_table(self, dataset_attr: str, suffix: str) -> str:
        """Build a fully-qualified BigQuery table name."""
        dataset = getattr(self.project, dataset_attr)
        return f"{self.project.bq_project}.{dataset}.{suffix}"

    def to_yaml(self) -> str:
        """Serialize the full config to YAML for inspection and editing.

        Enables the workflow: quick_config() -> inspect -> tweak -> reload.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for to_yaml(). Install with: pip install pyyaml"
            )

        data = self.model_dump(exclude_defaults=True, exclude_none=True)
        return yaml.dump(data, default_flow_style=False, sort_keys=False, width=100)

"""Matching stage: scores candidate pairs and filters by threshold.

Extracted from PipelineOrchestrator._execute_tiers() matching portion.
Supports both sum-based and Fellegi-Sunter scoring strategies.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
)
from bq_entity_resolution.matching.comparisons import (
    COMPARISON_FUNCTIONS,
    _validated_call,
)
from bq_entity_resolution.naming import (
    candidates_table,
    featured_table,
    matches_table,
)
from bq_entity_resolution.sql.builders.comparison import (
    ComparisonDef,
    ComparisonLevel,
    FellegiSunterParams,
    HardNegative,
    HardPositive,
    ScoreBand,
    SoftSignal,
    SumScoringParams,
    Threshold,
    build_fellegi_sunter_sql,
    build_sum_scoring_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)

# Legacy alias kept for backward-compatible test imports.
_ENTITY_TYPE_MAP: dict[str, str] = {
    "personal": "PERSON",
    "person": "PERSON",
    "business": "BUSINESS",
    "organization": "ORGANIZATION",
    "org": "ORGANIZATION",
}


def _resolve_entity_type_sql_value(condition: str) -> str:
    """Resolve a friendly entity type condition to SQL value.

    Checks legacy aliases first, then registered entity type templates,
    falling back to uppercasing the condition string.
    """
    lower = condition.lower()
    # Legacy aliases for backward compat
    if lower in _ENTITY_TYPE_MAP:
        return _ENTITY_TYPE_MAP[lower]
    # Check registered entity type templates
    from bq_entity_resolution.config.entity_types import ENTITY_TYPE_TEMPLATES
    for name in ENTITY_TYPE_TEMPLATES:
        if name.lower() == lower:
            return name.upper()
    return condition.upper()


class MatchingStage(Stage):
    """Score candidate pairs for a single matching tier.

    Generates comparison SQL, applies hard negatives and soft signals,
    computes aggregate score, and filters by threshold.
    """

    def __init__(
        self,
        tier: MatchingTierConfig,
        tier_index: int,
        config: PipelineConfig,
    ):
        self._tier = tier
        self._tier_index = tier_index
        self._config = config
        self._estimated_params: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return f"matching_{self._tier.name}"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "candidates": TableRef(
                name=f"candidates_{self._tier.name}",
                fq_name=candidates_table(self._config, self._tier.name),
            ),
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = matches_table(self._config, self._tier.name)
        return {
            "matches": TableRef(
                name=f"matches_{self._tier.name}",
                fq_name=target,
                description=f"Scored matches for tier {self._tier.name}",
            ),
        }

    def set_estimated_params(self, params: dict[str, Any]) -> None:
        """Inject estimated m/u parameters from EM or labeled data."""
        self._estimated_params = params

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate matching/scoring SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        tier = self._tier
        is_fs = tier.threshold.method == "fellegi_sunter"

        if is_fs:
            return self._plan_fellegi_sunter()
        else:
            return self._plan_sum_scoring()

    def _plan_sum_scoring(self) -> list[SQLExpression]:
        """Generate sum-based scoring SQL."""
        tier = self._tier
        udf_dataset = self._config.project.udf_dataset

        comparisons: list[ComparisonDef] = []
        for comp in tier.comparisons:
            func = COMPARISON_FUNCTIONS.get(comp.method)
            if func is None:
                logger.warning(
                    "Unknown comparison method '%s' for column '%s' — skipping. "
                    "Available: %s",
                    comp.method, comp.left,
                    sorted(COMPARISON_FUNCTIONS.keys())[:10],
                )
                continue
            params = dict(comp.params) if comp.params else {}
            if udf_dataset:
                params["udf_dataset"] = udf_dataset
            try:
                sql_expr = _validated_call(func, comp.left, comp.right, **params)
            except Exception as exc:
                logger.warning(
                    "Skipping comparison '%s' (method=%s): %s",
                    comp.left, comp.method, exc,
                )
                continue
            comparisons.append(
                ComparisonDef(
                    name=f"{comp.left}_{comp.method}",
                    sql_expr=sql_expr,
                    weight=comp.weight,
                    **self._tf_fields(comp),
                )
            )

        signals = self._build_all_signals(tier)

        max_score = sum(c.weight for c in comparisons)
        tf_table = self._resolve_tf_table(comparisons)

        scoring_params = SumScoringParams(
            tier_name=tier.name,
            tier_index=self._tier_index,
            matches_table=self.outputs["matches"].fq_name,
            candidates_table=self.inputs["candidates"].fq_name,
            source_table=self.inputs["featured"].fq_name,
            comparisons=comparisons,
            hard_negatives=signals["hard_negatives"],
            hard_positives=signals["hard_positives"],
            soft_signals=signals["soft_signals"],
            threshold=Threshold(
                method=tier.threshold.method,
                min_score=tier.threshold.min_score,
                min_matching_comparisons=tier.threshold.min_matching_comparisons,
            ),
            confidence=tier.confidence,
            max_possible_score=max_score,
            tf_table=tf_table,
            audit_trail_enabled=self._audit_trail_enabled(),
            score_bands=signals["score_bands"],
        )

        return [build_sum_scoring_sql(scoring_params)]

    def _plan_fellegi_sunter(self) -> list[SQLExpression]:
        """Generate Fellegi-Sunter scoring SQL."""
        tier = self._tier

        comparisons: list[ComparisonDef] = []
        for comp in tier.comparisons:
            levels: list[ComparisonLevel] = []
            for level in (comp.levels or []):
                m_val = level.m if level.m is not None else 0.9
                u_val = level.u if level.u is not None else 0.1
                # Compute log_weight from m/u if not explicitly set
                if level.log_weight is not None and level.log_weight != 0.0:
                    log_weight = level.log_weight
                elif u_val > 0 and m_val > 0:
                    log_weight = math.log2(m_val / u_val)
                else:
                    log_weight = 0.0
                levels.append(
                    ComparisonLevel(
                        label=level.label,
                        sql_expr=level.sql_expr,
                        log_weight=log_weight,
                        m=m_val,
                        u=u_val,
                        tf_adjusted=level.tf_adjusted,
                    )
                )
            comparisons.append(
                ComparisonDef(
                    name=f"{comp.left}_{comp.method}",
                    levels=levels,
                    **self._tf_fields(comp),
                )
            )

        signals = self._build_all_signals(tier)
        tf_table = self._resolve_tf_table(comparisons)

        scoring_params = FellegiSunterParams(
            tier_name=tier.name,
            tier_index=self._tier_index,
            matches_table=self.outputs["matches"].fq_name,
            candidates_table=self.inputs["candidates"].fq_name,
            source_table=self.inputs["featured"].fq_name,
            comparisons=comparisons,
            log_prior_odds=tier.threshold.log_prior_odds,
            hard_negatives=signals["hard_negatives"],
            hard_positives=signals["hard_positives"],
            soft_signals=signals["soft_signals"],
            threshold=Threshold(
                method=tier.threshold.method,
                min_score=tier.threshold.min_score,
                match_threshold=tier.threshold.match_threshold,
                min_matching_comparisons=tier.threshold.min_matching_comparisons,
            ),
            tf_table=tf_table,
            audit_trail_enabled=self._audit_trail_enabled(),
            score_bands=signals["score_bands"],
        )

        return [build_fellegi_sunter_sql(scoring_params)]

    # -- Shared helpers for both scoring strategies --------------------------

    @staticmethod
    def _tf_fields(comp: Any) -> dict[str, Any]:
        """Extract term-frequency fields from a config ComparisonDef."""
        tf_adj = getattr(comp, "tf_adjustment", None)
        return {
            "tf_enabled": (
                getattr(comp, "tf_enabled", False)
                or (tf_adj is not None and getattr(tf_adj, "enabled", False))
            ),
            "tf_column": (
                getattr(comp, "tf_column", "")
                or (getattr(tf_adj, "tf_adjustment_column", "") if tf_adj else "")
                or comp.left
            ),
            "tf_minimum_u": (
                getattr(comp, "tf_minimum_u", 0.01)
                if getattr(comp, "tf_enabled", False)
                else (getattr(tf_adj, "tf_minimum_u_value", 0.01) if tf_adj else 0.01)
            ),
        }

    def _audit_trail_enabled(self) -> bool:
        """Check if audit trail is enabled via reconciliation output config."""
        output = self._config.reconciliation.output
        return output.audit_trail.enabled

    def _build_all_signals(self, tier: MatchingTierConfig) -> dict[str, Any]:
        """Build all signal types for a tier (shared by sum and F-S)."""
        return {
            "hard_negatives": self._build_hard_negatives(tier),
            "hard_positives": self._build_hard_positives(tier),
            "soft_signals": self._build_soft_signals(tier),
            "score_bands": self._build_score_bands(tier),
        }

    def _resolve_tf_table(self, comparisons: list[ComparisonDef]) -> str | None:
        """Resolve the TF stats table if any comparison uses TF adjustment."""
        if any(c.tf_enabled for c in comparisons):
            from bq_entity_resolution.naming import term_frequency_table
            return term_frequency_table(self._config)
        return None

    def _build_hard_negatives(self, tier: MatchingTierConfig) -> list[HardNegative]:
        """Convert combined global + tier hard negatives to builder format.

        Severity-aware behavior:
          - hn1_critical / hn2_structural: Apply as configured.
          - hn3_identity: Apply entity_type_condition guard (if configured).
          - hn4_contextual: Force to 'penalize' (never disqualify).
        """
        result: list[HardNegative] = []
        all_hns = self._config.effective_hard_negatives(tier)
        for hn in all_hns:
            sql_cond = self._hard_negative_sql(hn)
            if not sql_cond:
                continue

            sql_cond = self._apply_entity_type_guard(sql_cond, hn)

            # Severity-aware action: hn4_contextual never disqualifies
            action = hn.action
            if hn.severity == "hn4_contextual" and action == "disqualify":
                action = "penalize"

            result.append(
                HardNegative(
                    sql_condition=sql_cond,
                    action=action,
                    penalty=hn.penalty,
                )
            )
        return result

    def _build_hard_positives(self, tier: MatchingTierConfig) -> list[HardPositive]:
        """Convert combined global + tier hard positives to builder format."""
        result: list[HardPositive] = []
        all_hps = self._config.effective_hard_positives(tier)
        for hp in all_hps:
            sql_cond = self._signal_sql(hp)
            if not sql_cond:
                continue
            sql_cond = self._apply_entity_type_guard(sql_cond, hp)
            result.append(
                HardPositive(
                    sql_condition=sql_cond,
                    action=hp.action,
                    boost=hp.boost,
                    target_band=hp.target_band,
                )
            )
        return result

    def _build_soft_signals(self, tier: MatchingTierConfig) -> list[SoftSignal]:
        """Convert combined global + tier soft signals to builder format."""
        result: list[SoftSignal] = []
        all_sigs = self._config.effective_soft_signals(tier)
        for ss in all_sigs:
            sql_cond = self._signal_sql(ss)
            if not sql_cond:
                continue
            sql_cond = self._apply_entity_type_guard(sql_cond, ss)
            result.append(
                SoftSignal(
                    sql_condition=sql_cond,
                    bonus=ss.bonus,
                )
            )
        return result

    def _build_score_bands(self, tier: MatchingTierConfig) -> list[ScoreBand]:
        """Convert tier score banding config to builder format."""
        banding = tier.score_banding
        if not banding.enabled:
            return []
        return [
            ScoreBand(
                name=b.name,
                min_score=b.min_score,
                max_score=b.max_score,
                action=b.action,
            )
            for b in banding.bands
        ]

    def _apply_entity_type_guard(self, sql_cond: str, signal: Any) -> str:
        """Wrap SQL condition with entity type guard if configured.

        Only applies when both:
          1. The signal has a non-empty entity_type_condition
          2. The pipeline has feature_engineering.entity_type_column set

        The guard ensures both sides of the pair match the specified type:
          (l.<col> = 'PERSON' AND r.<col> = 'PERSON' AND <original_condition>)
        """
        from bq_entity_resolution.sql.utils import sql_escape

        condition = getattr(signal, "entity_type_condition", None)
        if not condition:
            return sql_cond
        et_col = getattr(
            self._config.feature_engineering, "entity_type_column", ""
        )
        if not et_col:
            return sql_cond
        # Map friendly name to SQL value (e.g. "personal" -> "PERSON")
        sql_value = sql_escape(_resolve_entity_type_sql_value(condition))
        return (
            f"(l.{et_col} = '{sql_value}' AND r.{et_col} = '{sql_value}' "
            f"AND ({sql_cond}))"
        )

    @staticmethod
    def _hard_negative_sql(hn: Any) -> str:
        """Generate SQL condition for a hard negative rule."""
        from bq_entity_resolution.sql.utils import validate_identifier

        if getattr(hn, "sql", None):
            return str(hn.sql)
        left = hn.left
        right = getattr(hn, "right", None) or left
        method = hn.method
        params = getattr(hn, "params", {}) or {}
        validate_identifier(left, "hard negative left column")
        validate_identifier(right, "hard negative right column")
        if method == "different":
            return f"l.{left} IS DISTINCT FROM r.{right}"
        elif method == "null_either":
            return f"(l.{left} IS NULL OR r.{right} IS NULL)"
        # Fall back to comparison function registry
        func = COMPARISON_FUNCTIONS.get(method)
        if func:
            try:
                return _validated_call(func, left, right, **params)
            except Exception as exc:
                logger.warning(
                    "Hard negative SQL failed (left=%s, method=%s): %s",
                    left, method, exc,
                )
        return ""

    @staticmethod
    def _signal_sql(signal: Any) -> str:
        """Generate SQL condition for any signal (hard positive, soft signal, etc.)."""
        from bq_entity_resolution.sql.utils import validate_identifier

        if getattr(signal, "sql", None):
            return str(signal.sql)
        left = signal.left
        right = getattr(signal, "right", None) or left
        method = signal.method
        params = getattr(signal, "params", {}) or {}
        validate_identifier(left, "signal left column")
        validate_identifier(right, "signal right column")
        if method == "exact":
            return f"l.{left} = r.{right}"
        elif method == "exact_case_insensitive":
            return f"LOWER(l.{left}) = LOWER(r.{right})"
        elif method == "both_null":
            return f"(l.{left} IS NULL AND r.{right} IS NULL)"
        elif method == "different":
            return f"l.{left} IS DISTINCT FROM r.{right}"
        elif method == "null_either":
            return f"(l.{left} IS NULL OR r.{right} IS NULL)"
        # Fall back to comparison function registry
        func = COMPARISON_FUNCTIONS.get(method)
        if func:
            try:
                return _validated_call(func, left, right, **params)
            except Exception as exc:
                logger.warning(
                    "Signal SQL failed (left=%s, method=%s): %s",
                    left, method, exc,
                )
        return ""

    def validate(self) -> list[str]:
        errors = []
        if not self._tier.comparisons:
            errors.append(
                f"Tier '{self._tier.name}' has no comparisons defined"
            )
        for comp in self._tier.comparisons:
            if comp.method not in COMPARISON_FUNCTIONS:
                errors.append(
                    f"Unknown comparison method: '{comp.method}' "
                    f"in tier '{self._tier.name}'"
                )
        return errors

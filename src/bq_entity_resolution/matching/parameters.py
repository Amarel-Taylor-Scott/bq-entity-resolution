"""
Parameter estimation for Fellegi-Sunter probabilistic matching.

Computes m (match) and u (non-match) probabilities for each comparison
level, either from labeled training data or via Expectation-Maximization.
All estimation runs in BigQuery — no data leaves the warehouse.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
    TrainingConfig,
)
from bq_entity_resolution.exceptions import ParameterEstimationError
from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS, _validated_call
from bq_entity_resolution.naming import (
    candidates_table,
    featured_table,
    labels_table,
    udf_dataset,
)
from bq_entity_resolution.sql.builders.em import (
    EMComparison,
    EMLevel,
    EMParams,
    LabelEstimationParams,
    build_em_estimation_sql,
    build_estimate_from_labels_sql,
)

logger = logging.getLogger(__name__)


@dataclass
class LevelParameters:
    """Estimated m/u for one level of a comparison."""

    label: str
    m: float
    u: float

    @property
    def log_weight(self) -> float:
        m = max(0.001, min(0.999, self.m))
        u = max(0.001, min(0.999, self.u))
        return math.log2(m / u)


@dataclass
class ComparisonParameters:
    """Estimated m/u per level for one comparison."""

    comparison_name: str
    levels: list[dict[str, Any]] = field(default_factory=list)
    # Each dict: {"label": str, "m": float, "u": float}


@dataclass
class TierParameters:
    """All estimated parameters for a tier."""

    tier_name: str
    comparisons: list[ComparisonParameters] = field(default_factory=list)
    prior_match_prob: float = 0.1

    @property
    def log_prior_odds(self) -> float:
        p = max(0.001, min(0.999, self.prior_match_prob))
        return math.log2(p / (1 - p))


class ParameterEstimator:
    """Estimates m/u probabilities from labeled data or EM."""

    def __init__(self, config: PipelineConfig):
        self.config = config

    def resolve_training_config(self, tier: MatchingTierConfig) -> TrainingConfig:
        """Resolve the effective training config for a tier.

        Delegates to PipelineConfig.effective_training_config() which
        handles the full resolution chain: tier-level → auto-retrain
        from label feedback → global training config.
        """
        return self.config.effective_training_config(tier)

    def needs_estimation(self, tier: MatchingTierConfig) -> bool:
        """Check if this tier needs parameter estimation."""
        if tier.threshold.method != "fellegi_sunter":
            return False
        training = self.resolve_training_config(tier)
        return training.method != "none"

    def extract_manual_params(self, tier: MatchingTierConfig) -> TierParameters:
        """Extract manually specified m/u from comparison level definitions."""
        comparisons = []
        for comp in tier.comparisons:
            safe_name = f"{comp.left}__{comp.method}".replace(".", "_")
            levels = []
            if comp.levels:
                for lvl in comp.levels:
                    levels.append({
                        "label": lvl.label,
                        "m": lvl.m if lvl.m is not None else 0.5,
                        "u": lvl.u if lvl.u is not None else 0.5,
                    })
            else:
                levels = [
                    {"label": "match", "m": 0.9, "u": 0.1},
                    {"label": "else", "m": 0.1, "u": 0.9},
                ]
            comparisons.append(ComparisonParameters(
                comparison_name=safe_name,
                levels=levels,
            ))
        return TierParameters(tier_name=tier.name, comparisons=comparisons)

    def generate_label_estimation_sql(
        self, tier: MatchingTierConfig, training: TrainingConfig
    ) -> str:
        """Generate SQL to estimate m/u from labeled pairs."""
        if not training.labeled_pairs_table:
            raise ParameterEstimationError(
                "labeled training requires labeled_pairs_table"
            )
        comparisons = self._build_level_expressions(tier)
        params = LabelEstimationParams(
            labeled_pairs_table=training.labeled_pairs_table,
            source_table=featured_table(self.config),
            comparisons=comparisons,
        )
        return build_estimate_from_labels_sql(params).render()

    def generate_em_estimation_sql(
        self, tier: MatchingTierConfig, training: TrainingConfig
    ) -> str:
        """Generate SQL for EM parameter estimation."""
        comparisons = self._build_level_expressions(tier)

        # Convert to EMComparison/EMLevel for the builder
        em_comparisons: list[EMComparison] = []
        for comp in comparisons:
            em_levels = [
                EMLevel(
                    label=lvl["label"],
                    sql_expr=lvl.get("sql_expr", ""),
                    has_expr=lvl.get("has_expr", False),
                )
                for lvl in comp["levels"]
            ]
            em_comparisons.append(EMComparison(
                name=comp["name"],
                left=comp["left"],
                right=comp["right"],
                levels=em_levels,
            ))

        params = EMParams(
            candidates_table=candidates_table(self.config, tier.name),
            source_table=featured_table(self.config),
            comparisons=em_comparisons,
            max_iterations=training.em_max_iterations,
            convergence_threshold=training.em_convergence_threshold,
            sample_size=training.em_sample_size,
            initial_match_proportion=training.em_initial_match_proportion,
        )
        return build_em_estimation_sql(params).render()

    def parse_estimation_results(
        self, tier: MatchingTierConfig, rows: list[dict[str, Any]]
    ) -> TierParameters:
        """Parse BigQuery result rows into TierParameters.

        Expected row format: {comparison_name, level_label, m_probability, u_probability}
        """
        comp_map: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            name = row["comparison_name"]
            if name not in comp_map:
                comp_map[name] = []
            comp_map[name].append({
                "label": row["level_label"],
                "m": max(0.001, min(0.999, row["m_probability"])),
                "u": max(0.001, min(0.999, row["u_probability"])),
            })

        comparisons = [
            ComparisonParameters(comparison_name=name, levels=levels)
            for name, levels in comp_map.items()
        ]

        # Estimate prior from overall match rate if available
        prior = 0.1
        if rows and "match_rate" in rows[0]:
            prior = max(0.001, min(0.999, rows[0]["match_rate"]))

        return TierParameters(
            tier_name=tier.name,
            comparisons=comparisons,
            prior_match_prob=prior,
        )

    def generate_reestimation_sql(
        self, tier: MatchingTierConfig, labels_tbl: str | None = None
    ) -> str:
        """Generate SQL to re-estimate m/u from accumulated labels.

        Uses the labels table (from active learning ingestion) as the
        labeled_pairs_table for estimation. This closes the feedback loop:
        review queue -> human labels -> retrain -> improved matching.
        """
        label_table = labels_tbl or labels_table(self.config)
        comparisons = self._build_level_expressions(tier)
        params = LabelEstimationParams(
            labeled_pairs_table=label_table,
            source_table=featured_table(self.config),
            comparisons=comparisons,
        )
        return build_estimate_from_labels_sql(params).render()

    def _build_level_expressions(self, tier: MatchingTierConfig) -> list[dict[str, Any]]:
        """Build SQL expressions for each comparison level.

        Returns list of:
        {
            "name": "first_name__exact",
            "left": "first_name_clean",
            "right": "first_name_clean",
            "levels": [
                {"label": "exact", "sql_expr": "...", "has_expr": True},
                {"label": "else", "sql_expr": None, "has_expr": False},
            ]
        }
        """
        udf_ds = udf_dataset(self.config)
        result = []

        for comp in tier.comparisons:
            safe_name = f"{comp.left}__{comp.method}".replace(".", "_")
            levels = []

            if comp.levels:
                for lvl in comp.levels:
                    if lvl.method is not None:
                        func = COMPARISON_FUNCTIONS.get(lvl.method)
                        if func is None:
                            raise ParameterEstimationError(
                                f"Unknown comparison method '{lvl.method}'"
                            )
                        params = {**lvl.params, "udf_dataset": udf_ds}
                        sql_expr = _validated_call(func, comp.left, comp.right, **params)
                        levels.append({
                            "label": lvl.label,
                            "sql_expr": sql_expr,
                            "has_expr": True,
                        })
                    else:
                        levels.append({
                            "label": lvl.label,
                            "sql_expr": None,
                            "has_expr": False,
                        })
            else:
                # Auto-create binary levels
                func = COMPARISON_FUNCTIONS.get(comp.method)
                if func is None:
                    raise ParameterEstimationError(
                        f"Unknown comparison method '{comp.method}'"
                    )
                params = {**comp.params, "udf_dataset": udf_ds}
                sql_expr = _validated_call(func, comp.left, comp.right, **params)
                levels = [
                    {"label": "match", "sql_expr": sql_expr, "has_expr": True},
                    {"label": "else", "sql_expr": None, "has_expr": False},
                ]

            result.append({
                "name": safe_name,
                "left": comp.left,
                "right": comp.right,
                "levels": levels,
            })

        return result

    def generate_persist_params_sql(
        self, params: TierParameters, target_table: str
    ) -> str:
        """Generate SQL to persist estimated parameters to a table."""
        from bq_entity_resolution.sql.utils import sql_escape

        rows = []
        for cp in params.comparisons:
            for lvl in cp.levels:
                m = lvl["m"]
                u = lvl["u"]
                log_w = math.log2(max(0.001, m) / max(0.001, u))
                safe_name = sql_escape(cp.comparison_name)
                safe_label = sql_escape(lvl['label'])
                rows.append(
                    f"  STRUCT<comparison_name STRING, level_label STRING, "
                    f"m_probability FLOAT64, u_probability FLOAT64, "
                    f"log_weight FLOAT64, prior_match_prob FLOAT64, "
                    f"estimated_at TIMESTAMP>"
                    f"('{safe_name}', '{safe_label}', "
                    f"{m}, {u}, {round(log_w, 6)}, "
                    f"{round(params.prior_match_prob, 6)}, CURRENT_TIMESTAMP())"
                )
        values = ",\n".join(rows)
        return (
            f"CREATE OR REPLACE TABLE `{target_table}` AS\n"
            f"SELECT * FROM UNNEST([\n"
            f"{values}\n"
            f"])"
        ) if rows else ""

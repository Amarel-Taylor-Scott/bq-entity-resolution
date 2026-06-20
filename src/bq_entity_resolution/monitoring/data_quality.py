"""Data quality scoring: aggregate 0-100 metric from multiple signals.

Computes a composite data quality score from placeholder detection rates,
null rates, and blocking effectiveness metrics. The score starts at 100
and deducts points for quality issues, floored at 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DataQualityScore:
    """Aggregate data quality score."""

    overall_score: int  # 0-100
    component_scores: dict[str, int] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)


class DataQualityScorer:
    """Compute data quality score from multiple signal sources.

    Scoring formula: starts at 100, deducts points for issues.

    Placeholder rates (per column):
        >5%  -> -10 pts
        >20% -> -25 pts (replaces -10)

    Null rates (per column):
        >10% -> -5 pts
        >50% -> -15 pts (replaces -5)

    Blocking effectiveness (per tier):
        reduction_ratio < 90% -> -10 pts
        reduction_ratio < 50% -> -25 pts (replaces -10)

    Max bucket size (per tier):
        >1,000  -> -5 pts
        >10,000 -> -15 pts (replaces -5)

    Floor at 0.
    """

    def compute(
        self,
        placeholder_rates: dict[str, float] | None = None,
        null_rates: dict[str, float] | None = None,
        blocking_stats: list[dict[str, Any]] | None = None,
    ) -> DataQualityScore:
        """Compute the aggregate data quality score.

        Args:
            placeholder_rates: {column_name: rate} where rate is 0.0-1.0.
            null_rates: {column_name: rate} where rate is 0.0-1.0.
            blocking_stats: List of dicts with keys:
                tier_name, reduction_ratio, max_candidates_per_entity.

        Returns:
            DataQualityScore with overall_score, component_scores, and details.
        """
        score = 100
        details: list[str] = []
        components: dict[str, int] = {}

        # Placeholder scoring
        ph_deductions = 0
        for col, rate in (placeholder_rates or {}).items():
            if rate > 0.20:
                ph_deductions += 25
                details.append(
                    f"Placeholder rate {rate:.1%} for '{col}' (>20%: -25 pts)"
                )
            elif rate > 0.05:
                ph_deductions += 10
                details.append(
                    f"Placeholder rate {rate:.1%} for '{col}' (>5%: -10 pts)"
                )
        components["placeholder"] = max(0, 100 - ph_deductions)
        score -= ph_deductions

        # Null rate scoring
        null_deductions = 0
        for col, rate in (null_rates or {}).items():
            if rate > 0.50:
                null_deductions += 15
                details.append(
                    f"Null rate {rate:.1%} for '{col}' (>50%: -15 pts)"
                )
            elif rate > 0.10:
                null_deductions += 5
                details.append(
                    f"Null rate {rate:.1%} for '{col}' (>10%: -5 pts)"
                )
        components["null_rates"] = max(0, 100 - null_deductions)
        score -= null_deductions

        # Blocking effectiveness scoring
        blocking_deductions = 0
        for stat in blocking_stats or []:
            tier = stat.get("tier_name", "?")
            rr = stat.get("reduction_ratio", 1.0)
            max_bucket = stat.get("max_candidates_per_entity", 0)

            if rr < 0.50:
                blocking_deductions += 25
                details.append(
                    f"Blocking reduction {rr:.1%} for tier '{tier}'"
                    f" (<50%: -25 pts)"
                )
            elif rr < 0.90:
                blocking_deductions += 10
                details.append(
                    f"Blocking reduction {rr:.1%} for tier '{tier}'"
                    f" (<90%: -10 pts)"
                )

            if max_bucket > 10000:
                blocking_deductions += 15
                details.append(
                    f"Max bucket size {max_bucket:,} for tier '{tier}'"
                    f" (>10K: -15 pts)"
                )
            elif max_bucket > 1000:
                blocking_deductions += 5
                details.append(
                    f"Max bucket size {max_bucket:,} for tier '{tier}'"
                    f" (>1K: -5 pts)"
                )

        components["blocking"] = max(0, 100 - blocking_deductions)
        score -= blocking_deductions

        overall = max(0, score)
        return DataQualityScore(
            overall_score=overall,
            component_scores=components,
            details=details,
        )

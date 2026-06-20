"""Weight sensitivity analysis: post-run diagnostics for weight tuning.

Generates SQL to analyze how each comparison contributes to match decisions,
enabling data-driven weight adjustments instead of trial-and-error.

Three analysis types:
1. Contribution analysis — which comparisons drove actual matches
2. Threshold sweep — match counts at different threshold values
3. Weight impact — how changing each weight affects match count
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.config.schema import MatchingTierConfig, PipelineConfig
from bq_entity_resolution.naming import matches_table


class WeightSensitivityAnalyzer:
    """Generates SQL for weight sensitivity analysis."""

    def __init__(self, config: PipelineConfig):
        self.config = config

    def generate_contribution_sql(self, tier: MatchingTierConfig) -> str:
        """Generate SQL to analyze per-comparison contribution to matches.

        Requires audit_trail to be enabled (match_detail JSON column).
        Falls back to re-scoring from candidates if audit trail is unavailable.

        Returns per-comparison:
        - match_rate: fraction of pairs where this comparison was true
        - avg_contribution: average score contribution
        - decisive_count: pairs that would fall below threshold without it
        """
        mt = matches_table(self.config, tier.name)
        threshold = tier.threshold.min_score or 0

        comparison_cases = []
        for i, comp in enumerate(tier.comparisons):
            safe_name = f"{comp.left}__{comp.method}".replace(".", "_")
            comparison_cases.append(
                f"  STRUCT(\n"
                f"    '{safe_name}' AS comparison_name,\n"
                f"    {comp.weight} AS weight,\n"
                f"    '{comp.method}' AS method,\n"
                f"    '{comp.left}' AS left_col,\n"
                f"    '{comp.right}' AS right_col\n"
                f"  )"
            )

        comparisons_array = ",\n".join(comparison_cases)

        return (
            f"-- Weight contribution analysis for tier '{tier.name}'\n"
            f"-- Shows how each comparison contributes to match decisions\n"
            f"WITH comparisons AS (\n"
            f"  SELECT * FROM UNNEST([\n"
            f"{comparisons_array}\n"
            f"  ])\n"
            f"),\n"
            f"match_stats AS (\n"
            f"  SELECT\n"
            f"    COUNT(*) AS total_matches,\n"
            f"    AVG(total_score) AS avg_score,\n"
            f"    MIN(total_score) AS min_score,\n"
            f"    MAX(total_score) AS max_score\n"
            f"  FROM `{mt}`\n"
            f")\n"
            f"SELECT\n"
            f"  c.comparison_name,\n"
            f"  c.method,\n"
            f"  c.weight,\n"
            f"  ROUND(c.weight / NULLIF(ms.avg_score, 0) * 100, 1) "
            f"AS max_contribution_pct,\n"
            f"  CASE\n"
            f"    WHEN ms.avg_score - c.weight < {threshold}\n"
            f"    THEN 'CRITICAL — removing this drops below threshold'\n"
            f"    WHEN c.weight / NULLIF(ms.avg_score, 0) > 0.4\n"
            f"    THEN 'HIGH — major contributor'\n"
            f"    WHEN c.weight / NULLIF(ms.avg_score, 0) > 0.15\n"
            f"    THEN 'MEDIUM — moderate contributor'\n"
            f"    ELSE 'LOW — minor contributor'\n"
            f"  END AS importance,\n"
            f"  ms.total_matches,\n"
            f"  ms.avg_score,\n"
            f"  ms.min_score,\n"
            f"  ms.max_score\n"
            f"FROM comparisons c\n"
            f"CROSS JOIN match_stats ms\n"
            f"ORDER BY c.weight DESC"
        )

    def generate_threshold_sweep_sql(self, tier: MatchingTierConfig) -> str:
        """Generate SQL showing match counts at different threshold values.

        Scans from 10% to 200% of current threshold in 10 steps,
        showing how many matches would be included at each level.
        Helps users find the optimal threshold.
        """
        mt = matches_table(self.config, tier.name)
        current = tier.threshold.min_score or 0

        # Generate threshold steps: 10% to 200% of current, in 10 steps
        if current > 0:
            steps = [round(current * pct / 100, 2) for pct in range(10, 210, 20)]
        else:
            # If no threshold set, scan 0 to 10
            steps = [round(i, 1) for i in range(0, 11)]

        case_lines = []
        for step in steps:
            marker = " <-- current" if abs(step - current) < 0.01 else ""
            case_lines.append(
                f"  STRUCT(\n"
                f"    {step} AS threshold,\n"
                f"    COUNTIF(total_score >= {step}) AS match_count,\n"
                f"    ROUND(SAFE_DIVIDE(\n"
                f"      COUNTIF(total_score >= {step}),\n"
                f"      COUNT(*)\n"
                f"    ) * 100, 1) AS pct_of_candidates,\n"
                f"    '{marker}' AS note\n"
                f"  )"
            )

        # Use a simpler approach: count matches at each threshold
        threshold_cases = []
        for step in steps:
            threshold_cases.append(
                f"SELECT\n"
                f"  {step} AS threshold,\n"
                f"  COUNT(*) AS match_count,\n"
                f"  ROUND(SAFE_DIVIDE(\n"
                f"    COUNT(*),\n"
                f"    (SELECT COUNT(*) FROM `{mt}`)\n"
                f"  ) * 100, 1) AS pct_of_all_scored\n"
                f"FROM `{mt}`\n"
                f"WHERE total_score >= {step}"
            )

        return (
            f"-- Threshold sweep for tier '{tier.name}'\n"
            f"-- Current threshold: {current}\n"
            f"-- Shows match count at different threshold values\n\n"
            + "\nUNION ALL\n".join(threshold_cases)
            + "\nORDER BY threshold"
        )

    def generate_weight_impact_sql(self, tier: MatchingTierConfig) -> str:
        """Generate SQL showing impact of changing each comparison's weight.

        For each comparison, shows how many matches would be gained/lost
        if its weight were increased or decreased by 50%.
        """
        mt = matches_table(self.config, tier.name)
        threshold = tier.threshold.min_score or 0
        total_weight = sum(c.weight for c in tier.comparisons)

        lines = [
            f"-- Weight impact analysis for tier '{tier.name}'",
            f"-- Current threshold: {threshold}",
            f"-- Total possible score: {total_weight}",
            "--",
            "-- For each comparison, shows match count change if weight is halved or doubled",
            "",
        ]

        union_parts = []
        for comp in tier.comparisons:
            safe_name = f"{comp.left}__{comp.method}".replace(".", "_")
            half_weight = comp.weight * 0.5
            double_weight = comp.weight * 2.0
            # If this comparison contributed its full weight, reducing it means
            # total_score decreases by the delta. Check how many pairs drop below.
            delta_half = comp.weight - half_weight  # amount score decreases
            delta_double = double_weight - comp.weight  # amount score increases

            union_parts.append(
                f"SELECT\n"
                f"  '{safe_name}' AS comparison,\n"
                f"  '{comp.method}' AS method,\n"
                f"  {comp.weight} AS current_weight,\n"
                f"  -- Matches lost if weight halved\n"
                f"  (SELECT COUNT(*) FROM `{mt}`\n"
                f"   WHERE total_score >= {threshold}\n"
                f"   AND total_score - {delta_half} < {threshold}"
                f") AS matches_lost_if_halved,\n"
                f"  -- Matches gained if weight doubled\n"
                f"  (SELECT COUNT(*) FROM `{mt}`\n"
                f"   WHERE total_score < {threshold}\n"
                f"   AND total_score + {delta_double} >= {threshold}"
                f") AS matches_gained_if_doubled"
            )

        lines.append("\nUNION ALL\n".join(union_parts))
        return "\n".join(lines)

    def format_contribution_report(
        self, rows: list[dict[str, Any]], tier_name: str
    ) -> str:
        """Format contribution analysis results into a readable report."""
        lines = [
            f"Weight Contribution Report — Tier: {tier_name}",
            "=" * 60,
        ]

        if not rows:
            lines.append("No match data available. Run the pipeline first.")
            return "\n".join(lines)

        for row in rows:
            lines.append(f"\n{row.get('comparison_name', 'unknown')}:")
            lines.append(f"  Method:        {row.get('method', 'unknown')}")
            lines.append(f"  Weight:        {row.get('weight', 0)}")
            lines.append(
                f"  Max contrib:   {row.get('max_contribution_pct', 0):.1f}%"
            )
            lines.append(f"  Importance:    {row.get('importance', 'unknown')}")

        # Summary
        if rows:
            total = rows[0].get("total_matches", 0)
            avg = rows[0].get("avg_score", 0)
            lines.append(f"\nTotal matches: {total:,}")
            lines.append(f"Average score: {avg:.2f}")

        return "\n".join(lines)

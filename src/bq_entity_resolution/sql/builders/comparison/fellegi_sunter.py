"""Fellegi-Sunter probabilistic scoring SQL builder.

Uses log-likelihood ratio scoring with comparison levels.
Total score = log_prior_odds + sum of per-comparison log-weights.
Match probability = 2^score / (1 + 2^score) with overflow clamping."""

from __future__ import annotations

from bq_entity_resolution.columns import (
    ENTITY_UID,
    IS_AUTO_MATCH,
    LEFT_ENTITY_UID,
    MATCH_BAND,
    MATCH_CONFIDENCE,
    MATCH_DETAIL,
    MATCH_TIER_NAME,
    MATCH_TIER_PRIORITY,
    MATCH_TOTAL_SCORE,
    MATCHED_AT,
    RIGHT_ENTITY_UID,
    TERM_FREQUENCY_RATIO,
    match_log_weight_column,
)
from bq_entity_resolution.sql.builders.comparison.models import (
    ComparisonDef,
    FellegiSunterParams,
)
from bq_entity_resolution.sql.builders.comparison.signals import (
    _build_auto_match_flag,
    _build_disqualify_filters,
    _build_hard_positive_boosts,
    _build_score_banding_expr,
    _build_tf_joins,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape


def _build_fs_level_case(
    comp: ComparisonDef,
    tf_table: str | None,
) -> str:
    """Build COALESCE(CASE ... END, 0.0) for a Fellegi-Sunter comparison.

    TF adjustment: Uses log(m/u) - log(max(u, tf_ratio)) instead of standard IDF.
    This is a heuristic that increases weight for rare terms (low tf_ratio) and
    decreases weight for common terms, similar to inverse document frequency but
    adapted for pairwise comparison context.
    """
    if not comp.levels:
        return "0.0"

    lines: list[str] = ["COALESCE(CASE"]

    for level in comp.levels:
        if level.sql_expr is not None:
            if level.tf_adjusted and tf_table:
                lines.append(
                    f"      WHEN {level.sql_expr} THEN\n"
                    f"        LOG({level.m}) / LOG(2)"
                    f" - LOG(GREATEST({level.u}, "
                    f"COALESCE(tf_{comp.name}."
                    f"{TERM_FREQUENCY_RATIO}, "
                    f"{comp.tf_minimum_u}))) / LOG(2)"
                )
            else:
                lines.append(f"      WHEN {level.sql_expr} THEN {level.log_weight}")
        else:
            lines.append(f"      ELSE {level.log_weight}")

    lines.append("    END, 0.0)")
    return "\n".join(lines)


def build_fellegi_sunter_sql(params: FellegiSunterParams) -> SQLExpression:
    """Build Fellegi-Sunter probabilistic scoring SQL.

    Uses log-likelihood ratio scoring with comparison levels.
    Total score = log_prior_odds + sum of per-comparison log-weights.
    Match probability = 2^score / (1 + 2^score) with overflow clamping.
    """
    if not params.comparisons:
        raise ValueError(
            f"Tier '{params.tier_name}' has no comparisons defined. "
            "At least one comparison is required for Fellegi-Sunter scoring."
        )

    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{params.matches_table}` AS")
    parts.append("")
    parts.append("WITH scored AS (")
    parts.append("  SELECT")
    parts.append(f"    c.{LEFT_ENTITY_UID},")
    parts.append(f"    c.{RIGHT_ENTITY_UID},")
    parts.append("")

    # Per-comparison level assignment and log-weight
    for comp in params.comparisons:
        case_expr = _build_fs_level_case(comp, params.tf_table)
        parts.append(f"    {case_expr} AS {match_log_weight_column(comp.name)},")

    parts.append("")

    # Total log-likelihood ratio score
    parts.append("    (")
    parts.append(f"      {params.log_prior_odds}")

    for comp in params.comparisons:
        case_expr = _build_fs_level_case(comp, params.tf_table)
        parts.append(f"      + {case_expr}")

    # Soft signal bonuses
    for ss in params.soft_signals:
        parts.append(
            f"      + CASE WHEN {ss.sql_condition} "
            f"THEN {ss.bonus} ELSE 0.0 END"
        )

    # Hard negative penalties
    for hn in params.hard_negatives:
        if hn.action == "penalize":
            parts.append(
                f"      + CASE WHEN {hn.sql_condition} "
                f"THEN {hn.penalty} ELSE 0.0 END"
            )

    # Hard positive boosts
    parts.extend(_build_hard_positive_boosts(params.hard_positives))

    parts.append(f"    ) AS {MATCH_TOTAL_SCORE}")

    # Pre-compute auto_match flag and elevate-band booleans inside the
    # scored CTE where l./r. aliases are in scope.
    auto_match_expr = _build_auto_match_flag(params.hard_positives)
    if auto_match_expr:
        parts.append(",")
        parts.append(f"    {auto_match_expr} AS {IS_AUTO_MATCH}")
    elevate_hps = [
        hp for hp in params.hard_positives if hp.action == "elevate_band"
    ]
    for i, hp in enumerate(elevate_hps):
        parts.append(",")
        parts.append(
            f"    CASE WHEN {hp.sql_condition} "
            f"THEN TRUE ELSE FALSE END AS _hp_elevate_{i}"
        )
    parts.append("")

    # FROM clause — same INT64 join pattern as sum scoring.
    # PERF: entity_uid is INT64 throughout the pipeline (FARM_FINGERPRINT-based).
    # Both INNER JOINs are 8-byte hash probes — minimal overhead.
    parts.append(f"  FROM `{params.candidates_table}` c")
    parts.append(
        f"  INNER JOIN `{params.source_table}` l "
        f"ON c.{LEFT_ENTITY_UID} = l.{ENTITY_UID}"
    )
    parts.append(
        f"  INNER JOIN `{params.source_table}` r "
        f"ON c.{RIGHT_ENTITY_UID} = r.{ENTITY_UID}"
    )

    # TF joins
    parts.extend(_build_tf_joins(params.comparisons, params.tf_table))

    # WHERE clause — disqualify filters eliminate pairs before
    # log-weight computation.
    parts.append("  WHERE 1=1")
    parts.extend(_build_disqualify_filters(params.hard_negatives))
    parts.append(")")
    parts.append("")

    # Final SELECT
    parts.append("SELECT")
    parts.append(f"  {LEFT_ENTITY_UID},")
    parts.append(f"  {RIGHT_ENTITY_UID},")
    parts.append(f"  {MATCH_TOTAL_SCORE},")
    parts.append(f"  {params.tier_index} AS {MATCH_TIER_PRIORITY},")
    parts.append(f"  '{sql_escape(params.tier_name)}' AS {MATCH_TIER_NAME},")

    # Match confidence with overflow clamping
    parts.append("  ROUND(CASE")
    parts.append(f"    WHEN {MATCH_TOTAL_SCORE} > 50 THEN 1.0")
    parts.append(f"    WHEN {MATCH_TOTAL_SCORE} < -50 THEN 0.0")
    parts.append(
        f"    ELSE SAFE_DIVIDE(POW(2.0, {MATCH_TOTAL_SCORE}), "
        f"1.0 + POW(2.0, {MATCH_TOTAL_SCORE}))"
    )
    parts.append(f"  END, 4) AS {MATCH_CONFIDENCE},")

    for comp in params.comparisons:
        parts.append(f"  {match_log_weight_column(comp.name)},")

    if params.audit_trail_enabled:
        struct_fields = ", ".join(
            match_log_weight_column(c.name) for c in params.comparisons
        )
        parts.append(
            f"  TO_JSON_STRING(STRUCT({struct_fields})) "
            f"AS {MATCH_DETAIL},"
        )

    # Auto-match flag (pre-computed in scored CTE)
    if auto_match_expr:
        parts.append(f"  {IS_AUTO_MATCH},")

    # Score banding (uses pre-computed elevate booleans from scored CTE)
    band_expr = _build_score_banding_expr(params.score_bands)
    if band_expr:
        if elevate_hps:
            result = band_expr
            for i, hp in enumerate(reversed(elevate_hps)):
                idx = len(elevate_hps) - 1 - i
                result = (
                    f"CASE WHEN _hp_elevate_{idx} "
                    f"THEN '{hp.target_band}' ELSE {result} END"
                )
            parts.append(f"  {result} AS {MATCH_BAND},")
        else:
            parts.append(f"  {band_expr} AS {MATCH_BAND},")

    parts.append(f"  CURRENT_TIMESTAMP() AS {MATCHED_AT}")
    parts.append("FROM scored")

    threshold_val = (
        params.threshold.match_threshold
        if params.threshold.match_threshold is not None
        else params.threshold.min_score
    )

    # Auto-match pairs bypass threshold (reference pre-computed flag)
    if auto_match_expr:
        parts.append(
            f"WHERE ({MATCH_TOTAL_SCORE} >= {threshold_val} "
            f"OR {IS_AUTO_MATCH} = TRUE)"
        )
    else:
        parts.append(
            f"WHERE {MATCH_TOTAL_SCORE} >= {threshold_val}"
        )

    # Minimum matching comparisons filter: require at least N comparisons
    # with positive log-weight (evidence for match) before accepting the pair.
    if params.threshold.min_matching_comparisons > 0:
        match_count_terms = [
            f"(CASE WHEN {match_log_weight_column(comp.name)} > 0 "
            f"THEN 1 ELSE 0 END)"
            for comp in params.comparisons
        ]
        match_count_expr = "\n    + ".join(match_count_terms)
        parts.append(
            f"AND (\n    {match_count_expr}\n"
            f") >= {params.threshold.min_matching_comparisons}"
        )

    return SQLExpression.from_raw("\n".join(parts))

__all__ = [
    "_build_fs_level_case",
    "build_fellegi_sunter_sql",
]

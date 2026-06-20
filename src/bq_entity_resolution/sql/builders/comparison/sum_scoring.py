"""Sum-based scoring SQL builder.

Generates SQL for weighted binary comparisons with aggregate score.
Each comparison produces a 0/1 score, multiplied by weight.
Total score = sum of weighted scores + soft signals - penalties."""

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
    match_score_column,
)
from bq_entity_resolution.sql.builders.comparison.models import SumScoringParams
from bq_entity_resolution.sql.builders.comparison.signals import (
    _build_auto_match_flag,
    _build_disqualify_filters,
    _build_hard_positive_boosts,
    _build_score_banding_expr,
    _build_tf_joins,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape


def build_sum_scoring_sql(params: SumScoringParams) -> SQLExpression:
    """Build sum-based scoring SQL.

    Each comparison produces a 0/1 score, multiplied by weight.
    Total score = sum of weighted scores + soft signals - penalties.
    """
    if not params.comparisons:
        raise ValueError(
            f"Tier '{params.tier_name}' has no comparisons defined. "
            "At least one comparison is required for scoring."
        )

    parts: list[str] = []

    parts.append(f"CREATE OR REPLACE TABLE `{params.matches_table}` AS")
    parts.append("")
    parts.append("WITH scored AS (")
    parts.append("  SELECT")
    parts.append(f"    c.{LEFT_ENTITY_UID},")
    parts.append(f"    c.{RIGHT_ENTITY_UID},")
    parts.append("")

    # Individual comparison scores
    for comp in params.comparisons:
        parts.append(
            f"    CASE WHEN {comp.sql_expr} THEN 1.0 ELSE 0.0 END "
            f"AS {match_score_column(comp.name)},"
        )

    parts.append("")
    # Weighted aggregate score
    parts.append("    (")

    score_terms: list[str] = []
    for comp in params.comparisons:
        if comp.tf_enabled and params.tf_table:
            score_terms.append(
                f"      CASE WHEN {comp.sql_expr}\n"
                f"        THEN {comp.weight} * LOG(1.0 / GREATEST("
                f"COALESCE(tf_{comp.name}.{TERM_FREQUENCY_RATIO}, {comp.tf_minimum_u}), "
                f"{comp.tf_minimum_u}))\n"
                f"        ELSE 0.0\n"
                f"      END"
            )
        else:
            score_terms.append(
                f"      {comp.weight} * (CASE WHEN {comp.sql_expr} "
                f"THEN 1.0 ELSE 0.0 END)"
            )

    parts.append("\n      + ".join(score_terms))

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

    # FROM clause with joins.
    # PERF: Both JOINs are on entity_uid (INT64) — this is the fastest
    # possible join pattern. The source table should be CLUSTER BY entity_uid
    # so BQ can co-locate the left and right lookups in storage.
    parts.append(f"  FROM `{params.candidates_table}` c")
    parts.append(
        f"  INNER JOIN `{params.source_table}` l "
        f"ON c.{LEFT_ENTITY_UID} = l.{ENTITY_UID}"
    )
    parts.append(
        f"  INNER JOIN `{params.source_table}` r "
        f"ON c.{RIGHT_ENTITY_UID} = r.{ENTITY_UID}"
    )

    # TF joins — each adds a LEFT JOIN on STRING keys (column_name, value).
    # PERF: Keep TF-enabled comparisons to a minimum (1-3) to avoid
    # join explosion. Each TF join scans the tf_stats table.
    parts.extend(_build_tf_joins(params.comparisons, params.tf_table))

    # WHERE clause — disqualify hard negatives filter pairs BEFORE scoring.
    # PERF: This is the most important optimization point. Disqualify
    # filters that use INT64 inequality or NULL checks eliminate pairs
    # before any expensive comparison runs.
    parts.append("  WHERE 1=1")
    parts.extend(_build_disqualify_filters(params.hard_negatives))
    parts.append(")")
    parts.append("")

    # Final SELECT with threshold
    parts.append("SELECT")
    parts.append(f"  {LEFT_ENTITY_UID},")
    parts.append(f"  {RIGHT_ENTITY_UID},")
    parts.append(f"  {MATCH_TOTAL_SCORE},")
    parts.append(f"  {params.tier_index} AS {MATCH_TIER_PRIORITY},")
    parts.append(f"  '{sql_escape(params.tier_name)}' AS {MATCH_TIER_NAME},")

    if params.confidence is not None:
        parts.append(f"  {params.confidence} AS {MATCH_CONFIDENCE},")
    elif params.confidence_method == "sigmoid":
        parts.append(
            f"  ROUND(1.0 / (1.0 + EXP(-1.0 * {MATCH_TOTAL_SCORE})), 4) "
            f"AS {MATCH_CONFIDENCE},"
        )
    else:
        parts.append(
            f"  ROUND({MATCH_TOTAL_SCORE} / "
            f"NULLIF({params.max_possible_score}, 0), 4) "
            f"AS {MATCH_CONFIDENCE},"
        )

    for comp in params.comparisons:
        parts.append(f"  {match_score_column(comp.name)},")

    if params.audit_trail_enabled:
        struct_fields = ", ".join(
            match_score_column(c.name) for c in params.comparisons
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

    # Auto-match pairs bypass threshold (reference pre-computed flag)
    if auto_match_expr:
        parts.append(
            f"WHERE ({MATCH_TOTAL_SCORE} >= {params.threshold.min_score} "
            f"OR {IS_AUTO_MATCH} = TRUE)"
        )
    else:
        parts.append(
            f"WHERE {MATCH_TOTAL_SCORE} >= "
            f"{params.threshold.min_score}"
        )

    # Minimum matching comparisons filter: require at least N comparisons
    # to score > 0 before accepting the pair.
    if params.threshold.min_matching_comparisons > 0:
        match_count_terms = [
            f"(CASE WHEN {comp.sql_expr} THEN 1 ELSE 0 END)"
            for comp in params.comparisons
        ]
        match_count_expr = "\n    + ".join(match_count_terms)
        parts.append(
            f"AND (\n    {match_count_expr}\n"
            f") >= {params.threshold.min_matching_comparisons}"
        )

    return SQLExpression.from_raw("\n".join(parts))

__all__ = [
    "build_sum_scoring_sql",
]

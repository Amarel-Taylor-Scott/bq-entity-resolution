"""SQL builder for matching/scoring (replaces tier_comparisons.sql.j2 + tier_fellegi_sunter.sql.j2).

Generates SQL for two scoring strategies:
1. Sum-based scoring: weighted binary comparisons with aggregate score
2. Fellegi-Sunter: log-likelihood ratio with m/u probabilities

Both support hard negatives, soft signals, term frequency adjustments,
and audit trail output.

BigQuery Scoring Performance Notes
====================================
The scoring SQL runs per candidate pair. If blocking produces N pairs,
every comparison expression is evaluated N times. Optimizations:

1. COMPARISON ORDERING: Comparisons are emitted in declaration order.
   For best performance, declare cheap comparisons first (exact on INT64,
   numeric_within) and expensive ones last (jaro_winkler, cosine_similarity).
   BigQuery evaluates CASE WHEN sequentially and can skip branches.
   See COMPARISON_COSTS in matching/comparisons.py for cost ranking.

2. JOIN PATTERN: Candidate pairs -> source table uses INNER JOIN on
   entity_uid (INT64). This is the tightest possible join -- 8 bytes
   per probe. The source table should be CLUSTER BY entity_uid for
   co-located reads.

3. TF JOINS: Each term-frequency-enabled comparison adds a LEFT JOIN
   to the tf_stats table. Keep TF comparisons minimal (1-3 max) to
   avoid join explosion. TF joins use STRING keys (column name + value).

4. HARD NEGATIVES: "disqualify" negatives become WHERE filters, applied
   BEFORE scoring. This eliminates pairs early and avoids wasted
   comparison computation. Place cheap conditions (INT64 inequality,
   NULL checks) as disqualify negatives for best pruning.
"""

from bq_entity_resolution.sql.builders.comparison.accumulation import (
    build_accumulate_matches_sql,
    build_init_matches_sql,
)
from bq_entity_resolution.sql.builders.comparison.fellegi_sunter import (
    _build_fs_level_case,
    build_fellegi_sunter_sql,
)
from bq_entity_resolution.sql.builders.comparison.models import (
    ComparisonDef,
    ComparisonLevel,
    FellegiSunterParams,
    HardNegative,
    HardPositive,
    ScoreBand,
    SoftSignal,
    SumScoringParams,
    Threshold,
)
from bq_entity_resolution.sql.builders.comparison.signals import (
    _build_auto_match_flag,
    _build_band_elevation_expr,
    _build_disqualify_filters,
    _build_hard_positive_boosts,
    _build_score_banding_expr,
    _build_tf_joins,
)
from bq_entity_resolution.sql.builders.comparison.sum_scoring import (
    build_sum_scoring_sql,
)

__all__ = [
    # Models
    "ComparisonLevel",
    "ComparisonDef",
    "HardNegative",
    "SoftSignal",
    "HardPositive",
    "ScoreBand",
    "Threshold",
    "SumScoringParams",
    "FellegiSunterParams",
    # Signals / helpers
    "_build_tf_joins",
    "_build_disqualify_filters",
    "_build_hard_positive_boosts",
    "_build_auto_match_flag",
    "_build_score_banding_expr",
    "_build_band_elevation_expr",
    # Sum-based scoring
    "build_sum_scoring_sql",
    # Fellegi-Sunter scoring
    "_build_fs_level_case",
    "build_fellegi_sunter_sql",
    # Match accumulation
    "build_init_matches_sql",
    "build_accumulate_matches_sql",
]

"""Tests for Fellegi-Sunter SQL generation via builders."""

import math

from bq_entity_resolution.sql.builders.comparison import (
    ComparisonDef as BuilderComparisonDef,
)
from bq_entity_resolution.sql.builders.comparison import (
    ComparisonLevel,
    FellegiSunterParams,
    SumScoringParams,
    Threshold,
    build_fellegi_sunter_sql,
    build_sum_scoring_sql,
)


def _log_weight(m: float, u: float) -> float:
    """Compute log2(m/u), clamping extreme values."""
    m = max(0.001, min(0.999, m))
    u = max(0.001, min(0.999, u))
    return round(math.log2(m / u), 6)


def _make_fs_params(
    comparisons=None,
    match_threshold=4.0,
    audit_trail_enabled=False,
    tf_table=None,
):
    """Create FellegiSunterParams for testing."""
    if comparisons is None:
        comparisons = [
            BuilderComparisonDef(
                name="first_name_clean__exact",
                levels=[
                    ComparisonLevel(
                        label="match",
                        sql_expr="l.first_name_clean = r.first_name_clean",
                        log_weight=_log_weight(0.9, 0.1),
                        m=0.9,
                        u=0.1,
                    ),
                    ComparisonLevel(
                        label="else",
                        sql_expr=None,
                        log_weight=_log_weight(0.1, 0.9),
                        m=0.1,
                        u=0.9,
                    ),
                ],
            ),
            BuilderComparisonDef(
                name="last_name_clean__exact",
                levels=[
                    ComparisonLevel(
                        label="match",
                        sql_expr="l.last_name_clean = r.last_name_clean",
                        log_weight=_log_weight(0.9, 0.1),
                        m=0.9,
                        u=0.1,
                    ),
                    ComparisonLevel(
                        label="else",
                        sql_expr=None,
                        log_weight=_log_weight(0.1, 0.9),
                        m=0.1,
                        u=0.9,
                    ),
                ],
            ),
        ]
    return FellegiSunterParams(
        tier_name="exact",
        tier_index=0,
        matches_table="proj.silver.matches_exact",
        candidates_table="proj.silver.candidates_exact",
        source_table="proj.silver.featured",
        comparisons=comparisons,
        log_prior_odds=-3.17,
        threshold=Threshold(method="fellegi_sunter", match_threshold=match_threshold),
        audit_trail_enabled=audit_trail_enabled,
        tf_table=tf_table,
    )


def test_fellegi_sunter_renders():
    """F-S SQL renders without errors."""
    params = _make_fs_params(match_threshold=4.0)
    sql = build_fellegi_sunter_sql(params).render()
    assert "CREATE OR REPLACE TABLE" in sql
    assert "POW(2.0, match_total_score)" in sql
    assert "match_confidence" in sql
    assert "match_log_weight_" in sql
    assert "4.0" in sql  # match_threshold
    # COALESCE guards against NULL from missing ELSE
    assert "COALESCE(CASE" in sql
    # Overflow protection: clamped match_confidence
    assert "WHEN match_total_score > 50 THEN 1.0" in sql


def test_fellegi_sunter_log_weights_in_sql():
    """F-S SQL contains computed log weights."""
    m, u = 0.95, 0.05
    expected_match_weight = round(math.log2(m / u), 6)
    expected_else_weight = round(math.log2(u / m), 6)

    comparisons = [
        BuilderComparisonDef(
            name="first_name_clean__exact",
            levels=[
                ComparisonLevel(
                    label="match",
                    sql_expr="l.first_name_clean = r.first_name_clean",
                    log_weight=expected_match_weight,
                    m=m,
                    u=u,
                ),
                ComparisonLevel(
                    label="else",
                    sql_expr=None,
                    log_weight=expected_else_weight,
                    m=u,
                    u=m,
                ),
            ],
        ),
    ]
    params = _make_fs_params(comparisons=comparisons, match_threshold=3.0)
    sql = build_fellegi_sunter_sql(params).render()

    assert str(expected_match_weight) in sql
    assert str(expected_else_weight) in sql


def test_fellegi_sunter_with_explicit_levels():
    """F-S with multi-level comparisons produces correct CASE/WHEN structure."""
    comparisons = [
        BuilderComparisonDef(
            name="first_name__multi",
            levels=[
                ComparisonLevel(
                    label="exact",
                    sql_expr="l.first_name_clean = r.first_name_clean",
                    log_weight=_log_weight(0.95, 0.01),
                    m=0.95,
                    u=0.01,
                ),
                ComparisonLevel(
                    label="fuzzy",
                    sql_expr="EDIT_DISTANCE(l.first_name_clean, r.first_name_clean) <= 2",
                    log_weight=_log_weight(0.70, 0.10),
                    m=0.70,
                    u=0.10,
                ),
                ComparisonLevel(
                    label="else",
                    sql_expr=None,
                    log_weight=_log_weight(0.05, 0.89),
                    m=0.05,
                    u=0.89,
                ),
            ],
        ),
    ]
    params = _make_fs_params(comparisons=comparisons, match_threshold=5.0)
    sql = build_fellegi_sunter_sql(params).render()

    # Should have WHEN clauses for each level
    assert "WHEN" in sql
    assert "ELSE" in sql
    assert "EDIT_DISTANCE" in sql  # levenshtein in fuzzy level


def test_sum_scoring_unchanged():
    """Sum-based scoring still works exactly as before."""
    params = SumScoringParams(
        tier_name="exact",
        tier_index=0,
        matches_table="proj.silver.matches_exact",
        candidates_table="proj.silver.candidates_exact",
        source_table="proj.silver.featured",
        comparisons=[
            BuilderComparisonDef(
                name="ck_name_addr__exact",
                sql_expr="l.ck_name_addr = r.ck_name_addr",
                weight=10.0,
            ),
        ],
        threshold=Threshold(method="score", min_score=10.0),
    )
    sql = build_sum_scoring_sql(params).render()
    assert "CASE WHEN" in sql
    assert "total_score" in sql
    # Should NOT have POW(2.0, ...) -- that's F-S only
    assert "POW(2.0" not in sql


def test_fellegi_sunter_coalesce_null_guard():
    """COALESCE wraps CASE to prevent NULL propagation from missing ELSE."""
    params = _make_fs_params()
    sql = build_fellegi_sunter_sql(params).render()
    # Every CASE is wrapped in COALESCE(..., 0.0)
    assert sql.count("COALESCE(CASE") >= 2  # at least per-column + total


def test_fellegi_sunter_overflow_clamp():
    """Match confidence uses clamping to avoid POW(2.0, x) overflow."""
    params = _make_fs_params(match_threshold=3.0)
    sql = build_fellegi_sunter_sql(params).render()
    # Clamp: high scores -> 1.0, low scores -> 0.0
    assert "WHEN match_total_score > 50 THEN 1.0" in sql
    assert "WHEN match_total_score < -50 THEN 0.0" in sql
    # Still uses POW for mid-range scores
    assert "SAFE_DIVIDE(POW(2.0, match_total_score)" in sql

"""Tests for the comparison/scoring SQL builder."""

from bq_entity_resolution.sql.builders.comparison import (
    ComparisonDef,
    ComparisonLevel,
    FellegiSunterParams,
    HardNegative,
    SoftSignal,
    SumScoringParams,
    Threshold,
    build_fellegi_sunter_sql,
    build_sum_scoring_sql,
)

# -- Sum-based scoring tests --


def test_sum_scoring_basic():
    """Basic sum scoring generates scored CTE with threshold."""
    params = SumScoringParams(
        tier_name="exact",
        tier_index=0,
        matches_table="proj.ds.matches_t1",
        candidates_table="proj.ds.candidates_t1",
        source_table="proj.ds.featured",
        comparisons=[
            ComparisonDef(
                name="name", sql_expr="l.name_clean = r.name_clean", weight=2.0
            ),
            ComparisonDef(
                name="dob", sql_expr="l.dob = r.dob", weight=1.5
            ),
        ],
        threshold=Threshold(min_score=2.0),
        max_possible_score=3.5,
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "WITH scored AS" in sql
    assert "l.name_clean = r.name_clean" in sql
    assert "match_score_name" in sql
    assert "match_score_dob" in sql
    assert "match_total_score" in sql
    assert "match_tier_priority" in sql
    assert "'exact'" in sql
    assert "WHERE match_total_score >= 2.0" in sql


def test_sum_scoring_hard_negative_disqualify():
    """Disqualification hard negative appears in WHERE."""
    params = SumScoringParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[ComparisonDef(name="x", sql_expr="l.x = r.x", weight=1.0)],
        hard_negatives=[
            HardNegative(
                sql_condition="l.dob != r.dob AND l.dob IS NOT NULL",
                action="disqualify",
            ),
        ],
        threshold=Threshold(min_score=0.5),
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "AND NOT (" in sql
    assert "l.dob != r.dob" in sql


def test_sum_scoring_hard_negative_penalize():
    """Penalty hard negative appears in score calculation."""
    params = SumScoringParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[ComparisonDef(name="x", sql_expr="l.x = r.x", weight=1.0)],
        hard_negatives=[
            HardNegative(
                sql_condition="l.age_diff > 5",
                action="penalize",
                penalty=-0.5,
            ),
        ],
        threshold=Threshold(min_score=0.5),
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "-0.5" in sql
    assert "l.age_diff > 5" in sql


def test_sum_scoring_soft_signal():
    """Soft signal bonus appears in score calculation."""
    params = SumScoringParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[ComparisonDef(name="x", sql_expr="l.x = r.x", weight=1.0)],
        soft_signals=[
            SoftSignal(sql_condition="l.zip = r.zip", bonus=0.5),
        ],
        threshold=Threshold(min_score=0.5),
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "l.zip = r.zip" in sql
    assert "0.5" in sql


def test_sum_scoring_fixed_confidence():
    """Fixed confidence value overrides calculated confidence."""
    params = SumScoringParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[ComparisonDef(name="x", sql_expr="l.x = r.x", weight=1.0)],
        confidence=0.99,
        threshold=Threshold(min_score=0.5),
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "0.99 AS match_confidence" in sql


def test_sum_scoring_tf_adjusted():
    """TF-adjusted comparison uses LOG-based weighting."""
    params = SumScoringParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="last",
                sql_expr="l.last_name = r.last_name",
                weight=2.0,
                tf_enabled=True,
                tf_column="last_name",
                tf_minimum_u=0.01,
            ),
        ],
        tf_table="proj.ds.tf_stats",
        threshold=Threshold(min_score=0.5),
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "LEFT JOIN" in sql
    assert "tf_last" in sql
    assert "LOG(" in sql
    assert "term_frequency_ratio" in sql


def test_sum_scoring_audit_trail():
    """Audit trail generates JSON match detail."""
    params = SumScoringParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[ComparisonDef(name="x", sql_expr="l.x = r.x", weight=1.0)],
        threshold=Threshold(min_score=0.5),
        audit_trail_enabled=True,
    )
    expr = build_sum_scoring_sql(params)
    sql = expr.render()

    assert "TO_JSON_STRING" in sql
    assert "match_detail" in sql


# -- Fellegi-Sunter scoring tests --


def test_fs_scoring_basic():
    """Basic F-S scoring generates log-weight columns."""
    params = FellegiSunterParams(
        tier_name="probabilistic",
        tier_index=1,
        matches_table="proj.ds.matches_t2",
        candidates_table="proj.ds.candidates_t2",
        source_table="proj.ds.featured",
        comparisons=[
            ComparisonDef(
                name="name",
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.name_clean = r.name_clean",
                        log_weight=5.0,
                        m=0.95,
                        u=0.01,
                    ),
                    ComparisonLevel(
                        label="else",
                        sql_expr=None,
                        log_weight=-2.0,
                    ),
                ],
            ),
        ],
        log_prior_odds=-3.0,
        threshold=Threshold(match_threshold=2.0),
    )
    expr = build_fellegi_sunter_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "log_weight_name" in sql
    assert "COALESCE(CASE" in sql
    assert "total_score" in sql
    assert "-3.0" in sql
    assert "match_confidence" in sql
    assert "POW(2.0, match_total_score)" in sql
    assert "WHERE match_total_score >= 2.0" in sql


def test_fs_scoring_overflow_clamp():
    """F-S scoring clamps POW(2, score) to prevent overflow."""
    params = FellegiSunterParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="x",
                levels=[
                    ComparisonLevel(label="match", sql_expr="l.x = r.x", log_weight=5.0),
                    ComparisonLevel(label="else", sql_expr=None, log_weight=-1.0),
                ],
            ),
        ],
        threshold=Threshold(match_threshold=0.0),
    )
    expr = build_fellegi_sunter_sql(params)
    sql = expr.render()

    assert "WHEN match_total_score > 50 THEN 1.0" in sql
    assert "WHEN match_total_score < -50 THEN 0.0" in sql


def test_fs_scoring_null_coalesce():
    """F-S scoring wraps CASE in COALESCE to guard against NULL."""
    params = FellegiSunterParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="x",
                levels=[
                    ComparisonLevel(label="match", sql_expr="l.x = r.x", log_weight=5.0),
                    # No ELSE clause — COALESCE guards against NULL
                ],
            ),
        ],
        threshold=Threshold(min_score=0.0),
    )
    expr = build_fellegi_sunter_sql(params)
    sql = expr.render()

    assert "COALESCE(CASE" in sql
    assert ", 0.0)" in sql


def test_fs_scoring_tf_adjusted():
    """F-S TF-adjusted level uses dynamic log2(m/u)."""
    params = FellegiSunterParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="last",
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.last_name = r.last_name",
                        log_weight=5.0,
                        m=0.95,
                        u=0.01,
                        tf_adjusted=True,
                    ),
                    ComparisonLevel(label="else", sql_expr=None, log_weight=-1.0),
                ],
                tf_enabled=True,
                tf_column="last_name",
                tf_minimum_u=0.01,
            ),
        ],
        tf_table="proj.ds.tf_stats",
        threshold=Threshold(min_score=0.0),
    )
    expr = build_fellegi_sunter_sql(params)
    sql = expr.render()

    assert "LOG(0.95) / LOG(2)" in sql
    assert "tf_last.term_frequency_ratio" in sql
    assert "LEFT JOIN" in sql


def test_fs_scoring_uses_match_threshold():
    """F-S uses match_threshold when set."""
    params = FellegiSunterParams(
        tier_name="t1",
        tier_index=0,
        matches_table="p.d.matches",
        candidates_table="p.d.candidates",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="x",
                levels=[ComparisonLevel(label="m", sql_expr="1=1", log_weight=1.0)],
            ),
        ],
        threshold=Threshold(match_threshold=5.0, min_score=2.0),
    )
    expr = build_fellegi_sunter_sql(params)
    sql = expr.render()

    assert "WHERE match_total_score >= 5.0" in sql
    assert "WHERE match_total_score >= 2.0" not in sql

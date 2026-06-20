"""Tests for per-match audit trail via builders."""

from bq_entity_resolution.config.schema import AuditTrailConfig
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

# ---------------------------------------------------------------
# Config model tests
# ---------------------------------------------------------------


def test_audit_trail_config_defaults():
    """Default audit trail config is disabled."""
    at = AuditTrailConfig()
    assert not at.enabled
    assert at.include_individual_scores


def test_audit_trail_config_enabled():
    """Audit trail config can be enabled."""
    at = AuditTrailConfig(enabled=True)
    assert at.enabled


# ---------------------------------------------------------------
# Sum-based scoring: audit trail
# ---------------------------------------------------------------


def _make_sum_params(audit_trail_enabled=False):
    return SumScoringParams(
        tier_name="fuzzy",
        tier_index=1,
        matches_table="proj.silver.matches_fuzzy",
        candidates_table="proj.silver.candidates_fuzzy",
        source_table="proj.silver.featured",
        comparisons=[
            BuilderComparisonDef(
                name="first_name_clean__levenshtein",
                sql_expr="EDIT_DISTANCE(l.first_name_clean, r.first_name_clean) <= 2",
                weight=3.0,
            ),
            BuilderComparisonDef(
                name="last_name_clean__exact",
                sql_expr="l.last_name_clean = r.last_name_clean",
                weight=3.0,
            ),
        ],
        threshold=Threshold(method="score", min_score=6.0),
        audit_trail_enabled=audit_trail_enabled,
    )


def test_sum_audit_trail_includes_match_detail():
    """Sum-based scoring includes TO_JSON_STRING match_detail when audit enabled."""
    params = _make_sum_params(audit_trail_enabled=True)
    sql = build_sum_scoring_sql(params).render()
    assert "TO_JSON_STRING" in sql
    assert "match_detail" in sql


def test_sum_no_audit_trail_by_default():
    """Sum-based scoring does NOT include match_detail when audit disabled."""
    params = _make_sum_params(audit_trail_enabled=False)
    sql = build_sum_scoring_sql(params).render()
    assert "match_detail" not in sql


# ---------------------------------------------------------------
# F-S scoring: audit trail
# ---------------------------------------------------------------


def _make_fs_params(audit_trail_enabled=False):
    return FellegiSunterParams(
        tier_name="fuzzy",
        tier_index=1,
        matches_table="proj.silver.matches_fuzzy",
        candidates_table="proj.silver.candidates_fuzzy",
        source_table="proj.silver.featured",
        comparisons=[
            BuilderComparisonDef(
                name="first_name_clean__exact",
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.first_name_clean = r.first_name_clean",
                        log_weight=3.17,
                        m=0.9,
                        u=0.1,
                    ),
                    ComparisonLevel(
                        label="else",
                        sql_expr=None,
                        log_weight=-3.17,
                        m=0.1,
                        u=0.9,
                    ),
                ],
            ),
        ],
        log_prior_odds=-3.17,
        threshold=Threshold(method="fellegi_sunter", match_threshold=5.0),
        audit_trail_enabled=audit_trail_enabled,
    )


def test_fs_audit_trail_includes_match_detail():
    """F-S scoring includes TO_JSON_STRING match_detail when audit enabled."""
    params = _make_fs_params(audit_trail_enabled=True)
    sql = build_fellegi_sunter_sql(params).render()
    assert "TO_JSON_STRING" in sql
    assert "match_detail" in sql

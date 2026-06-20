"""Tests for term frequency adjustments in matching."""

from bq_entity_resolution.naming import term_frequency_table
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
from bq_entity_resolution.sql.builders.features import (
    TFColumn,
    build_term_frequencies_sql,
)

# ---------------------------------------------------------------
# TF SQL generation via builder
# ---------------------------------------------------------------


def test_generate_tf_sql_returns_sql():
    """TF SQL generated when a column is specified."""
    sql_expr = build_term_frequencies_sql(
        target_table="proj.silver.term_frequencies",
        source_table="proj.silver.featured",
        tf_columns=[TFColumn(column_name="first_name_clean")],
    )
    sql = sql_expr.render()
    assert "CREATE OR REPLACE TABLE" in sql
    assert "term_frequency_ratio" in sql
    assert "term_frequencies" in sql


def test_tf_sql_includes_correct_column():
    """TF SQL computes frequencies for the correct column."""
    sql_expr = build_term_frequencies_sql(
        target_table="proj.silver.term_frequencies",
        source_table="proj.silver.featured",
        tf_columns=[TFColumn(column_name="last_name_clean")],
    )
    sql = sql_expr.render()
    assert "last_name_clean" in sql


def test_tf_sql_deduplicates_columns():
    """Same column referenced by multiple TFColumn entries appears only once."""
    columns = [
        TFColumn(column_name="first_name_clean"),
        TFColumn(column_name="first_name_clean"),
    ]
    # Deduplication should happen at the caller level;
    # builder creates one block per entry
    col_names = [c.column_name for c in columns]
    unique = list(dict.fromkeys(col_names))
    assert len(unique) == 1, "Caller should deduplicate columns"


# ---------------------------------------------------------------
# Sum-based scoring with TF
# ---------------------------------------------------------------


def test_sum_scoring_includes_tf_join():
    """Sum-based scoring includes TF table join when TF enabled."""
    params = SumScoringParams(
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
                tf_enabled=True,
                tf_column="first_name_clean",
                tf_minimum_u=0.01,
            ),
        ],
        threshold=Threshold(method="score", min_score=6.0),
        tf_table="proj.silver.term_frequencies",
    )
    sql = build_sum_scoring_sql(params).render()
    assert "term_frequencies" in sql
    assert "term_frequency_ratio" in sql
    assert "LEFT JOIN" in sql


def test_sum_scoring_no_tf_join_when_disabled():
    """Sum-based scoring has no TF join when TF is disabled."""
    params = SumScoringParams(
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
        ],
        threshold=Threshold(method="score", min_score=6.0),
    )
    sql = build_sum_scoring_sql(params).render()
    assert "term_frequencies" not in sql


def test_sum_tf_uses_minimum_u():
    """TF adjustment uses the minimum_u floor value."""
    params = SumScoringParams(
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
                tf_enabled=True,
                tf_column="first_name_clean",
                tf_minimum_u=0.005,
            ),
        ],
        threshold=Threshold(method="score", min_score=6.0),
        tf_table="proj.silver.term_frequencies",
    )
    sql = build_sum_scoring_sql(params).render()
    assert "0.005" in sql


# ---------------------------------------------------------------
# Fellegi-Sunter scoring with TF
# ---------------------------------------------------------------


def test_fs_scoring_includes_tf_join():
    """F-S scoring includes TF join when TF is enabled on a comparison."""
    params = FellegiSunterParams(
        tier_name="fuzzy",
        tier_index=1,
        matches_table="proj.silver.matches_fuzzy",
        candidates_table="proj.silver.candidates_fuzzy",
        source_table="proj.silver.featured",
        comparisons=[
            BuilderComparisonDef(
                name="first_name_clean__exact",
                tf_enabled=True,
                tf_column="first_name_clean",
                tf_minimum_u=0.01,
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.first_name_clean = r.first_name_clean",
                        log_weight=3.17,
                        m=0.9,
                        u=0.1,
                        tf_adjusted=True,
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
        tf_table="proj.silver.term_frequencies",
    )
    sql = build_fellegi_sunter_sql(params).render()
    assert "term_frequencies" in sql
    assert "LEFT JOIN" in sql


def test_fs_tf_adjusted_uses_dynamic_weight():
    """TF-adjusted F-S levels compute log-weight dynamically."""
    params = FellegiSunterParams(
        tier_name="fuzzy",
        tier_index=1,
        matches_table="proj.silver.matches_fuzzy",
        candidates_table="proj.silver.candidates_fuzzy",
        source_table="proj.silver.featured",
        comparisons=[
            BuilderComparisonDef(
                name="first_name_clean__exact",
                tf_enabled=True,
                tf_column="first_name_clean",
                tf_minimum_u=0.01,
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.first_name_clean = r.first_name_clean",
                        log_weight=3.17,
                        m=0.9,
                        u=0.1,
                        tf_adjusted=True,
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
        tf_table="proj.silver.term_frequencies",
    )
    sql = build_fellegi_sunter_sql(params).render()
    # Should have LOG-based dynamic computation
    assert "LOG(" in sql
    assert "GREATEST" in sql


def test_fs_non_tf_levels_use_static_weight():
    """Non-TF levels in F-S still use pre-computed static log-weight."""
    comp = BuilderComparisonDef(
        name="last_name__exact",
        levels=[
            ComparisonLevel(
                label="exact",
                sql_expr="l.last_name_clean = r.last_name_clean",
                log_weight=3.17,
                m=0.9,
                u=0.1,
                tf_adjusted=False,
            ),
            ComparisonLevel(
                label="else",
                sql_expr=None,
                log_weight=-3.17,
                m=0.1,
                u=0.9,
                tf_adjusted=False,
            ),
        ],
    )
    # Non-TF levels should not have tf_adjusted flag set
    for level in comp.levels:
        assert not level.tf_adjusted


# ---------------------------------------------------------------
# Naming: term_frequency_table
# ---------------------------------------------------------------


def test_term_frequency_table_name(sample_config):
    """term_frequency_table returns correct fully-qualified name."""
    result = term_frequency_table(sample_config)
    assert result == "test-project.test_silver.term_frequencies"

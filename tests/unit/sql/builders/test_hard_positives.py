"""Tests for hard positive and score banding SQL builders."""
from __future__ import annotations

from bq_entity_resolution.sql.builders.comparison import (
    ComparisonDef,
    ComparisonLevel,
    FellegiSunterParams,
    HardPositive,
    ScoreBand,
    SumScoringParams,
    Threshold,
    _build_auto_match_flag,
    _build_band_elevation_expr,
    _build_hard_positive_boosts,
    _build_score_banding_expr,
    build_fellegi_sunter_sql,
    build_sum_scoring_sql,
)


class TestBuildHardPositiveBoosts:
    """Tests for _build_hard_positive_boosts()."""
    def test_generates_case_when_for_boost(self):
        hps = [HardPositive(
            sql_condition="l.email = r.email",
            action="boost",
            boost=5.0,
        )]
        lines = _build_hard_positive_boosts(hps)
        assert len(lines) == 1
        assert "CASE WHEN l.email = r.email THEN 5.0 ELSE 0.0 END" in lines[0]
    def test_ignores_auto_match_actions(self):
        hps = [HardPositive(
            sql_condition="l.ssn = r.ssn",
            action="auto_match",
            boost=0.0,
        )]
        lines = _build_hard_positive_boosts(hps)
        assert len(lines) == 0
    def test_multiple_boosts(self):
        hps = [
            HardPositive(
                sql_condition="l.a = r.a",
                action="boost",
                boost=3.0,
            ),
            HardPositive(
                sql_condition="l.b = r.b",
                action="boost",
                boost=2.0,
            ),
        ]
        lines = _build_hard_positive_boosts(hps)
        assert len(lines) == 2

class TestBuildAutoMatchFlag:
    """Tests for _build_auto_match_flag()."""
    def test_generates_flag_sql(self):
        hps = [HardPositive(
            sql_condition="l.ssn = r.ssn",
            action="auto_match",
        )]
        result = _build_auto_match_flag(hps)
        assert result is not None
        assert "l.ssn = r.ssn" in result
        assert "TRUE" in result
    def test_returns_none_when_no_auto_match(self):
        hps = [HardPositive(
            sql_condition="l.a = r.a",
            action="boost",
            boost=5.0,
        )]
        assert _build_auto_match_flag(hps) is None
    def test_combines_multiple_auto_match(self):
        hps = [
            HardPositive(
                sql_condition="l.ssn = r.ssn",
                action="auto_match",
            ),
            HardPositive(
                sql_condition="l.ein = r.ein",
                action="auto_match",
            ),
        ]
        result = _build_auto_match_flag(hps)
        assert "l.ssn = r.ssn" in result
        assert "l.ein = r.ein" in result
        assert "OR" in result

class TestBuildScoreBandingExpr:
    """Tests for _build_score_banding_expr()."""
    def test_generates_case_when_for_bands(self):
        bands = [
            ScoreBand(name="HIGH", min_score=8.0),
            ScoreBand(
                name="LOW",
                min_score=0.0,
                max_score=8.0,
            ),
        ]
        result = _build_score_banding_expr(bands)
        assert result is not None
        assert "HIGH" in result and "LOW" in result and "CASE" in result
    def test_returns_none_for_empty_bands(self):
        assert _build_score_banding_expr([]) is None
    def test_sorts_bands_by_min_score_desc(self):
        bands = [
            ScoreBand(
                name="LOW",
                min_score=0.0,
                max_score=5.0,
            ),
            ScoreBand(name="HIGH", min_score=8.0),
        ]
        result = _build_score_banding_expr(bands)
        assert result.index("HIGH") < result.index("LOW")

class TestBuildBandElevationExpr:
    """Tests for _build_band_elevation_expr()."""
    def test_wraps_with_hard_positive_elevations(self):
        base_expr = "CASE WHEN score >= 8.0 THEN 'HIGH' ELSE 'LOW' END"
        hps = [HardPositive(
            sql_condition="l.ssn = r.ssn",
            action="elevate_band",
            target_band="HIGH",
        )]
        result = _build_band_elevation_expr(base_expr, hps)
        assert "l.ssn = r.ssn" in result and "'HIGH'" in result
    def test_no_elevation_returns_base(self):
        base_expr = "CASE WHEN score >= 8.0 THEN 'HIGH' ELSE 'LOW' END"
        hps = [HardPositive(
            sql_condition="l.a = r.a",
            action="boost",
            boost=5.0,
        )]
        result = _build_band_elevation_expr(base_expr, hps)
        assert result == base_expr

def _make_sum_params(**kwargs):
    defaults = dict(
        tier_name="exact",
        tier_index=0,
        matches_table="proj.silver.matches_exact",
        candidates_table="proj.silver.candidates_exact",
        source_table="proj.silver.featured",
        comparisons=[ComparisonDef(
            name="email",
            sql_expr="l.email = r.email",
            weight=5.0,
        )],
        threshold=Threshold(min_score=5.0),
    )
    defaults.update(kwargs)
    return SumScoringParams(**defaults)

class TestBuildSumScoringWithSignals:
    """Tests for build_sum_scoring_sql() with hard positives and bands."""
    def test_includes_hard_positive_boost_in_score(self):
        params = _make_sum_params(
            hard_positives=[HardPositive(
                sql_condition="l.ssn = r.ssn",
                action="boost",
                boost=10.0,
            )],
        )
        sql = build_sum_scoring_sql(params).render()
        assert "l.ssn = r.ssn" in sql and "10.0" in sql
    def test_includes_auto_match_flag_column(self):
        params = _make_sum_params(
            hard_positives=[HardPositive(
                sql_condition="l.ssn = r.ssn",
                action="auto_match",
            )],
        )
        sql = build_sum_scoring_sql(params).render()
        assert "is_auto_match" in sql
    def test_includes_match_band_column(self):
        params = _make_sum_params(
            score_bands=[
                ScoreBand(name="HIGH", min_score=8.0),
                ScoreBand(
                    name="LOW",
                    min_score=0.0,
                    max_score=8.0,
                ),
            ],
        )
        sql = build_sum_scoring_sql(params).render()
        assert "match_band" in sql
    def test_auto_match_bypasses_threshold(self):
        params = _make_sum_params(
            hard_positives=[HardPositive(
                sql_condition="l.ssn = r.ssn",
                action="auto_match",
            )],
        )
        sql = build_sum_scoring_sql(params).render()
        # Auto-match flag computed in scored CTE, WHERE uses column ref
        assert "is_auto_match" in sql
        assert "OR is_auto_match = TRUE" in sql
        assert "l.ssn = r.ssn" in sql  # In scored CTE

def _make_fs_params(**kwargs):
    defaults = dict(
        tier_name="prob",
        tier_index=0,
        matches_table="proj.silver.matches_prob",
        candidates_table="proj.silver.candidates_prob",
        source_table="proj.silver.featured",
        comparisons=[ComparisonDef(
            name="email",
            levels=[
                ComparisonLevel(
                    label="exact",
                    sql_expr="l.email = r.email",
                    log_weight=3.0,
                    m=0.95,
                    u=0.01,
                ),
                ComparisonLevel(
                    label="else",
                    sql_expr=None,
                    log_weight=-1.0,
                    m=0.05,
                    u=0.99,
                ),
            ],
        )],
        threshold=Threshold(
            min_score=0.0,
            match_threshold=2.0,
        ),
    )
    defaults.update(kwargs)
    return FellegiSunterParams(**defaults)

class TestBuildFellegiSunterWithSignals:
    """Tests for build_fellegi_sunter_sql() with hard positives and bands."""
    def test_includes_hard_positive_boost(self):
        params = _make_fs_params(
            hard_positives=[HardPositive(
                sql_condition="l.ssn = r.ssn",
                action="boost",
                boost=10.0,
            )],
        )
        sql = build_fellegi_sunter_sql(params).render()
        assert "l.ssn = r.ssn" in sql and "10.0" in sql
    def test_includes_score_banding(self):
        params = _make_fs_params(
            score_bands=[
                ScoreBand(name="HIGH", min_score=5.0),
                ScoreBand(
                    name="LOW",
                    min_score=0.0,
                    max_score=5.0,
                ),
            ],
        )
        sql = build_fellegi_sunter_sql(params).render()
        assert "match_band" in sql and "HIGH" in sql

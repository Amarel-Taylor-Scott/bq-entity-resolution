"""Tests for the golden record SQL builder.

Validates all 5 merge strategies:
- most_complete (default)
- most_recent
- source_priority
- most_common
- weighted_vote
"""

from bq_entity_resolution.sql.builders.golden_record import (
    FieldStrategy,
    GoldenRecordParams,
    _build_order_by,
    _build_vote_cte,
    build_golden_record_cte,
)


class TestBuildOrderBy:
    def test_most_complete_order(self):
        s = FieldStrategy(column="name", strategy="most_complete")
        order = _build_order_by(s)
        assert "completeness_score DESC" in order
        assert "source_updated_at DESC" in order

    def test_most_recent_order(self):
        s = FieldStrategy(column="name", strategy="most_recent")
        order = _build_order_by(s)
        assert "source_updated_at DESC" in order
        assert "completeness_score" not in order

    def test_source_priority_order(self):
        s = FieldStrategy(
            column="name",
            strategy="source_priority",
            source_priority=["crm", "erp"],
        )
        order = _build_order_by(s)
        assert "CASE source_name" in order
        assert "WHEN 'crm' THEN 0" in order
        assert "WHEN 'erp' THEN 1" in order
        assert "ELSE 999" in order

    def test_source_priority_empty_falls_back(self):
        """Empty source_priority falls back to most_complete."""
        s = FieldStrategy(column="name", strategy="source_priority")
        order = _build_order_by(s)
        assert "completeness_score DESC" in order


class TestBuildVoteCte:
    def test_most_common_uses_count(self):
        s = FieldStrategy(column="city", strategy="most_common")
        cte = _build_vote_cte("city", s)
        assert "vote_city AS" in cte
        assert "COUNT(*) AS vote_weight" in cte
        assert "cluster_id" in cte
        assert "GROUP BY" in cte
        assert "QUALIFY ROW_NUMBER()" in cte

    def test_weighted_vote_uses_exp_decay(self):
        s = FieldStrategy(column="phone", strategy="weighted_vote", decay_rate=0.05)
        cte = _build_vote_cte("phone", s)
        assert "vote_phone AS" in cte
        assert "EXP(-0.05" in cte
        assert "TIMESTAMP_DIFF" in cte
        assert "SUM(" in cte


class TestBuildGoldenRecordCte:
    def test_default_strategy_most_complete(self):
        """Default strategy uses FIRST_VALUE with completeness ordering."""
        params = GoldenRecordParams(
            source_columns=["first_name", "last_name", "email"],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "clustered_scored AS" in sql
        assert "completeness_score" in sql
        assert "golden_fields AS" in sql
        assert "FIRST_VALUE(first_name IGNORE NULLS)" in sql
        assert "FIRST_VALUE(last_name IGNORE NULLS)" in sql
        assert "FIRST_VALUE(email IGNORE NULLS)" in sql

    def test_most_recent_strategy(self):
        params = GoldenRecordParams(
            source_columns=["first_name"],
            field_strategies=[
                FieldStrategy(column="first_name", strategy="most_recent"),
            ],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "FIRST_VALUE(first_name IGNORE NULLS)" in sql
        assert "source_updated_at DESC" in sql

    def test_source_priority_strategy(self):
        params = GoldenRecordParams(
            source_columns=["email"],
            field_strategies=[
                FieldStrategy(
                    column="email",
                    strategy="source_priority",
                    source_priority=["crm", "erp"],
                ),
            ],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "FIRST_VALUE(email IGNORE NULLS)" in sql
        assert "CASE source_name" in sql
        assert "'crm'" in sql

    def test_most_common_strategy(self):
        params = GoldenRecordParams(
            source_columns=["city"],
            field_strategies=[
                FieldStrategy(column="city", strategy="most_common"),
            ],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "vote_city AS" in sql
        assert "COUNT(*)" in sql
        assert "COALESCE(" in sql
        assert "vote_city.voted_value" in sql
        assert "LEFT JOIN vote_city" in sql

    def test_weighted_vote_strategy(self):
        params = GoldenRecordParams(
            source_columns=["phone"],
            field_strategies=[
                FieldStrategy(column="phone", strategy="weighted_vote", decay_rate=0.02),
            ],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "vote_phone AS" in sql
        assert "EXP(-0.02" in sql
        assert "LEFT JOIN vote_phone" in sql

    def test_mixed_strategies(self):
        """Different columns can use different strategies."""
        params = GoldenRecordParams(
            source_columns=["first_name", "email", "city"],
            field_strategies=[
                FieldStrategy(column="first_name", strategy="most_recent"),
                FieldStrategy(column="email", strategy="source_priority", source_priority=["crm"]),
                FieldStrategy(column="city", strategy="most_common"),
            ],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "vote_city AS" in sql
        assert "FIRST_VALUE(first_name IGNORE NULLS)" in sql
        assert "FIRST_VALUE(email IGNORE NULLS)" in sql
        assert "LEFT JOIN vote_city" in sql

    def test_scoring_columns_override(self):
        """scoring_columns overrides source_columns for completeness scoring."""
        params = GoldenRecordParams(
            source_columns=["a", "b", "c"],
            scoring_columns=["a", "b"],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        # Should only count a and b for score, not c
        score_section = sql.split("clustered_scored")[1].split(")")[0]
        assert "a IS NOT NULL" in score_section
        assert "b IS NOT NULL" in score_section

    def test_source_priority_ranking(self):
        """Source priority list generates CASE expression."""
        params = GoldenRecordParams(
            source_columns=["name"],
            source_priority=["alpha", "beta", "gamma"],
        )
        expr = build_golden_record_cte(params)
        sql = expr.render()

        assert "WHEN 'alpha' THEN 0" in sql
        assert "WHEN 'beta' THEN 1" in sql
        assert "WHEN 'gamma' THEN 2" in sql
        assert "ELSE 999" in sql

    def test_returns_sql_expression(self):
        params = GoldenRecordParams(source_columns=["x"])
        expr = build_golden_record_cte(params)
        assert expr.is_raw is True
        assert isinstance(expr.render(), str)

    def test_row_number_for_dedup(self):
        """Golden fields CTE includes ROW_NUMBER for final deduplication."""
        params = GoldenRecordParams(source_columns=["name"])
        sql = build_golden_record_cte(params).render()
        assert "ROW_NUMBER() OVER" in sql
        assert "AS rn" in sql

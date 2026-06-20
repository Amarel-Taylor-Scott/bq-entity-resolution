"""Tests for the gold output SQL builder."""

from bq_entity_resolution.sql.builders.gold_output import (
    GoldOutputParams,
    build_gold_output_sql,
)
from bq_entity_resolution.sql.builders.golden_record import (
    FieldStrategy,
    GoldenRecordParams,
    build_golden_record_cte,
)


def test_gold_output_completeness():
    """Completeness canonical method counts non-null columns."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        canonical_method="completeness",
        scoring_columns=["first_name", "last_name", "email"],
        source_columns=["first_name", "last_name", "email"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "clustered" in sql
    assert "canonical_scores" in sql
    assert "canonicals" in sql
    assert "resolved" in sql
    assert "IS NOT NULL THEN 1" in sql
    assert "canonical_score" in sql
    assert "is_canonical" in sql
    assert "resolved_entity_id" in sql


def test_gold_output_recency():
    """Recency canonical method uses timestamp."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        canonical_method="recency",
        source_columns=["name"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "UNIX_MICROS(source_updated_at)" in sql


def test_gold_output_source_priority():
    """Source priority canonical method uses CASE on source_name."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        canonical_method="source_priority",
        source_columns=["name"],
        source_priority=["gold_source", "silver_source"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "CASE source_name" in sql
    assert "gold_source" in sql
    assert "silver_source" in sql


def test_gold_output_match_metadata():
    """Match metadata includes tier, score, confidence."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        include_match_metadata=True,
        source_columns=["name"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "matched_by_tier" in sql
    assert "match_score" in sql
    assert "match_confidence" in sql
    assert "ROW_NUMBER()" in sql


def test_gold_output_no_match_metadata():
    """Without match metadata, no LEFT JOIN."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        include_match_metadata=False,
        source_columns=["name"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "matched_by_tier" not in sql
    assert "LEFT JOIN" not in sql


def test_gold_output_partition_and_cluster():
    """Partitioning and clustering options."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        source_columns=["name"],
        partition_column="_pipeline_loaded_at",
        cluster_columns=["source_name", "cluster_id"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "PARTITION BY _pipeline_loaded_at" in sql
    assert "CLUSTER BY source_name, cluster_id" in sql


def test_gold_output_resolved_entity_id_is_int64():
    """resolved_entity_id is kept as INT64 (cluster_id) for efficient joins."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        entity_id_prefix="cust",
        source_columns=["name"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    # resolved_entity_id should be INT64 cluster_id, not a string-concatenated prefix
    assert "cluster_id AS resolved_entity_id" in sql
    assert "CAST(" not in sql or "CAST(cl.cluster_id AS STRING)" not in sql


def test_gold_output_passthrough_columns():
    """Passthrough columns are included in output."""
    params = GoldOutputParams(
        target_table="proj.ds.resolved",
        source_table="proj.ds.featured",
        cluster_table="proj.ds.clusters",
        matches_table="proj.ds.all_matches",
        source_columns=["name"],
        passthrough_columns=["raw_id", "external_ref"],
    )
    expr = build_gold_output_sql(params)
    sql = expr.render()

    assert "f.raw_id" in sql
    assert "f.external_ref" in sql


# ---------------------------------------------------------------------------
# Golden record CTE tests
# ---------------------------------------------------------------------------


class TestGoldenRecordCTE:
    """Tests for field-level golden record assembly."""

    def test_basic_cte_generation(self):
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["first_name", "last_name", "email"],
            scoring_columns=["first_name", "last_name", "email"],
        )).render()
        assert "clustered_scored" in cte
        assert "golden_fields" in cte
        assert "FIRST_VALUE(first_name IGNORE NULLS)" in cte
        assert "FIRST_VALUE(last_name IGNORE NULLS)" in cte
        assert "FIRST_VALUE(email IGNORE NULLS)" in cte
        assert "completeness_score" in cte

    def test_most_recent_strategy(self):
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["phone"],
            field_strategies=[
                FieldStrategy(column="phone", strategy="most_recent"),
            ],
        )).render()
        assert "FIRST_VALUE(phone IGNORE NULLS)" in cte
        assert "source_updated_at DESC" in cte

    def test_source_priority_strategy(self):
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["email"],
            field_strategies=[
                FieldStrategy(
                    column="email",
                    strategy="source_priority",
                    source_priority=["crm", "erp"],
                ),
            ],
        )).render()
        assert "FIRST_VALUE(email IGNORE NULLS)" in cte
        assert "CASE source_name" in cte
        assert "'crm'" in cte
        assert "'erp'" in cte

    def test_mixed_strategies(self):
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["first_name", "phone", "email"],
            field_strategies=[
                FieldStrategy(column="phone", strategy="most_recent"),
                FieldStrategy(
                    column="email",
                    strategy="source_priority",
                    source_priority=["crm"],
                ),
            ],
            default_strategy="most_complete",
            scoring_columns=["first_name", "phone", "email"],
        )).render()
        # first_name uses default (most_complete) = completeness_score DESC
        assert "completeness_score DESC" in cte
        # phone uses most_recent = source_updated_at DESC
        assert "source_updated_at DESC" in cte
        # email uses source_priority = CASE source_name
        assert "CASE source_name" in cte

    def test_rn_column_for_dedup(self):
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["name"],
        )).render()
        assert "ROW_NUMBER()" in cte
        assert "rn" in cte

    def test_most_common_strategy(self):
        """most_common strategy uses majority vote via GROUP BY + COUNT."""
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["city", "state"],
            field_strategies=[
                FieldStrategy(column="city", strategy="most_common"),
            ],
        )).render()
        # Should generate a vote CTE for city
        assert "vote_city AS" in cte
        assert "COUNT(*)" in cte
        assert "voted_value" in cte
        assert "vote_weight" in cte
        # Vote CTE filters nulls and picks top by vote_weight
        assert "city IS NOT NULL" in cte
        assert "GROUP BY cluster_id, city" in cte
        assert "ORDER BY vote_weight DESC" in cte
        # Main query uses COALESCE(vote.voted_value, FIRST_VALUE fallback)
        assert "COALESCE(" in cte
        assert "vote_city.voted_value" in cte
        # State should use default (most_complete) without vote CTE
        assert "vote_state" not in cte
        assert "FIRST_VALUE(state IGNORE NULLS)" in cte

    def test_weighted_vote_strategy(self):
        """weighted_vote strategy uses exponential time decay."""
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["phone"],
            field_strategies=[
                FieldStrategy(
                    column="phone",
                    strategy="weighted_vote",
                    decay_rate=0.05,
                ),
            ],
        )).render()
        # Should generate a vote CTE with exponential decay
        assert "vote_phone AS" in cte
        assert "EXP(-0.05" in cte
        assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_updated_at, DAY)" in cte
        assert "SUM(" in cte
        assert "voted_value" in cte
        # Main query uses COALESCE with vote result
        assert "COALESCE(" in cte
        assert "vote_phone.voted_value" in cte
        # LEFT JOIN for vote CTE
        assert "LEFT JOIN vote_phone" in cte

    def test_weighted_vote_default_decay_rate(self):
        """weighted_vote uses default decay_rate of 0.01 when not specified."""
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["email"],
            field_strategies=[
                FieldStrategy(column="email", strategy="weighted_vote"),
            ],
        )).render()
        assert "EXP(-0.01" in cte

    def test_mixed_vote_and_nonvote_strategies(self):
        """Mix of vote-based and non-vote strategies in same golden record."""
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["first_name", "city", "phone", "email"],
            field_strategies=[
                FieldStrategy(column="city", strategy="most_common"),
                FieldStrategy(column="phone", strategy="weighted_vote", decay_rate=0.02),
                FieldStrategy(column="email", strategy="most_recent"),
            ],
            default_strategy="most_complete",
        )).render()
        # Vote CTEs for city and phone
        assert "vote_city AS" in cte
        assert "vote_phone AS" in cte
        assert "COUNT(*)" in cte  # city uses COUNT
        assert "SUM(EXP(" in cte  # phone uses weighted SUM
        # No vote CTE for first_name or email
        assert "vote_first_name" not in cte
        assert "vote_email" not in cte
        # LEFT JOINs for vote CTEs
        assert "LEFT JOIN vote_city" in cte
        assert "LEFT JOIN vote_phone" in cte
        # first_name uses default (most_complete)
        assert "FIRST_VALUE(first_name IGNORE NULLS)" in cte
        # email uses most_recent
        assert "FIRST_VALUE(email IGNORE NULLS)" in cte

    def test_vote_cte_qualify_picks_top_value(self):
        """Vote CTEs use QUALIFY ROW_NUMBER() to pick the winning value."""
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["city"],
            field_strategies=[
                FieldStrategy(column="city", strategy="most_common"),
            ],
        )).render()
        assert "QUALIFY ROW_NUMBER() OVER" in cte
        assert "PARTITION BY cluster_id" in cte

    def test_vote_fallback_to_first_value(self):
        """Vote-based columns fall back to FIRST_VALUE if vote CTE is NULL."""
        cte = build_golden_record_cte(GoldenRecordParams(
            source_columns=["city"],
            field_strategies=[
                FieldStrategy(column="city", strategy="most_common"),
            ],
        )).render()
        # COALESCE(vote.voted_value, FIRST_VALUE(...))
        assert "COALESCE(" in cte
        assert "FIRST_VALUE(city IGNORE NULLS)" in cte


# ---------------------------------------------------------------------------
# Field merge gold output tests
# ---------------------------------------------------------------------------


class TestFieldMergeGoldOutput:
    """Tests for field_merge canonical method in gold output."""

    def test_field_merge_generates_golden_fields(self):
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            canonical_method="field_merge",
            source_columns=["first_name", "last_name", "phone"],
            scoring_columns=["first_name", "last_name", "phone"],
        )
        sql = build_gold_output_sql(params).render()

        assert "golden_fields" in sql
        assert "clustered_scored" in sql
        assert "FIRST_VALUE(first_name IGNORE NULLS)" in sql
        assert "FIRST_VALUE(last_name IGNORE NULLS)" in sql
        assert "FIRST_VALUE(phone IGNORE NULLS)" in sql
        assert "resolved_entity_id" in sql
        assert "WHERE g.rn = 1" in sql

    def test_field_merge_with_strategies(self):
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            canonical_method="field_merge",
            source_columns=["first_name", "phone"],
            scoring_columns=["first_name", "phone"],
            field_strategies=[
                FieldStrategy(column="phone", strategy="most_recent"),
            ],
            default_field_strategy="most_complete",
        )
        sql = build_gold_output_sql(params).render()

        assert "golden_fields" in sql
        assert "completeness_score DESC" in sql  # first_name default
        assert "source_updated_at DESC" in sql  # phone most_recent

    def test_field_merge_no_canonical_scores_cte(self):
        """field_merge does NOT use the canonical_scores/canonicals CTEs."""
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            canonical_method="field_merge",
            source_columns=["name"],
        )
        sql = build_gold_output_sql(params).render()

        assert "canonical_scores" not in sql
        assert "canonicals AS" not in sql

    def test_field_merge_with_most_common(self):
        """field_merge with most_common strategy generates vote CTE."""
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            canonical_method="field_merge",
            source_columns=["first_name", "city"],
            field_strategies=[
                FieldStrategy(column="city", strategy="most_common"),
            ],
        )
        sql = build_gold_output_sql(params).render()

        assert "golden_fields" in sql
        assert "vote_city AS" in sql
        assert "COUNT(*)" in sql
        assert "voted_value" in sql

    def test_field_merge_with_weighted_vote(self):
        """field_merge with weighted_vote strategy uses exponential decay."""
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            canonical_method="field_merge",
            source_columns=["phone", "email"],
            field_strategies=[
                FieldStrategy(
                    column="phone",
                    strategy="weighted_vote",
                    decay_rate=0.03,
                ),
            ],
            default_field_strategy="most_complete",
        )
        sql = build_gold_output_sql(params).render()

        assert "golden_fields" in sql
        assert "vote_phone AS" in sql
        assert "EXP(-0.03" in sql
        assert "LEFT JOIN vote_phone" in sql
        assert "resolved_entity_id" in sql
        assert "WHERE g.rn = 1" in sql


# ---------------------------------------------------------------------------
# Reconciliation strategy tests
# ---------------------------------------------------------------------------


class TestReconciliationStrategy:
    """Tests for reconciliation strategy in match metadata."""

    def test_tier_priority_default(self):
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            source_columns=["name"],
            reconciliation_strategy="tier_priority",
        )
        sql = build_gold_output_sql(params).render()
        assert "ORDER BY match_tier_priority ASC, match_total_score DESC" in sql

    def test_highest_score_strategy(self):
        params = GoldOutputParams(
            target_table="proj.ds.resolved",
            source_table="proj.ds.featured",
            cluster_table="proj.ds.clusters",
            matches_table="proj.ds.all_matches",
            source_columns=["name"],
            reconciliation_strategy="highest_score",
        )
        sql = build_gold_output_sql(params).render()
        assert "ORDER BY match_total_score DESC, match_tier_priority ASC" in sql

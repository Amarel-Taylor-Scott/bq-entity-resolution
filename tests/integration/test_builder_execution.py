"""Integration tests: builder-generated SQL executes correctly in DuckDB.

Proves that the SQL builders produce SQL that runs against real data
using the DuckDB backend, producing correct results.
"""

from bq_entity_resolution.sql.builders.active_learning import (
    ActiveLearningParams,
    build_active_learning_sql,
)
from bq_entity_resolution.sql.builders.blocking import (
    BlockingParams,
    BlockingPath,
    build_blocking_sql,
)
from bq_entity_resolution.sql.builders.comparison import (
    ComparisonDef,
    ComparisonLevel,
    FellegiSunterParams,
    SumScoringParams,
    Threshold,
    build_fellegi_sunter_sql,
    build_sum_scoring_sql,
)
from bq_entity_resolution.sql.builders.features import (
    FeatureExpr,
    FeatureParams,
    TFColumn,
    build_features_sql,
    build_term_frequencies_sql,
)
from bq_entity_resolution.sql.builders.gold_output import (
    GoldOutputParams,
    build_gold_output_sql,
)
from bq_entity_resolution.sql.builders.staging import (
    StagingParams,
    build_staging_sql,
)


def test_staging_builder_executes(backend):
    """Staging builder SQL runs in DuckDB and produces rows."""
    # First create a raw source table
    backend.execute("""
        CREATE TABLE raw_customers (
            customer_id VARCHAR,
            first_name VARCHAR,
            last_name VARCHAR,
            updated_at TIMESTAMP
        )
    """)
    backend.execute("""
        INSERT INTO raw_customers VALUES
        ('c1', 'John', 'Smith', '2024-01-01'),
        ('c2', 'Jane', 'Doe', '2024-01-02')
    """)

    params = StagingParams(
        target_table="p.d.staged_customers",
        source_name="crm",
        source_table="p.d.raw_customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=["first_name", "last_name"],
    )
    expr = build_staging_sql(params)
    backend.execute(expr.render())

    assert backend.row_count("staged_customers") == 2

    rows = backend.execute_and_fetch("SELECT * FROM staged_customers ORDER BY first_name")
    assert rows[1]["source_name"] == "crm"
    assert rows[1]["first_name"] == "John"
    assert rows[1]["entity_uid"] is not None


def test_features_builder_executes(backend):
    """Feature builder SQL runs and produces features."""
    params = FeatureParams(
        target_table="p.d.featured_test",
        source_tables=["p.d.featured"],
        source_columns=["first_name", "last_name", "dob", "email"],
        feature_expressions=[
            FeatureExpr("upper_first", "UPPER(first_name)"),
            FeatureExpr("upper_last", "UPPER(last_name)"),
        ],
        dependent_features=[
            FeatureExpr("full_name", "CONCAT(upper_first, ' ', upper_last)"),
        ],
        blocking_keys=[
            FeatureExpr("bk_last_upper", "UPPER(last_name)"),
        ],
    )
    expr = build_features_sql(params)
    backend.execute(expr.render())

    assert backend.row_count("featured_test") == 5

    rows = backend.execute_and_fetch(
        "SELECT upper_first, full_name, bk_last_upper "
        "FROM featured_test WHERE entity_uid = 'e1'"
    )
    assert rows[0]["upper_first"] == "JOHN"
    assert rows[0]["full_name"] == "JOHN SMITH"
    assert rows[0]["bk_last_upper"] == "SMITH"


def test_term_frequency_builder_executes(backend):
    """Term frequency builder produces correct frequencies."""
    expr = build_term_frequencies_sql(
        target_table="tf_stats",
        source_table="featured",
        tf_columns=[TFColumn("last_name")],
    )
    backend.execute(expr.render())

    rows = backend.execute_and_fetch(
        "SELECT * FROM tf_stats ORDER BY term_frequency_value"
    )
    # Doe (1), Johnson (1), Smith (3) => frequencies: 0.2, 0.2, 0.6
    assert len(rows) == 3
    smith_row = [r for r in rows if r["term_frequency_value"] == "Smith"][0]
    assert smith_row["term_frequency_count"] == 3
    assert abs(smith_row["term_frequency_ratio"] - 0.6) < 0.01


def test_blocking_builder_executes(backend):
    """Blocking builder produces correct candidate pairs."""
    params = BlockingParams(
        target_table="p.d.candidates_builder",
        source_table="p.d.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="test",
    )
    expr = build_blocking_sql(params)
    backend.execute(expr.render())

    count = backend.row_count("candidates_builder")
    # Same result as test_blocking_produces_candidates: 3 pairs
    assert count == 3


def test_blocking_builder_link_only(backend):
    """Blocking with link_only restricts to cross-source."""
    params = BlockingParams(
        target_table="p.d.candidates_link",
        source_table="p.d.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="test",
        link_type="link_only",
    )
    expr = build_blocking_sql(params)
    backend.execute(expr.render())

    count = backend.row_count("candidates_link")
    # Cross-source soundex matches: (e1,e4), (e2,e4) = 2
    assert count == 2


def test_sum_scoring_builder_executes(backend):
    """Sum scoring builder produces scored matches."""
    # First create candidates
    backend.execute("""
        CREATE TABLE cand_sum AS
        SELECT
            l.entity_uid AS left_entity_uid,
            r.entity_uid AS right_entity_uid
        FROM featured l
        INNER JOIN featured r
            ON l.entity_uid < r.entity_uid
            AND l.name_soundex = r.name_soundex
            AND l.name_soundex IS NOT NULL
    """)

    params = SumScoringParams(
        tier_name="sum_test",
        tier_index=0,
        matches_table="p.d.matches_sum",
        candidates_table="p.d.cand_sum",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="name_exact",
                sql_expr=(
                    "l.first_name_clean = r.first_name_clean"
                    " AND l.first_name_clean IS NOT NULL"
                ),
                weight=2.0,
            ),
            ComparisonDef(
                name="dob_exact",
                sql_expr="l.dob = r.dob AND l.dob IS NOT NULL",
                weight=1.5,
            ),
        ],
        threshold=Threshold(min_score=1.0),
        max_possible_score=3.5,
    )
    expr = build_sum_scoring_sql(params)
    backend.execute(expr.render())

    rows = backend.execute_and_fetch(
        "SELECT * FROM matches_sum ORDER BY match_total_score DESC"
    )
    assert len(rows) > 0
    # All matched pairs should have score >= 1.0
    for row in rows:
        assert row["match_total_score"] >= 1.0
        assert row["match_tier_name"] == "sum_test"
        assert row["match_confidence"] is not None


def test_fs_scoring_builder_executes(backend):
    """Fellegi-Sunter scoring builder produces scored matches."""
    # Create candidates
    backend.execute("""
        CREATE TABLE cand_fs AS
        SELECT
            l.entity_uid AS left_entity_uid,
            r.entity_uid AS right_entity_uid
        FROM featured l
        INNER JOIN featured r
            ON l.entity_uid < r.entity_uid
            AND l.name_soundex = r.name_soundex
            AND l.name_soundex IS NOT NULL
    """)

    params = FellegiSunterParams(
        tier_name="fs_test",
        tier_index=1,
        matches_table="p.d.matches_fs",
        candidates_table="p.d.cand_fs",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="name",
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.first_name_clean = r.first_name_clean "
                        "AND l.first_name_clean IS NOT NULL",
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
            ComparisonDef(
                name="dob",
                levels=[
                    ComparisonLevel(
                        label="exact",
                        sql_expr="l.dob = r.dob AND l.dob IS NOT NULL",
                        log_weight=4.0,
                    ),
                    ComparisonLevel(
                        label="else",
                        sql_expr=None,
                        log_weight=-1.0,
                    ),
                ],
            ),
        ],
        log_prior_odds=-3.0,
        threshold=Threshold(min_score=-10.0),
    )
    expr = build_fellegi_sunter_sql(params)
    backend.execute(expr.render())

    rows = backend.execute_and_fetch(
        "SELECT * FROM matches_fs ORDER BY match_total_score DESC"
    )
    assert len(rows) > 0
    for row in rows:
        assert row["match_total_score"] >= -10.0
        assert row["match_tier_name"] == "fs_test"
        assert row["match_confidence"] is not None
        assert 0.0 <= row["match_confidence"] <= 1.0


def test_active_learning_builder_executes(backend):
    """Active learning builder produces review queue."""
    # Create a matches table first
    backend.execute("""
        CREATE TABLE al_matches (
            left_entity_uid VARCHAR,
            right_entity_uid VARCHAR,
            match_total_score DOUBLE,
            match_confidence DOUBLE,
            match_tier_priority INTEGER,
            match_tier_name VARCHAR,
            matched_at TIMESTAMP
        )
    """)
    backend.execute("""
        INSERT INTO al_matches VALUES
        ('e1', 'e2', 5.0, 0.85, 0, 'tier1', CURRENT_TIMESTAMP),
        ('e1', 'e4', 8.0, 0.95, 0, 'tier1', CURRENT_TIMESTAMP),
        ('e2', 'e4', 3.0, 0.55, 0, 'tier1', CURRENT_TIMESTAMP)
    """)

    params = ActiveLearningParams(
        review_table="p.d.review_queue",
        matches_table="p.d.al_matches",
        queue_size=10,
        uncertainty_window=0.5,
        is_fellegi_sunter=True,
    )
    expr = build_active_learning_sql(params)
    backend.execute(expr.render())

    rows = backend.execute_and_fetch(
        "SELECT * FROM review_queue ORDER BY match_uncertainty ASC"
    )
    # e2-e4 pair (confidence 0.55) is closest to 0.5
    assert len(rows) > 0
    assert rows[0]["match_uncertainty"] < rows[-1]["match_uncertainty"] or len(rows) == 1


def test_end_to_end_pipeline_builders(backend):
    """End-to-end: blocking -> scoring -> output using all builders."""
    # Step 1: Blocking
    blocking = build_blocking_sql(BlockingParams(
        target_table="p.d.e2e_candidates",
        source_table="p.d.featured",
        blocking_paths=[BlockingPath(index=0, keys=["name_soundex"])],
        tier_name="e2e",
    ))
    backend.execute(blocking.render())

    # Step 2: Sum scoring
    scoring = build_sum_scoring_sql(SumScoringParams(
        tier_name="e2e",
        tier_index=0,
        matches_table="p.d.e2e_matches",
        candidates_table="p.d.e2e_candidates",
        source_table="p.d.featured",
        comparisons=[
            ComparisonDef(
                name="name",
                sql_expr=(
                    "l.first_name_clean = r.first_name_clean"
                    " AND l.first_name_clean IS NOT NULL"
                ),
                weight=2.0,
            ),
            ComparisonDef(
                name="dob",
                sql_expr="l.dob = r.dob AND l.dob IS NOT NULL",
                weight=1.5,
            ),
        ],
        threshold=Threshold(min_score=1.0),
        max_possible_score=3.5,
    ))
    backend.execute(scoring.render())

    matches = backend.row_count("e2e_matches")
    assert matches > 0

    # Step 3: Cluster assignment (simplified - no BQ scripting in DuckDB)
    # Do a simple union-find in SQL
    backend.execute("""
        CREATE TABLE e2e_clusters AS
        SELECT DISTINCT entity_uid, entity_uid AS cluster_id
        FROM featured
    """)
    # Propagate clusters from matches
    backend.execute("""
        UPDATE e2e_clusters SET cluster_id = (
            SELECT LEAST(cl.cluster_id, cr.cluster_id)
            FROM e2e_matches m
            JOIN e2e_clusters cl ON m.left_entity_uid = cl.entity_uid
            JOIN e2e_clusters cr ON m.right_entity_uid = cr.entity_uid
            WHERE e2e_clusters.entity_uid = m.left_entity_uid
               OR e2e_clusters.entity_uid = m.right_entity_uid
            LIMIT 1
        )
        WHERE entity_uid IN (
            SELECT left_entity_uid FROM e2e_matches
            UNION
            SELECT right_entity_uid FROM e2e_matches
        )
    """)

    # Step 4: Gold output
    gold = build_gold_output_sql(GoldOutputParams(
        target_table="p.d.e2e_resolved",
        source_table="p.d.featured",
        cluster_table="p.d.e2e_clusters",
        matches_table="p.d.e2e_matches",
        canonical_method="completeness",
        scoring_columns=["first_name", "last_name", "email"],
        source_columns=["first_name", "last_name", "dob", "email"],
        include_match_metadata=True,
        entity_id_prefix="test",
    ))
    backend.execute(gold.render())

    resolved_count = backend.row_count("e2e_resolved")
    # All 5 entities should appear
    assert resolved_count == 5

    rows = backend.execute_and_fetch(
        "SELECT resolved_entity_id, cluster_id, is_canonical, first_name "
        "FROM e2e_resolved ORDER BY entity_uid"
    )
    # resolved_entity_id is now the raw cluster_id (INT64 in production),
    # not a string-prefixed version like "test_123"
    assert all(r["resolved_entity_id"] == r["cluster_id"] for r in rows)

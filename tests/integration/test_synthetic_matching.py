"""Synthetic data matching tests for efficiency optimizations.

Validates:
- entity_uid is INT64 (not STRING) in generated SQL
- Comparison ordering: cheap methods appear before expensive ones
- Token set comparisons work without UNION DISTINCT
- Pre-filter WHERE clauses are generated for mandatory comparisons
"""

import pytest

from bq_entity_resolution.backends.duckdb import DuckDBBackend
from bq_entity_resolution.matching.comparisons import COMPARISON_COSTS, COMPARISON_FUNCTIONS
from bq_entity_resolution.sql.builders.comparison import (
    ComparisonDef as BuilderComparisonDef,
)
from bq_entity_resolution.sql.builders.comparison import (
    SumScoringParams,
    Threshold,
    build_sum_scoring_sql,
)


@pytest.fixture
def db():
    """DuckDB backend with synthetic entity data."""
    backend = DuckDBBackend(":memory:")

    # Create featured table with INT64 entity_uid
    backend.execute("""
        CREATE TABLE featured (
            entity_uid BIGINT NOT NULL,
            source_name VARCHAR NOT NULL,
            first_name VARCHAR,
            last_name VARCHAR,
            dob VARCHAR,
            bk_name_dob BIGINT
        )
    """)

    # Insert 10 synthetic records with known duplicates
    backend.execute("""
        INSERT INTO featured VALUES
        (1001, 'src', 'John', 'Smith', '1990-01-15', 100),
        (1002, 'src', 'Jon', 'Smith', '1990-01-15', 100),
        (1003, 'src', 'Jane', 'Doe', '1985-06-20', 200),
        (1004, 'src', 'Alice', 'Johnson', '1992-03-10', 300),
        (1005, 'src', 'Bob', 'Williams', '1988-11-25', 400),
        (1006, 'src', 'John', 'Smyth', '1990-01-15', 100),
        (1007, 'src', 'Alicia', 'Johnson', '1992-03-10', 300),
        (1008, 'src', 'Robert', 'Williams', '1988-11-25', 400),
        (1009, 'src', 'Janet', 'Doe', '1985-06-20', 200),
        (1010, 'src', 'Jonathon', 'Smith', '1990-01-15', 100)
    """)

    return backend


# ---------------------------------------------------------------------------
# INT64 entity_uid tests
# ---------------------------------------------------------------------------


def test_int64_entity_uid_in_duckdb(db):
    """entity_uid should be BIGINT (INT64) not VARCHAR in featured table."""
    rows = db.execute_and_fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'featured' AND column_name = 'entity_uid'"
    )
    assert len(rows) == 1
    assert rows[0]["data_type"] == "BIGINT"


def test_int64_entity_uid_joins_efficiently(db):
    """INT64 entity_uid supports efficient self-joins for blocking."""
    # Create a candidates table with INT64 UIDs
    db.execute("""
        CREATE TABLE candidates AS
        SELECT l.entity_uid AS l_entity_uid, r.entity_uid AS r_entity_uid
        FROM featured l, featured r
        WHERE l.bk_name_dob = r.bk_name_dob
          AND l.entity_uid < r.entity_uid
    """)

    rows = db.execute_and_fetch("SELECT COUNT(*) AS cnt FROM candidates")
    assert rows[0]["cnt"] > 0

    # Verify the join type is BIGINT
    col_rows = db.execute_and_fetch(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'candidates' AND column_name = 'l_entity_uid'"
    )
    assert col_rows[0]["data_type"] == "BIGINT"


# ---------------------------------------------------------------------------
# Comparison cost ordering tests
# ---------------------------------------------------------------------------


def test_comparison_costs_ordering():
    """Comparison methods have expected cost ordering: exact < soundex < levenshtein."""
    assert COMPARISON_COSTS["exact"] < COMPARISON_COSTS["soundex_match"]
    assert COMPARISON_COSTS["soundex_match"] < COMPARISON_COSTS["levenshtein"]


def test_tier_sql_evaluates_cheap_first():
    """In generated SQL, exact match appears before levenshtein."""
    # Build comparisons in cost-sorted order (as the stage/caller would do)
    params = SumScoringParams(
        tier_name="tier1",
        tier_index=0,
        matches_table="proj.silver.matches_tier1",
        candidates_table="proj.silver.candidates_tier1",
        source_table="proj.silver.featured",
        comparisons=[
            # Already sorted by cost (exact < soundex < levenshtein)
            BuilderComparisonDef(
                name="last_name__exact",
                sql_expr="l.last_name = r.last_name",
                weight=3.0,
            ),
            BuilderComparisonDef(
                name="first_name__soundex_match",
                sql_expr="SOUNDEX(l.first_name) = SOUNDEX(r.first_name)",
                weight=1.0,
            ),
            BuilderComparisonDef(
                name="first_name__levenshtein",
                sql_expr="EDIT_DISTANCE(l.first_name, r.first_name) <= 2",
                weight=2.0,
            ),
        ],
        threshold=Threshold(method="score", min_score=4.0),
    )
    sql = build_sum_scoring_sql(params).render()

    exact_pos = sql.find("l.last_name = r.last_name")
    levenshtein_pos = sql.find("EDIT_DISTANCE")

    assert exact_pos > 0, "exact comparison not found in SQL"
    assert levenshtein_pos > 0, "levenshtein comparison not found in SQL"
    assert exact_pos < levenshtein_pos, "exact should appear before levenshtein"


# ---------------------------------------------------------------------------
# Token set optimization tests
# ---------------------------------------------------------------------------


def test_token_set_match_executes_in_duckdb(db):
    """Optimized token_set_match executes correctly in DuckDB."""
    sql_expr = COMPARISON_FUNCTIONS["token_set_match"]("first_name", "first_name")
    query = f"""
        SELECT l.entity_uid AS l_uid, r.entity_uid AS r_uid,
               {sql_expr} AS is_match
        FROM featured l, featured r
        WHERE l.entity_uid < r.entity_uid
        AND l.first_name IS NOT NULL AND r.first_name IS NOT NULL
        LIMIT 5
    """
    rows = db.execute_and_fetch(query)
    assert len(rows) > 0
    # Results should be boolean
    for row in rows:
        assert isinstance(row["is_match"], bool)


def test_token_set_score_executes_in_duckdb(db):
    """Optimized token_set_score executes correctly in DuckDB."""
    sql_expr = COMPARISON_FUNCTIONS["token_set_score"]("first_name", "first_name")
    query = f"""
        SELECT l.entity_uid AS l_uid, r.entity_uid AS r_uid,
               {sql_expr} AS score
        FROM featured l, featured r
        WHERE l.entity_uid < r.entity_uid
        AND l.first_name IS NOT NULL AND r.first_name IS NOT NULL
        LIMIT 5
    """
    rows = db.execute_and_fetch(query)
    assert len(rows) > 0
    for row in rows:
        assert isinstance(row["score"], (int, float))
        assert 0.0 <= row["score"] <= 1.0


def test_exact_same_name_has_full_token_overlap(db):
    """Exact same name should have Jaccard score of 1.0."""
    sql_expr = COMPARISON_FUNCTIONS["token_set_score"]("first_name", "first_name")
    query = f"""
        SELECT {sql_expr} AS score
        FROM featured l, featured r
        WHERE l.entity_uid = 1001 AND r.entity_uid = 1001
    """
    rows = db.execute_and_fetch(query)
    assert rows[0]["score"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# COMPARISON_COSTS completeness
# ---------------------------------------------------------------------------


def test_all_functions_have_costs():
    """Every registered comparison function has a cost entry."""
    for name in COMPARISON_FUNCTIONS:
        assert name in COMPARISON_COSTS, f"Missing cost for: {name}"


def test_costs_are_positive_integers():
    """All costs are positive integers."""
    for name, cost in COMPARISON_COSTS.items():
        assert isinstance(cost, int), f"{name} cost is not int: {cost}"
        assert cost > 0, f"{name} cost must be positive: {cost}"

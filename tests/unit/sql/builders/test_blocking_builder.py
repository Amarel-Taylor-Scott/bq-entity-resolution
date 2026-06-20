"""Tests for the blocking SQL builder."""

from bq_entity_resolution.sql.builders.blocking import (
    BlockingParams,
    BlockingPath,
    build_blocking_sql,
)


def test_basic_blocking_single_path():
    """Single blocking path generates correct CTE structure."""
    params = BlockingParams(
        target_table="proj.ds.candidates_t1",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="exact_name",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "intra_path_0" in sql
    assert "l.entity_uid < r.entity_uid" in sql
    assert "l.name_soundex = r.name_soundex" in sql
    assert "l.name_soundex IS NOT NULL" in sql
    assert "all_candidates" in sql
    assert "deduplicated" in sql


def test_blocking_multiple_paths():
    """Multiple blocking paths generate separate CTEs and UNION ALL."""
    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
            BlockingPath(index=1, keys=["dob_year", "zip3"]),
        ],
        tier_name="fuzzy",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "intra_path_0" in sql
    assert "intra_path_1" in sql
    assert "UNION ALL" in sql


def test_blocking_cross_batch():
    """Cross-batch blocking generates cross_path CTEs."""
    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        canonical_table="proj.ds.canonical",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="cross",
        cross_batch=True,
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "cross_path_0" in sql
    assert "l.entity_uid != r.entity_uid" in sql


def test_blocking_link_only():
    """link_only restricts to cross-source pairs."""
    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="link",
        link_type="link_only",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "l.source_name != r.source_name" in sql


def test_blocking_dedupe_only():
    """dedupe_only restricts to same-source pairs."""
    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="dedupe",
        link_type="dedupe_only",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "l.source_name = r.source_name" in sql


def test_blocking_candidate_limit():
    """Per-path candidate limit adds QUALIFY clause."""
    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"], candidate_limit=100),
        ],
        tier_name="limited",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "QUALIFY ROW_NUMBER()" in sql
    assert "<= 100" in sql


def test_blocking_excluded_pairs():
    """Prior-tier exclusion generates LEFT JOIN anti-pattern."""
    params = BlockingParams(
        target_table="proj.ds.candidates_t2",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["name_soundex"]),
        ],
        tier_name="t2",
        excluded_pairs_table="proj.ds.matches_t1",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "LEFT JOIN" in sql
    assert "proj.ds.matches_t1" in sql
    assert "e.left_entity_uid IS NULL" in sql


def test_blocking_with_lsh():
    """LSH keys generate pre-join CTEs."""
    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=[], lsh_keys=["lsh_bucket_0"]),
        ],
        tier_name="lsh",
        lsh_table="proj.ds.lsh_buckets",
    )
    expr = build_blocking_sql(params)
    sql = expr.render()

    assert "source_with_lsh" in sql
    assert "lsh_bucket_0" in sql
    assert "proj.ds.lsh_buckets" in sql


def test_blocking_returns_sql_expression():
    """Builder returns SQLExpression."""
    params = BlockingParams(
        target_table="p.d.target",
        source_table="p.d.source",
        blocking_paths=[BlockingPath(index=0, keys=["k"])],
        tier_name="test",
    )
    expr = build_blocking_sql(params)
    assert expr.is_raw is True

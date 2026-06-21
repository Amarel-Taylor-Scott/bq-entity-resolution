"""Multi-level sum scoring executes on DuckDB with graduated partial credit."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.comparison.models import (
    ComparisonDef,
    ComparisonLevel,
    SumScoringParams,
    Threshold,
)
from bq_entity_resolution.sql.builders.comparison.sum_scoring import (
    build_sum_scoring_sql,
)


def test_graduated_levels_score_on_duckdb():
    from bq_entity_resolution.backends.duckdb import DuckDBBackend

    db = DuckDBBackend(":memory:")
    db.execute("CREATE TABLE feat (entity_uid BIGINT, name VARCHAR, email VARCHAR)")
    for uid, name, email in [
        (1, "Acme", "a@x"),
        (2, "ACME", "b@x"),   # case-insensitive name match vs 1; different email
        (3, "Beta", "a@x"),   # name mismatch vs 1; exact email
    ]:
        db.connection.execute("INSERT INTO feat VALUES (?,?,?)", [uid, name, email])
    db.execute(
        "CREATE TABLE cand (left_entity_uid BIGINT, right_entity_uid BIGINT)"
    )
    db.connection.execute("INSERT INTO cand VALUES (1,2),(1,3)")

    name_cmp = ComparisonDef(
        name="name", sql_expr="", weight=3.0,
        levels=[
            ComparisonLevel("exact", "l.name = r.name", score=3.0),
            ComparisonLevel("ci", "LOWER(l.name) = LOWER(r.name)", score=1.5),
        ],
    )
    email_cmp = ComparisonDef(name="email", sql_expr="l.email = r.email", weight=5.0)

    params = SumScoringParams(
        tier_name="t", tier_index=0,
        matches_table="p.d.matches", candidates_table="p.d.cand",
        source_table="p.d.feat", comparisons=[name_cmp, email_cmp],
        threshold=Threshold(min_score=0.0), max_possible_score=8.0,
    )
    db.execute(build_sum_scoring_sql(params).render())

    rows = db.execute_and_fetch(
        "SELECT left_entity_uid, right_entity_uid, match_total_score "
        "FROM matches ORDER BY left_entity_uid, right_entity_uid"
    )
    scores = {
        (int(r["left_entity_uid"]), int(r["right_entity_uid"])):
        round(float(r["match_total_score"]), 3) for r in rows
    }
    # (1,2): name case-insensitive level (1.5) + no email match (0) = 1.5
    assert scores[(1, 2)] == 1.5
    # (1,3): name mismatch (0) + exact email (5.0) = 5.0
    assert scores[(1, 3)] == 5.0


def test_threshold_filters_low_level_credit_on_duckdb():
    from bq_entity_resolution.backends.duckdb import DuckDBBackend

    db = DuckDBBackend(":memory:")
    db.execute("CREATE TABLE feat (entity_uid BIGINT, name VARCHAR)")
    for uid, name in [(1, "Acme"), (2, "ACME")]:
        db.connection.execute("INSERT INTO feat VALUES (?,?)", [uid, name])
    db.execute("CREATE TABLE cand (left_entity_uid BIGINT, right_entity_uid BIGINT)")
    db.connection.execute("INSERT INTO cand VALUES (1,2)")

    name_cmp = ComparisonDef(
        name="name", sql_expr="", weight=3.0,
        levels=[
            ComparisonLevel("exact", "l.name = r.name", score=3.0),
            ComparisonLevel("ci", "LOWER(l.name) = LOWER(r.name)", score=1.5),
        ],
    )
    params = SumScoringParams(
        tier_name="t", tier_index=0,
        matches_table="p.d.matches", candidates_table="p.d.cand",
        source_table="p.d.feat", comparisons=[name_cmp],
        threshold=Threshold(min_score=2.0), max_possible_score=3.0,
    )
    db.execute(build_sum_scoring_sql(params).render())
    n = db.execute_and_fetch("SELECT COUNT(*) AS c FROM matches")[0]["c"]
    # Only the ci level (1.5) matched → below the 2.0 threshold → filtered out.
    assert int(n) == 0

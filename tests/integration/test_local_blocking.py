"""Integration test: blocking produces candidate pairs using DuckDB.

This is the proof-of-concept that SQL generated for entity resolution
can execute locally. The blocking SQL creates candidate pairs from
the featured table using equi-join on blocking keys.
"""


def test_blocking_produces_candidates(backend):
    """Simple blocking on name_soundex produces candidate pairs."""
    # This is a simplified version of what multi_path_candidates.sql.j2 generates
    blocking_sql = """
    CREATE TABLE candidates_tier1 AS
    SELECT
        l.entity_uid AS l_entity_uid,
        r.entity_uid AS r_entity_uid
    FROM featured l
    INNER JOIN featured r
        ON l.entity_uid < r.entity_uid
        AND l.name_soundex = r.name_soundex
        AND l.name_soundex IS NOT NULL
    """
    backend.execute(blocking_sql)
    count = backend.row_count("candidates_tier1")
    # e1 (John Smith, S530), e2 (Jon Smith, S530), e4 (John Smith, S530)
    # Should produce pairs: (e1,e2), (e1,e4), (e2,e4)
    assert count == 3


def test_blocking_with_link_only(backend):
    """link_only mode restricts to cross-source pairs."""
    blocking_sql = """
    CREATE TABLE candidates_link_only AS
    SELECT
        l.entity_uid AS l_entity_uid,
        r.entity_uid AS r_entity_uid
    FROM featured l
    INNER JOIN featured r
        ON l.entity_uid < r.entity_uid
        AND l.name_soundex = r.name_soundex
        AND l.name_soundex IS NOT NULL
        AND l.source_name != r.source_name
    """
    backend.execute(blocking_sql)
    count = backend.row_count("candidates_link_only")
    # Cross-source pairs with same soundex: (e1,e4), (e2,e4)
    assert count == 2


def test_blocking_empty_key_produces_zero(backend):
    """Blocking on non-existent key column pattern produces zero candidates."""
    # This validates that the quality gate would catch this
    blocking_sql = """
    CREATE TABLE candidates_empty AS
    SELECT
        l.entity_uid AS l_entity_uid,
        r.entity_uid AS r_entity_uid
    FROM featured l
    INNER JOIN featured r
        ON l.entity_uid < r.entity_uid
        AND l.email = r.email
        AND l.email IS NOT NULL
    """
    backend.execute(blocking_sql)
    count = backend.row_count("candidates_empty")
    # No two records have the same email
    assert count == 0


def test_candidate_deduplication(backend):
    """Multiple blocking paths produce deduplicated candidates."""
    blocking_sql = """
    CREATE TABLE candidates_dedup AS
    WITH path1 AS (
        SELECT l.entity_uid AS l_entity_uid, r.entity_uid AS r_entity_uid
        FROM featured l
        INNER JOIN featured r
            ON l.entity_uid < r.entity_uid
            AND l.name_soundex = r.name_soundex
            AND l.name_soundex IS NOT NULL
    ),
    path2 AS (
        SELECT l.entity_uid AS l_entity_uid, r.entity_uid AS r_entity_uid
        FROM featured l
        INNER JOIN featured r
            ON l.entity_uid < r.entity_uid
            AND l.bk_name_dob = r.bk_name_dob
            AND l.bk_name_dob IS NOT NULL
    ),
    all_candidates AS (
        SELECT * FROM path1
        UNION ALL
        SELECT * FROM path2
    )
    SELECT DISTINCT l_entity_uid, r_entity_uid
    FROM all_candidates
    """
    backend.execute(blocking_sql)
    count = backend.row_count("candidates_dedup")
    # path1: (e1,e2), (e1,e4), (e2,e4) [soundex match]
    # path2: (e1,e4) [exact name+dob match]
    # Dedup: 3 unique pairs
    assert count == 3

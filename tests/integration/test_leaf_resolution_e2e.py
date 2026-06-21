"""End-to-end integration test: leaf-based resolution on the DuckDB backend.

Reuses the standalone prototype's sample world (``examples/leaf_prototype.py``)
and proves the *packaged* leaf SQL builder reproduces the same clustering:

    new×new merges 201↔202 (same email, fresh dupes)
    new×old attaches 203 → canonical 101, 204 → canonical 102 (exact-key)
    old×old merges canonical 103 → 101 (re-resolution / repair)

    => 8 records collapse to 4 entities.

Clustering is leaf-blind: every leaf's tagged pairs union into one pair graph
that a simple union-find resolves (the package's clustering builder consumes the
same all_matches pair graph in production).
"""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.leaf import (
    LeafBlockingPath,
    LeafScoreTerm,
    LeafSQLParams,
    build_leaf_sql,
)

# ── sample world (mirrors examples/leaf_prototype.py) ───────────────────────
CANONICAL = [
    # entity_uid, name, email, phone, cluster_id, updated_at
    (101, "Robert Lee", "rlee@acme.com", "555-0101", "C1", 1),
    (102, "Maria Gomez", "mgomez@x.io", "555-0202", "C2", 1),
    (103, "Bob Lee", "", "555-0101", "C3", 5),  # merges w/ 101 (old×old)
]
NEW_BATCH = [
    (201, "Jon Smith", "jsmith@mail.com", "555-0303"),
    (202, "John Smith", "jsmith@mail.com", "555-9999"),  # dup of 201 (new×new email)
    (203, "Roberto Lee", "rlee@acme.com", "555-0101"),  # → canonical 101 (new×old)
    (204, "Mariah Gomez", "mgomez@x.io", "555-0202"),  # → canonical 102 (new×old)
    (205, "Wei Chen", "wchen@nova.dev", "555-0404"),  # genuinely new
]


@pytest.fixture
def leaf_backend():
    """DuckDB backend seeded with the leaf sample world.

    Both partitions carry the columns the leaf SQL references: entity_uid plus
    the comparison/blocking columns (email, phone, name, email_domain).
    """
    from bq_entity_resolution.backends.duckdb import DuckDBBackend

    db = DuckDBBackend(":memory:")
    db.execute(
        """
        CREATE TABLE new_batch (
            entity_uid BIGINT, name VARCHAR, email VARCHAR, phone VARCHAR,
            email_domain VARCHAR, name3 VARCHAR
        )
        """
    )
    for uid, name, email, phone in NEW_BATCH:
        domain = email.split("@")[-1]
        db.connection.execute(
            "INSERT INTO new_batch VALUES (?,?,?,?,?,?)",
            [uid, name, email, phone, domain, name[:3].lower()],
        )

    db.execute(
        """
        CREATE TABLE canonical (
            entity_uid BIGINT, name VARCHAR, email VARCHAR, phone VARCHAR,
            email_domain VARCHAR, name3 VARCHAR, cluster_id VARCHAR, updated_at BIGINT
        )
        """
    )
    for uid, name, email, phone, cid, upd in CANONICAL:
        domain = email.split("@")[-1] if email else ""
        db.connection.execute(
            "INSERT INTO canonical VALUES (?,?,?,?,?,?,?,?)",
            [uid, name, email, phone, domain, name[:3].lower(), cid, upd],
        )
    return db


def _new_x_new_params() -> LeafSQLParams:
    return LeafSQLParams(
        target_table="p.d.leaf_pairs_new_x_new",
        leaf_name="new_x_new",
        left_table="p.d.new_batch",
        right_table="p.d.new_batch",
        blocking_paths=[
            LeafBlockingPath(keys=["email_domain"]),
            LeafBlockingPath(keys=["name3"]),
        ],
        score_terms=[
            LeafScoreTerm(
                "email_exact",
                "l.email <> '' AND l.email = r.email",
                1.0,
            ),
            LeafScoreTerm(
                "name_jw",
                "jaro_winkler_similarity(l.name, r.name)",
                1.0,
            ),
        ],
        threshold=0.90,
        is_self_join=True,
        symmetric=True,
    )


def _new_x_old_params() -> LeafSQLParams:
    return LeafSQLParams(
        target_table="p.d.leaf_pairs_new_x_old",
        leaf_name="new_x_old",
        left_table="p.d.new_batch",
        right_table="p.d.canonical",
        blocking_paths=[
            LeafBlockingPath(keys=["email_domain"]),
            LeafBlockingPath(keys=["name3"]),
        ],
        score_terms=[
            LeafScoreTerm("email_exact", "l.email <> '' AND l.email = r.email", 1.0),
            LeafScoreTerm("phone_exact", "l.phone <> '' AND l.phone = r.phone", 1.0),
            LeafScoreTerm("name_jw", "jaro_winkler_similarity(l.name, r.name)", 1.0),
        ],
        threshold=0.95,
        is_self_join=False,
        exact_key_short_circuit=["email", "phone"],
    )


def _old_x_old_params() -> LeafSQLParams:
    return LeafSQLParams(
        target_table="p.d.leaf_pairs_old_x_old",
        leaf_name="old_x_old",
        left_table="p.d.canonical",
        right_table="p.d.canonical",
        blocking_paths=[
            LeafBlockingPath(keys=["phone"]),
            LeafBlockingPath(keys=["name3"]),
        ],
        score_terms=[
            LeafScoreTerm("phone_exact", "l.phone <> '' AND l.phone = r.phone", 1.0),
            LeafScoreTerm("name_jw", "jaro_winkler_similarity(l.name, r.name)", 1.0),
        ],
        threshold=0.95,
        is_self_join=True,
        symmetric=True,
    )


def _run_leaf(backend, params: LeafSQLParams) -> list[tuple[int, int]]:
    """Execute one leaf's builder SQL and return its (left, right) pairs."""
    backend.execute(build_leaf_sql(params).render())
    rows = backend.execute_and_fetch(
        f"SELECT left_entity_uid, right_entity_uid "
        f"FROM {params.target_table.split('.')[-1]}"
    )
    return [(int(r["left_entity_uid"]), int(r["right_entity_uid"])) for r in rows]


def _union_find(pairs: list[tuple[int, int]], all_uids: list[int]) -> dict[int, list[int]]:
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for a, b in pairs:
        union(a, b)
    clusters: dict[int, list[int]] = {}
    for uid in all_uids:
        clusters.setdefault(find(uid), []).append(uid)
    return clusters


class TestLeafResolutionEndToEnd:
    def test_new_x_new_merges_201_202(self, leaf_backend):
        pairs = _run_leaf(leaf_backend, _new_x_new_params())
        normalized = {tuple(sorted(p)) for p in pairs}
        assert (201, 202) in normalized

    def test_new_x_old_attaches_203_and_204(self, leaf_backend):
        pairs = _run_leaf(leaf_backend, _new_x_old_params())
        normalized = {tuple(sorted(p)) for p in pairs}
        # 203 → canonical 101 (exact email rlee@acme.com + phone 555-0101)
        assert (101, 203) in normalized
        # 204 → canonical 102 (exact email mgomez@x.io + phone 555-0202)
        assert (102, 204) in normalized

    def test_old_x_old_merges_canonicals(self, leaf_backend):
        pairs = _run_leaf(leaf_backend, _old_x_old_params())
        normalized = {tuple(sorted(p)) for p in pairs}
        # canonical 103 (Bob Lee, phone 555-0101) merges with 101 (Robert Lee)
        assert (101, 103) in normalized

    def test_eight_records_resolve_to_four_entities(self, leaf_backend):
        """The headline assertion: union of all leaves => 4 entities."""
        all_pairs: list[tuple[int, int]] = []
        all_pairs += _run_leaf(leaf_backend, _new_x_new_params())
        all_pairs += _run_leaf(leaf_backend, _new_x_old_params())
        all_pairs += _run_leaf(leaf_backend, _old_x_old_params())

        all_uids = [r[0] for r in CANONICAL] + [r[0] for r in NEW_BATCH]
        clusters = _union_find(all_pairs, all_uids)

        assert len(all_uids) == 8
        assert len(clusters) == 4, (
            f"expected 4 entities, got {len(clusters)}: "
            f"{sorted(sorted(m) for m in clusters.values())}"
        )

        # The expected groupings:
        members = sorted(sorted(m) for m in clusters.values())
        # Lee cluster: 101 (Robert) + 103 (Bob, old×old) + 203 (Roberto, new×old)
        assert [101, 103, 203] in members
        # Gomez cluster: 102 (Maria) + 204 (Mariah, new×old)
        assert [102, 204] in members
        # Smith cluster: 201 + 202 (new×new dupes)
        assert [201, 202] in members
        # Wei Chen: genuinely new singleton
        assert [205] in members

    def test_short_circuit_marks_auto_accepts(self, leaf_backend):
        """new×old exact-key short-circuit emits 'short_circuit' rows."""
        leaf_backend.execute(build_leaf_sql(_new_x_old_params()).render())
        rows = leaf_backend.execute_and_fetch(
            "SELECT match_method FROM leaf_pairs_new_x_old"
        )
        methods = {r["match_method"] for r in rows}
        assert "short_circuit" in methods

    def test_max_pairs_caps_output(self, leaf_backend):
        params = LeafSQLParams(
            target_table="p.d.leaf_pairs_capped",
            leaf_name="capped",
            left_table="p.d.new_batch",
            right_table="p.d.new_batch",
            blocking_paths=[LeafBlockingPath(keys=["email_domain"])],
            score_terms=[LeafScoreTerm("any", "1=1", 1.0)],
            threshold=0.5,
            is_self_join=True,
            max_pairs=1,
        )
        leaf_backend.execute(build_leaf_sql(params).render())
        assert leaf_backend.row_count("leaf_pairs_capped") == 1

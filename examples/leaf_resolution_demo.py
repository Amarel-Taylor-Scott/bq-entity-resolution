#!/usr/bin/env python3
"""Runnable end-to-end demo of LEAF-BASED resolution (DuckDB, no BigQuery).

Unlike ``examples/leaf_prototype.py`` (a standalone proof), this demo drives the
*packaged* leaf SQL builder (``bq_entity_resolution.sql.builders.leaf``) against
the DuckDB backend — the exact code path the pipeline uses, only the backend is
swapped. It shows three preset leaves resolving the sample world:

    new×new — intra-batch dedup            (201 ↔ 202, same email)
    new×old — attach to canonical store    (203 → 101, 204 → 102; exact-key)
    old×old — re-resolution / merge repair (103 → 101)

    => 8 records collapse to 4 entities.

Run it::

    python examples/leaf_resolution_demo.py
"""

from __future__ import annotations

from bq_entity_resolution.backends.duckdb import DuckDBBackend
from bq_entity_resolution.sql.builders.leaf import (
    LeafBlockingPath,
    LeafSQLParams,
    LeafScoreTerm,
    build_leaf_sql,
)

# ── sample world (same as examples/leaf_prototype.py) ───────────────────────
CANONICAL = [  # resolved "old" store: uid, name, email, phone, cluster_id, updated_at
    (101, "Robert Lee", "rlee@acme.com", "555-0101", "C1", 1),
    (102, "Maria Gomez", "mgomez@x.io", "555-0202", "C2", 1),
    (103, "Bob Lee", "", "555-0101", "C3", 5),  # merges w/ 101 (old×old)
]
NEW_BATCH = [  # incoming records this run: uid, name, email, phone
    (201, "Jon Smith", "jsmith@mail.com", "555-0303"),
    (202, "John Smith", "jsmith@mail.com", "555-9999"),  # dup of 201 (new×new)
    (203, "Roberto Lee", "rlee@acme.com", "555-0101"),  # → canonical 101 (new×old)
    (204, "Mariah Gomez", "mgomez@x.io", "555-0202"),  # → canonical 102 (new×old)
    (205, "Wei Chen", "wchen@nova.dev", "555-0404"),  # genuinely new
]


def _seed(backend: DuckDBBackend) -> None:
    backend.execute(
        "CREATE TABLE new_batch (entity_uid BIGINT, name VARCHAR, email VARCHAR, "
        "phone VARCHAR, email_domain VARCHAR, name3 VARCHAR)"
    )
    for uid, name, email, phone in NEW_BATCH:
        backend.connection.execute(
            "INSERT INTO new_batch VALUES (?,?,?,?,?,?)",
            [uid, name, email, phone, email.split("@")[-1], name[:3].lower()],
        )
    backend.execute(
        "CREATE TABLE canonical (entity_uid BIGINT, name VARCHAR, email VARCHAR, "
        "phone VARCHAR, email_domain VARCHAR, name3 VARCHAR, cluster_id VARCHAR, "
        "updated_at BIGINT)"
    )
    for uid, name, email, phone, cid, upd in CANONICAL:
        backend.connection.execute(
            "INSERT INTO canonical VALUES (?,?,?,?,?,?,?,?)",
            [uid, name, email, phone, email.split("@")[-1] if email else "",
             name[:3].lower(), cid, upd],
        )


# ── leaf presets (built with the packaged builder) ──────────────────────────
LEAVES = [
    LeafSQLParams(
        target_table="p.d.leaf_pairs_new_x_new",
        leaf_name="new_x_new",
        left_table="p.d.new_batch", right_table="p.d.new_batch",
        blocking_paths=[LeafBlockingPath(keys=["email_domain"]),
                        LeafBlockingPath(keys=["name3"])],
        score_terms=[
            LeafScoreTerm("email_exact", "l.email <> '' AND l.email = r.email", 1.0),
            LeafScoreTerm("name_jw", "jaro_winkler_similarity(l.name, r.name)", 1.0),
        ],
        threshold=0.90, is_self_join=True,
    ),
    LeafSQLParams(
        target_table="p.d.leaf_pairs_new_x_old",
        leaf_name="new_x_old",
        left_table="p.d.new_batch", right_table="p.d.canonical",
        blocking_paths=[LeafBlockingPath(keys=["email_domain"]),
                        LeafBlockingPath(keys=["name3"])],
        score_terms=[
            LeafScoreTerm("email_exact", "l.email <> '' AND l.email = r.email", 1.0),
            LeafScoreTerm("phone_exact", "l.phone <> '' AND l.phone = r.phone", 1.0),
            LeafScoreTerm("name_jw", "jaro_winkler_similarity(l.name, r.name)", 1.0),
        ],
        threshold=0.95, is_self_join=False,
        exact_key_short_circuit=["email", "phone"],
    ),
    LeafSQLParams(
        target_table="p.d.leaf_pairs_old_x_old",
        leaf_name="old_x_old",
        left_table="p.d.canonical", right_table="p.d.canonical",
        blocking_paths=[LeafBlockingPath(keys=["phone"]),
                        LeafBlockingPath(keys=["name3"])],
        score_terms=[
            LeafScoreTerm("phone_exact", "l.phone <> '' AND l.phone = r.phone", 1.0),
            LeafScoreTerm("name_jw", "jaro_winkler_similarity(l.name, r.name)", 1.0),
        ],
        threshold=0.95, is_self_join=True,
    ),
]


def run() -> None:
    backend = DuckDBBackend(":memory:")
    _seed(backend)

    all_pairs: list[tuple[int, int]] = []
    for params in LEAVES:
        backend.execute(build_leaf_sql(params).render())
        local = params.target_table.split(".")[-1]
        rows = backend.execute_and_fetch(
            f"SELECT left_entity_uid, right_entity_uid, match_total_score, match_method "
            f"FROM {local} ORDER BY left_entity_uid, right_entity_uid"
        )
        print(f"\n── leaf {params.leaf_name}  "
              f"[{params.left_table.split('.')[-1]} × {params.right_table.split('.')[-1]}] "
              f"— {len(rows)} pairs")
        for r in rows:
            a, b = int(r["left_entity_uid"]), int(r["right_entity_uid"])
            print(f"     {a} ↔ {b}   score={round(r['match_total_score'], 3):<5} "
                  f"({r['match_method']})")
            all_pairs.append((a, b))

    # union-find over the unified pair graph (clustering is leaf-blind)
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in all_pairs:
        parent[find(a)] = find(b)

    name = {r[0]: r[1] for r in CANONICAL} | {r[0]: r[1] for r in NEW_BATCH}
    cid_seed = {r[0]: r[4] for r in CANONICAL}
    all_uids = [r[0] for r in CANONICAL] + [r[0] for r in NEW_BATCH]
    clusters: dict[int, list[int]] = {}
    for uid in all_uids:
        clusters.setdefault(find(uid), []).append(uid)

    print(f"\n══ resolved clusters ({len(clusters)} entities from {len(all_uids)} records) ══")
    for members in sorted(clusters.values(), key=lambda m: -len(m)):
        old = [u for u in members if u in cid_seed]
        tag = f"(was {','.join(cid_seed[u] for u in old)})" if old else "(new entity)"
        print(f"   {tag:18} " + " + ".join(f"{u}:{name[u]}" for u in sorted(members)))

    assert len(clusters) == 4, f"expected 4 entities, got {len(clusters)}"
    print("\nOK: 8 records resolved to 4 entities.")


if __name__ == "__main__":
    run()

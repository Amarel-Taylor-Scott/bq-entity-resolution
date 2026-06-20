#!/usr/bin/env python3
"""Standalone prototype of LEAF-BASED resolution (DuckDB, no BigQuery needed).

Proves the generic N×M leaf model from docs/leaf-resolution-design.md:
each leaf compares an ordered pair of partitions with its OWN blocking, scoring,
threshold and heuristics, emits tagged candidate pairs, and all leaves union into
one pair graph that clusters incrementally.

    python examples/leaf_prototype.py

Presets shown: new×new (intra-batch dedup), new×old (attach to canonical store,
with exact-key short-circuit), old×old (re-resolution / merge repair), plus a
generic source×source leaf. Pure SQL generation — the same shape the package's
sql/builders/leaf.py will emit for BigQuery.
"""
from __future__ import annotations

import duckdb
from dataclasses import dataclass, field

# ── sample world ───────────────────────────────────────────────────────────
CANONICAL = [  # the resolved "old" store: entity_uid, name, email, phone, cluster_id, updated_at
    (101, "Robert Lee",   "rlee@acme.com",   "555-0101", "C1", 1),
    (102, "Maria Gomez",  "mgomez@x.io",     "555-0202", "C2", 1),
    (103, "Bob Lee",      "",                "555-0101", "C3", 5),   # should merge w/ 101 (old×old)
]
NEW_BATCH = [  # incoming records this run
    (201, "Jon Smith",    "jsmith@mail.com", "555-0303"),
    (202, "John Smith",   "jsmith@mail.com", "555-9999"),   # dup of 201 (new×new, same email)
    (203, "Roberto Lee",  "rlee@acme.com",   "555-0101"),   # matches canonical 101 (new×old, exact email+phone)
    (204, "Mariah Gomez", "mgomez@x.io",     "555-0202"),   # matches canonical 102 (new×old)
    (205, "Wei Chen",     "wchen@nova.dev",  "555-0404"),   # genuinely new
]


def setup(con):
    con.execute("CREATE TABLE canonical(entity_uid INT, name TEXT, email TEXT, phone TEXT, cluster_id TEXT, updated_at INT)")
    con.executemany("INSERT INTO canonical VALUES (?,?,?,?,?,?)", CANONICAL)
    con.execute("CREATE TABLE new_batch(entity_uid INT, name TEXT, email TEXT, phone TEXT)")
    con.executemany("INSERT INTO new_batch VALUES (?,?,?,?)", NEW_BATCH)


# ── leaf model (mirrors LeafDef/LeafHeuristics in the design) ───────────────
PARTITIONS = {
    # name -> (SQL source, predicate)
    "new":       ("new_batch", "TRUE"),
    "canonical": ("canonical", "TRUE"),
    "old_touched": ("canonical", "updated_at >= 5"),   # old×old touched_only demo
}

# blocking paths: candidate pair if it matches ANY path; each path = list of key exprs
BLOCKING_PATHS = [
    ["lower(substr({a}.name,1,3))"],          # name prefix
    ["split_part({a}.email,'@',2)"],          # email domain
    ["right({a}.phone,4)"],                   # phone last4
]
# comparison score: exact email / exact phone / fuzzy name
SCORE = ("greatest("
         "case when l.email<>'' and l.email=r.email then 1.0 else 0 end,"
         "case when l.phone<>'' and l.phone=r.phone then 1.0 else 0 end,"
         "jaro_winkler_similarity(l.name,r.name))")


@dataclass
class Leaf:
    name: str
    left: str
    right: str
    threshold: float = 0.90
    short_circuit: list[str] = field(default_factory=list)  # exact-key auto-accept (new×old)
    symmetric: bool = True


def leaf_sql(leaf: Leaf) -> str:
    lt, lp = PARTITIONS[leaf.left]
    rt, rp = PARTITIONS[leaf.right]
    blocks = " OR ".join(
        "(" + " AND ".join(f"{p.format(a='l')} = {p.format(a='r').replace('l.','r.')}"
                           for p in path) + ")"
        for path in BLOCKING_PATHS)
    # self-join dedup guard when comparing a partition to itself
    guard = "l.entity_uid < r.entity_uid" if leaf.left == leaf.right and leaf.symmetric else "l.entity_uid <> r.entity_uid"
    base = f"""
        SELECT l.entity_uid AS left_uid, r.entity_uid AS right_uid,
               {SCORE} AS score, '{leaf.name}' AS leaf, 'compare' AS method
        FROM (SELECT * FROM {lt} WHERE {lp}) l
        JOIN (SELECT * FROM {rt} WHERE {rp}) r
          ON ({blocks}) AND {guard}
        WHERE {SCORE} >= {leaf.threshold}"""
    # heuristic: exact-key short-circuit (cheap high-recall auto-accepts)
    if leaf.short_circuit:
        sc = " OR ".join(f"(l.{k}<>'' AND l.{k}=r.{k})" for k in leaf.short_circuit)
        base += f"""
        UNION
        SELECT l.entity_uid, r.entity_uid, 1.0, '{leaf.name}', 'short_circuit'
        FROM (SELECT * FROM {lt} WHERE {lp}) l
        JOIN (SELECT * FROM {rt} WHERE {rp}) r ON ({sc}) AND {guard}"""
    return base


def run():
    con = duckdb.connect()
    setup(con)
    leaves = [
        Leaf("new_x_new", "new", "new"),
        Leaf("new_x_old", "new", "canonical", short_circuit=["email", "phone"]),
        Leaf("old_x_old", "old_touched", "canonical", threshold=0.95),  # repair: touched vs all
    ]
    all_pairs = []
    for lf in leaves:
        rows = con.execute(leaf_sql(lf)).fetchall()
        # dedup symmetric pairs from the union
        seen, pairs = set(), []
        for a, b, s, name, m in rows:
            k = (min(a, b), max(a, b))
            if k in seen:
                continue
            seen.add(k); pairs.append((a, b, round(s, 3), m))
        all_pairs += [(a, b) for a, b, _, _ in pairs]
        print(f"\n── leaf {lf.name}  [{lf.left} × {lf.right}] — {len(pairs)} pairs")
        for a, b, s, m in sorted(pairs):
            print(f"     {a} ↔ {b}   score={s:<5} ({m})")

    # union-find clustering over the unified pair graph (clustering is leaf-blind)
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        parent[find(a)] = find(b)
    # seed with existing canonical clusters so new records attach to them
    cid_seed = {r[0]: r[4] for r in CANONICAL}
    for a, b in all_pairs:
        union(a, b)
    clusters = {}
    for uid in [r[0] for r in CANONICAL] + [r[0] for r in NEW_BATCH]:
        clusters.setdefault(find(uid), []).append(uid)

    name = {r[0]: r[1] for r in CANONICAL} | {r[0]: r[1] for r in NEW_BATCH}
    print(f"\n══ resolved clusters ({len(clusters)} entities from {len(name)} records) ══")
    for members in sorted(clusters.values(), key=lambda m: -len(m)):
        old = [u for u in members if u in cid_seed]
        tag = f"(was {','.join(cid_seed[u] for u in old)})" if old else "(new entity)"
        print(f"   {tag:18} " + " + ".join(f"{u}:{name[u]}" for u in sorted(members)))


if __name__ == "__main__":
    run()

# Leaf-Based Resolution — Design

> Status: **proposed** · Audience: maintainers · Supersedes the implicit
> intra-batch / cross-batch split in `sql/builders/blocking.py`.

## 1. Motivation

Today the pipeline does **one undifferentiated resolution pass**. The blocking
builder already distinguishes two strata internally
(`sql/builders/blocking.py`):

- **intra-batch** — new records × new records
- **cross-batch** — new records × gold canonicals

…but they are *blocking paths*, not first-class units. Consequences:

1. **No per-stratum tuning.** new×new (fresh dupes, often typos in the same
   load) and new×old (a fresh record vs a mature canonical with aggregated
   features) want *different* blocking keys, comparison levels, and thresholds —
   today they share one matching config.
2. **No `old×old`.** Existing canonicals are never re-compared, so two entities
   that *should* merge (discovered only after later data arrives, or a config
   change) stay split forever. There is no re-resolution / merge-repair path.
3. **Not generic.** "new" and "old" are hard-coded notions. Real deployments
   want arbitrary partitions: `source_A × source_B`, `region_us × region_eu`,
   `high_trust × low_trust`, time-window × time-window.

**Leaf-based resolution** makes each comparison stratum a first-class,
independently-configured **leaf**. `new×new`, `new×old`, `old×old` become
*presets* of a generic **N×M leaf** (`partition_left × partition_right`).

This is also a genuine differentiator: Splink / dedupe / recordlinkage all run a
single comparison space. Per-leaf blocking + matching + heuristics, with an
explicit incremental `old×old` repair leaf, is novel and warehouse-native.

## 2. Core abstraction

A **leaf** is a self-contained candidate-pair generator over an ordered pair of
**partitions** of the entity space:

```
leaf := (left_partition, right_partition, blocking, matching, heuristics, enabled, schedule)
```

- A **partition** is a named, SQL-expressible subset of the unified record/entity
  space: e.g. `new` (this batch, via the watermark cursor), `old` (the canonical
  index / gold), or any predicate (`source = 'crm'`, `ingested_at < @cutoff`).
- A leaf emits `(left_uid, right_uid, score, leaf_name, tier)` candidate pairs.
- `left == right` partition ⇒ **self-join** (dedup), emit unordered pairs once
  (`l.uid < r.uid`). `left != right` ⇒ **cross-join** between partitions.

### Presets (sugar over the generic model)

| Preset | left | right | Purpose | Default heuristics |
|---|---|---|---|---|
| `new_x_new` | `new` | `new` | intra-batch dedup | tightest thresholds; full blocking |
| `new_x_old` | `new` | `canonical` | attach new records to resolved entities | exact-canonical-key short-circuit; reuse canonical blocking keys; entity-level (aggregated) comparison features |
| `old_x_old` | `canonical` | `canonical` | periodic re-resolution / merge repair | schedule-gated; conservative thresholds; only re-examine clusters touched since last run or flagged |

`new` resolves to the watermark batch; `canonical` to the canonical index
(`reconciliation` / canonical builders). Both are existing concepts — leaves
just name and compose them.

## 3. Configuration

New model `config/models/leaves.py` (Pydantic v2, same conventions as
`matching.py` / `blocking.py`):

```python
class PartitionDef(BaseModel):
    name: str                         # "new" | "old"/"canonical" | custom
    source: Literal["batch", "canonical", "table"] = "batch"
    table: str | None = None          # for source="table"
    predicate: str | None = None      # validated SQL boolean expr (no DDL/DML)

class LeafDef(BaseModel):
    name: str
    left: str                         # PartitionDef name
    right: str                        # PartitionDef name (== left ⇒ self/dedup)
    blocking: TierBlockingConfig | None = None   # falls back to global blocking
    matching: list[MatchingTierConfig] | None = None  # falls back to global tiers
    heuristics: LeafHeuristics = LeafHeuristics()
    enabled: bool = True
    schedule: Literal["every_run", "manual", "cron"] = "every_run"
    cron: str | None = None           # for schedule="cron" (old×old repair)

class LeafHeuristics(BaseModel):
    exact_key_short_circuit: list[str] = []   # canonical keys that auto-accept (e.g. ["email_norm"])
    threshold_override: float | None = None
    symmetric: bool = True            # self-join emits each unordered pair once
    touched_only: bool = False        # old×old: only clusters changed since last run
    max_pairs: int | None = None      # safety cap per leaf
```

Pipeline config gains `partitions: list[PartitionDef]` and `leaves: list[LeafDef]`.
**Back-compat:** when `leaves` is omitted, the loader synthesizes the current
behaviour as two implicit leaves (`new_x_new`, `new_x_old`) from the existing
blocking paths — zero change for existing configs (existing 3,833 tests stay
green).

### YAML example

```yaml
partitions:
  - {name: new, source: batch}
  - {name: old, source: canonical}
leaves:
  - name: new_x_new
    left: new
    right: new
    matching: [ {tier: exact}, {tier: fuzzy} ]
  - name: new_x_old
    left: new
    right: old
    heuristics: {exact_key_short_circuit: [email_norm, phone_e164]}
  - name: old_x_old
    left: old
    right: old
    schedule: cron
    cron: "0 3 * * 0"          # weekly repair
    heuristics: {touched_only: true, threshold_override: 0.97}
    enabled: true
```

## 4. SQL shape (per leaf)

A parametrized `sql/builders/leaf.py` builds, for each enabled+scheduled leaf:

```
WITH L AS (SELECT … FROM <left_partition_table>  WHERE <left.predicate>),
     R AS (SELECT … FROM <right_partition_table> WHERE <right.predicate>)
SELECT l.entity_uid AS left_uid, r.entity_uid AS right_uid,
       <comparison score>, '<leaf.name>' AS leaf, <tier> AS tier
FROM L JOIN R
  ON <blocking join from leaf.blocking>              -- reuses blocking.py join gen
  AND (l.entity_uid < r.entity_uid OR <left != right>)   -- self-join dedup guard
WHERE <comparison passes leaf threshold>
```

- **Partition table selection** is the only new dispatch: `batch` → watermark
  staging table; `canonical` → canonical index; `table` → literal (validated via
  `validate_table_ref`). UID column stays `entity_uid` (INT64 FARM_FINGERPRINT)
  so all joins remain INT64-native (per the blocking builder's perf notes).
- **Blocking** reuses the existing multi-path / LSH join generation, parametrized
  by the leaf's `TierBlockingConfig`.
- **Comparison** reuses `matching/comparisons/*`; `new×old` may bind to
  *entity-level* (aggregated canonical) columns where the new side binds to raw.
- **Heuristics** compile to SQL: `exact_key_short_circuit` → a UNION-ALL branch
  that emits score=1.0 pairs on exact canonical-key equality (cheap, high-recall);
  `touched_only` → restrict R to canonicals with `updated_at > last_repair_at`.

All candidate pairs from all leaves **UNION ALL** into the existing
`all_matches` table, tagged by `leaf`, and flow unchanged into
`reconciliation/clustering.py` + incremental clustering. Clustering is leaf-blind
(it consumes a pair graph) — so connected-components / canonical-index logic is
untouched.

## 5. Executor flow

`pipeline/executor.py` gains a **leaf stage** before clustering:

1. Resolve partitions → physical tables (batch via watermark, canonical via index).
2. Select runnable leaves (`enabled` ∧ schedule due; `old×old` only when its cron
   fires or `--repair`).
3. For each leaf: build SQL → execute → write tagged pairs.
4. `UNION ALL` pairs → `all_matches` → existing clustering/reconciliation.

Leaves are independent ⇒ **parallelizable** and individually previewable
(`bq-er preview-sql --leaf new_x_old`). Per-leaf metrics (candidate pairs,
reduction ratio, precision) extend the existing blocking metrics.

## 6. Heuristics catalogue (per leaf)

- **new×new**: full blocking, tightest thresholds (same-load typos); symmetric.
- **new×old**: (a) exact-canonical-key short-circuit (email/phone/national-id)
  emits auto-accepts before fuzzy scoring; (b) blocking keys read from the
  canonical index's precomputed `bk_`/`fp_` columns (no recompute); (c) compare
  new-raw against canonical-*aggregated* features (most-frequent value, value set
  membership).
- **old×old**: schedule-gated; `touched_only` to bound cost; conservative
  threshold (avoid over-merging mature entities); emits *merge proposals* that
  clustering applies via the incremental canonical-index UPDATE path.

## 7. Migration & compatibility

- Configs without `leaves:` behave exactly as today (synthesized presets).
- The intra-batch / cross-batch flags in `blocking.py` become the implementation
  detail behind the `new_x_new` / `new_x_old` presets.
- `old×old` is **opt-in** (default `enabled: true, schedule: cron` but only runs
  when scheduled / `--repair`), so it never changes default cost.

## 8. Test plan

- Unit: `PartitionDef`/`LeafDef`/`LeafHeuristics` validation (predicate SQL-safety
  reuses the `_SQL_INJECTION_PATTERN`); preset synthesis; self-join dedup guard.
- SQL golden tests: emitted SQL per leaf (new×new, new×old, old×old, custom NxM)
  on the DuckDB backend, asserting candidate-pair sets on fixtures.
- Heuristic tests: short-circuit auto-accepts; `touched_only` scoping.
- Back-compat: existing configs produce byte-identical `all_matches` to pre-leaf.
- Property: union of leaves' pairs == single-pass pairs when leaves partition the
  space disjointly with identical blocking/matching (no double counting).

## 9. Phasing

1. **Prototype (DuckDB, standalone)** — prove new×new / new×old / old×old / NxM end
   to end on sample data. *(this PR's companion)*
2. **Config models** — `leaves.py` + loader synthesis + validation + tests.
3. **Leaf SQL builder** — `sql/builders/leaf.py` reusing blocking + comparisons.
4. **Executor stage** — run leaves → union → clustering; CLI `--repair`,
   `preview-sql --leaf`.
5. **Heuristics** — short-circuit, touched-only, entity-level features.
6. **Docs + examples** — a `leaves` example config; README headline.

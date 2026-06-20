# Incremental Processing

This document describes the incremental processing system in bq-entity-resolution: how the pipeline processes source data in batches, tracks progress via watermarks, maintains a persistent canonical index across batches, and supports drain mode for backlog processing.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Cursor Strategy Guide](#2-cursor-strategy-guide)
3. [Processing Modes](#3-processing-modes)
4. [Configuration Reference](#4-configuration-reference)
5. [Operational Runbook](#5-operational-runbook)
6. [Cursor Profiler Tool](#6-cursor-profiler-tool)
7. [Capacity Planning](#7-capacity-planning)
8. [Example: Insurance Use Case](#8-example-insurance-use-case)

---

## 1. Architecture Overview

### Data Flow

The incremental pipeline processes source data in bounded batches. Each batch flows through the full pipeline -- staging through gold output -- and then the watermark advances to mark what was processed.

```
                             Incremental Pipeline Flow
 +------------------+
 | Source Table      |    28M+ records/day, partitioned by date
 | (raw data)       |
 +--------+---------+
          |
          v
 +--------+---------+
 | Watermark Read    |    Read cursor position from er_meta.pipeline_watermarks
 | (er_meta)        |    Returns {updated_at: "2024-01-15T...", policy_id: 999}
 +--------+---------+
          |
          v
 +--------+---------+
 | Staging (batch)   |    WHERE (updated_at, policy_id) > (wm_ts, wm_id)
 | (bronze)         |    ORDER BY updated_at, policy_id, entity_uid
 +--------+---------+    LIMIT 5,000,000
          |
          v
 +--------+---------+
 | Feature           |    Derive 45+ features: name_clean, soundex, fingerprints
 | Engineering       |    Two-pass CTE: independent -> dependent features
 | (silver)         |
 +--------+---------+
          |
          v
 +--------+-------------------+
 | Blocking                    |
 |  Intra-batch:              |    new records vs new records (l.uid < r.uid)
 |    featured x featured     |
 |  Cross-batch:              |    new records vs ALL historical records
 |    featured x canonical    |    (l.uid != r.uid)
 |         _index             |
 +--------+-------------------+
          |
          v
 +--------+---------+
 | Matching           |    Score candidate pairs: comparisons + hard negatives
 | (per tier)        |    + soft signals -> threshold -> matches
 +--------+---------+
          |
          v
 +--------+---------+
 | Clustering         |    Incremental connected components:
 | (incremental)     |    1. Init from canonical_index (prior cluster_ids)
 +--------+---------+    2. Add new entities as singletons
          |              3. Propagate MIN(cluster_id) through match edges
          v
 +--------+---------+
 | Gold Output        |    Elect canonical record per cluster
 | (gold)            |    JOIN clusters + featured -> resolved_entities
 +--------+---------+
          |
          v
 +--------+---------+
 | Canonical Index    |    UPDATE existing entities with new cluster_ids
 | Populate          |    INSERT new entities from current batch
 +--------+---------+    This table accumulates ALL entities across batches
          |
          v
 +--------+---------+
 | Watermark Advance  |    Atomically advance cursor to MAX values from
 | (er_meta)         |    the staged batch (not the raw source)
 +------------------+
```

### Key Tables

| Table | Layer | Purpose | Persistence |
|-------|-------|---------|-------------|
| `staged_{source}` | Bronze | Current batch raw data with entity_uid | Replaced each batch |
| `featured` | Silver | Current batch with engineered features | Replaced each batch |
| `candidates_{tier}` | Silver | Candidate pairs for current batch | Replaced each batch |
| `matches_{tier}` | Silver | Matched pairs for current tier | Replaced each batch |
| `all_matched_pairs` | Silver | Accumulated matches across tiers | Replaced each batch |
| `entity_clusters` | Silver | Cluster assignments (all entities) | Replaced each batch |
| `resolved_entities` | Gold | Final output with canonical records | Replaced each batch |
| `canonical_index` | Gold | **Persistent** -- all entities + cluster_ids | Accumulates across batches |
| `pipeline_watermarks` | Meta | Cursor positions per source | Accumulates (is_current flag) |
| `pipeline_checkpoints` | Meta | Stage completion for crash recovery | Accumulates per run |

### The Canonical Index

The `canonical_index` table is the backbone of incremental processing. It persists all entities ever processed by the pipeline, along with their current `cluster_id` assignments.

**Schema:** Mirrors the `featured` table plus a `cluster_id` column.

**Lifecycle:**

1. **First run (full refresh):** Created via `CREATE TABLE IF NOT EXISTS ... AS SELECT *, entity_uid AS cluster_id FROM featured WHERE FALSE` -- an empty table with the correct schema.
2. **Each batch:** After clustering completes, `CanonicalIndexPopulateStage` runs:
   - **UPDATE** existing entities whose `cluster_id` changed (because new match edges connected previously separate clusters)
   - **INSERT** new entities from the current batch with their assigned `cluster_id`
3. **Reads:** `ClusteringStage` reads the canonical_index to initialize cluster assignments for incremental clustering. `BlockingStage` reads it for cross-batch candidate generation.

**Source code:**
- `src/bq_entity_resolution/sql/builders/clustering.py` -- `build_canonical_index_init_sql()`, `build_populate_canonical_index_sql()`, `build_incremental_cluster_sql()`
- `src/bq_entity_resolution/stages/reconciliation.py` -- `CanonicalIndexInitStage`, `CanonicalIndexPopulateStage`, `ClusteringStage`

### Cross-Batch Blocking

When `cross_batch: true` (the default) is set on a tier's blocking config, the `BlockingStage` generates candidate pairs in two passes:

1. **Intra-batch:** `featured` x `featured` (standard `l.entity_uid < r.entity_uid` to avoid duplicates)
2. **Cross-batch:** `featured` x `canonical_index` (new batch records vs all historical records, using `l.entity_uid != r.entity_uid`)

This ensures that a new record arriving in batch N can match against any record from batches 1 through N-1. Without cross-batch blocking, records from different batches would never be compared and could form duplicate clusters.

**Generated SQL pattern:**

```sql
WITH
-- Intra-batch: new vs new
intra_path_0 AS (
  SELECT l.entity_uid AS l_entity_uid, r.entity_uid AS r_entity_uid
  FROM `er_silver.featured` l
  INNER JOIN `er_silver.featured` r
    ON l.entity_uid < r.entity_uid
    AND l.bk_name_zip = r.bk_name_zip
    AND l.bk_name_zip IS NOT NULL
),

-- Cross-batch: new vs historical
cross_path_0 AS (
  SELECT l.entity_uid AS l_entity_uid, r.entity_uid AS r_entity_uid
  FROM `er_silver.featured` l
  INNER JOIN `er_gold.canonical_index` r
    ON l.entity_uid != r.entity_uid
    AND l.bk_name_zip = r.bk_name_zip
    AND l.bk_name_zip IS NOT NULL
),
...
```

**Source code:** `src/bq_entity_resolution/sql/builders/blocking.py` -- `BlockingParams.cross_batch`, `_build_path_cte()`

### DAG Wiring

The pipeline DAG (`src/bq_entity_resolution/pipeline/dag.py`) wires incremental-specific stages:

```
staging -> features -> [canonical_index_init] -> blocking_tier1 -> matching_tier1 ->
  accumulation_tier1 -> blocking_tier2 -> ... -> clustering -> gold_output ->
  canonical_index_populate
```

When `incremental.enabled = true`:
- `CanonicalIndexInitStage` is added before clustering (creates the table on first run)
- `ClusteringStage` uses `build_incremental_cluster_sql()` instead of `build_cluster_assignment_sql()`
- `CanonicalIndexPopulateStage` is added after clustering (upserts into canonical_index)
- Explicit DAG edge: `canonical_index_populate` depends on `clustering`

---

## 2. Cursor Strategy Guide

A cursor defines the "bookmark" into your source table -- the position up to which data has been processed. The choice of cursor strategy depends on the data distribution in your source.

### Single Timestamp Cursor

The simplest strategy. Uses a single column (typically a timestamp) to determine which records are new.

**How it works:**

```sql
WHERE updated_at > TIMESTAMP('2024-01-15T23:59:59Z')
ORDER BY updated_at, entity_uid
LIMIT 5000000
```

**When to use:** When each distinct value of the cursor column has fewer records than your batch size. For example, if `updated_at` has daily granularity and you receive 500K records per day with a batch size of 5M, single cursor works perfectly.

**Configuration:**

```yaml
incremental:
  enabled: true
  cursor_columns: [updated_at]
  batch_size: 5_000_000
```

### Composite Ordered Cursor (Recommended for High-Volume)

When a single cursor column has too many records per value (e.g., 28M records share the same date), a composite cursor adds a secondary column to create clean batch boundaries.

**How it works:**

For cursor columns `[updated_at, policy_id]`, the staging SQL generates a tuple comparison:

```sql
WHERE (
  updated_at > TIMESTAMP('2024-01-15T00:00:00Z')
  OR (updated_at = TIMESTAMP('2024-01-15T00:00:00Z') AND policy_id > 750)
)
ORDER BY updated_at, policy_id, entity_uid
LIMIT 5000000
```

This is equivalent to the SQL tuple comparison `(updated_at, policy_id) > (wm_ts, wm_id)` and ensures:
- No records are skipped (the OR clause catches records at the watermark boundary)
- No records are re-processed (the AND clause on the equality branch excludes already-processed values)
- Deterministic ordering (ORDER BY on all cursor columns + entity_uid as tiebreaker)

**Grace period** is applied only to the first (timestamp) column:

```sql
WHERE (
  updated_at > TIMESTAMP_SUB(TIMESTAMP('2024-01-15T00:00:00Z'), INTERVAL 48 HOUR)
  OR (updated_at = TIMESTAMP('2024-01-15T00:00:00Z') AND policy_id > 750)
)
```

**Configuration:**

```yaml
incremental:
  enabled: true
  cursor_columns: [updated_at, policy_id]
  cursor_mode: ordered     # "ordered" generates tuple comparison
  batch_size: 5_000_000
  grace_period_hours: 48
```

**Source code:** `src/bq_entity_resolution/sql/builders/staging.py` -- `_build_ordered_watermark()`

### Hash Cursor Fallback

When no natural secondary column exists (no integer ID, no sequence number), a hash cursor generates a virtual partition column from the unique key.

**How it works:**

During staging, a virtual column is computed:

```sql
SELECT
  ...,
  MOD(FARM_FINGERPRINT(CAST(record_id AS STRING)), 1000) AS _hash_partition,
  ...
FROM source_table
WHERE (
  updated_at > wm_ts
  OR (updated_at = wm_ts AND _hash_partition > wm_hash)
)
ORDER BY updated_at, _hash_partition, entity_uid
LIMIT 5000000
```

This creates a numeric dimension (0-999) that, combined with the primary timestamp, enables clean batch boundaries. The hash is deterministic (same input always produces the same bucket), so records never shift between buckets across runs.

**Trade-offs:**
- Adds a `FARM_FINGERPRINT` computation per row (marginal cost for BigQuery)
- Distribution depends on source data -- generally uniform for high-cardinality keys
- Prefer natural columns when they exist (zero compute cost)

**Configuration:**

```yaml
incremental:
  enabled: true
  cursor_columns: [updated_at]
  cursor_mode: ordered
  hash_cursor:
    column: record_id      # Column to hash
    modulus: 1000           # Number of buckets (0-999)
    alias: _hash_partition  # Virtual column name
```

### Decision Tree

Use this flowchart to choose the right cursor strategy:

```
How many records share the same primary cursor value (e.g., same date)?

  Less than batch_size (e.g., <5M per date)?
    |
    +---> Use SINGLE CURSOR: cursor_columns: [updated_at]
          Simple, efficient, no secondary column needed.

  More than batch_size (e.g., 28M per date)?
    |
    +---> Do you have a natural secondary column?
          (integer ID, policy number, sequence, etc.)
          |
          +---> YES: Use ORDERED CURSOR
          |         cursor_columns: [updated_at, policy_id]
          |         cursor_mode: ordered
          |         Zero compute cost, clean batch boundaries.
          |
          +---> NO:  Use HASH CURSOR
                     cursor_columns: [updated_at]
                     hash_cursor:
                       column: unique_key
                       modulus: 1000
                     Adds FARM_FINGERPRINT cost but always available.
```

---

## 3. Processing Modes

### Single Batch Mode (Default)

The pipeline processes one batch and stops. This is the default behavior.

**Flow:**

1. Read watermark from `pipeline_watermarks` table
2. Stage one batch of `batch_size` records (WHERE cursor > watermark, LIMIT batch_size)
3. Run full pipeline: features -> blocking -> matching -> clustering -> gold output
4. Populate canonical_index with new/updated entities
5. Advance watermark to MAX cursor values from the staged batch
6. Stop

**When to use:** Scheduled execution (e.g., Cloud Scheduler triggers the pipeline every hour). Each invocation processes one batch.

**CLI:**

```bash
bq-er run --config config.yml
```

**Python:**

```python
from bq_entity_resolution.pipeline.pipeline import Pipeline

pipeline = Pipeline(config)
result = pipeline.run(backend=bq_backend, watermark_manager=wm_manager)
# Processes one batch, advances watermark, returns
```

### Drain Mode

The pipeline auto-loops through batches until all unprocessed records are consumed.

**Flow:**

```
iteration = 0
while True:
    1. Read current watermark
    2. Plan and execute one batch
    3. Advance watermark to MAX values from staged batch
    4. Check: are there more records beyond the new watermark?
       - No  -> stop (all caught up)
       - Yes -> iteration += 1
    5. Check: iteration >= drain_max_iterations?
       - Yes -> stop (safety limit reached)
       - No  -> continue loop
```

**When to use:**
- Initial backlog processing after deploying the pipeline
- Catch-up after an outage or maintenance window
- Processing a burst of data that exceeds one batch

**CLI:**

```bash
# Drain all pending records
bq-er run --config config.yml --drain

# Drain with explicit iteration limit
bq-er run --config config.yml --drain --drain-max-iterations 50
```

**Python:**

```python
result = pipeline.run(
    backend=bq_backend,
    watermark_manager=wm_manager,
    drain=True,
)
# Loops until no more unprocessed records or max_iterations reached
```

**Safety:**
- `drain_max_iterations` (default: 100) prevents infinite loops
- Each iteration is a complete pipeline run (staging through gold output)
- Watermark advances only after successful execution
- If any iteration fails, the loop stops and the watermark remains at the last successful position

**Source code:** `src/bq_entity_resolution/pipeline/pipeline.py` -- `Pipeline.run()` drain loop

---

## 4. Configuration Reference

### Full Annotated Configuration

```yaml
incremental:
  # Master switch for incremental processing.
  # When false, the pipeline processes all records on every run.
  enabled: true

  # Cursor columns define the watermark dimensions.
  # Single column: simple timestamp-based incremental.
  # Multiple columns: composite watermark for high-volume sources.
  # The first column should be the primary time dimension.
  cursor_columns: [updated_at, policy_id]

  # How multiple cursor columns are compared against the watermark.
  #
  # "ordered" (recommended):
  #   Tuple comparison: (col1, col2) > (wm1, wm2)
  #   Expands to: col1 > wm1 OR (col1 = wm1 AND col2 > wm2)
  #   Guarantees no skips, no re-processing.
  #
  # "independent" (legacy):
  #   OR comparison: col1 > wm1 OR col2 > wm2
  #   Simpler but can re-process or skip when dimensions aren't aligned.
  cursor_mode: ordered

  # Number of records to process per batch.
  # This becomes the LIMIT clause in staging SQL.
  # Records are ordered by cursor columns + entity_uid before limiting.
  batch_size: 5_000_000

  # Re-process records within this window before the watermark.
  # Catches late-arriving data that was inserted after the watermark advanced.
  # Applied only to the first (timestamp) cursor column.
  # Set to 0 to disable.
  grace_period_hours: 48

  # When true, auto-detect schema changes in source tables and trigger
  # a full refresh (reprocess all records, rebuild canonical_index).
  full_refresh_on_schema_change: true

  # Drain mode: auto-loop through batches until caught up.
  # Can also be activated via --drain CLI flag.
  drain_mode: false

  # Safety limit: maximum number of drain iterations before stopping.
  drain_max_iterations: 100

  # Hash cursor: virtual partition column for tables without a natural
  # secondary cursor. Only needed when cursor_columns has one entry
  # and that column has more records per value than batch_size.
  hash_cursor:
    column: record_id       # Column to hash (usually the unique_key)
    modulus: 1000           # Number of buckets (0 to modulus-1)
    alias: _hash_partition  # Name of the virtual column in staging SQL

  # Partition cursors: additional AND predicates for BigQuery partition pruning.
  # These do NOT affect watermark tracking -- they optimize scan cost.
  # Use when source tables are partitioned by columns beyond the timestamp.
  partition_cursors:
    - column: state
      strategy: range       # >= last processed value
    - column: policy_year
      strategy: equality    # = specific value
      value: 2024
```

### Blocking Cross-Batch Configuration

Cross-batch blocking is configured per matching tier:

```yaml
matching_tiers:
  - name: "fuzzy_name"
    blocking:
      # paths define equi-join keys for candidate generation
      paths:
        - keys: [bk_name_zip]
          candidate_limit: 200
        - keys: [bk_name_city]
          candidate_limit: 150

      # cross_batch: when true (default), also generate candidates by
      # joining featured (new batch) against canonical_index (all historical).
      # When false, only intra-batch (new vs new) candidates are generated.
      cross_batch: true
```

### Scale Configuration for Incremental Tables

```yaml
scale:
  # Staging tables
  staging_partition_by: "DATE(source_updated_at)"
  staging_clustering: [entity_uid, source_name]

  # Candidate pair tables
  candidates_clustering: [l_entity_uid]

  # Match result tables
  matches_partition_by: "DATE(matched_at)"
  matches_clustering: [l_entity_uid, r_entity_uid]

  # Canonical index (critical for cross-batch performance)
  canonical_index_partition_by: null    # Usually not partitioned
  canonical_index_clustering: [entity_uid]  # CLUSTER BY for fast JOINs

  # Checkpoint/resume
  checkpoint_enabled: false   # Enable for crash recovery
```

### Watermark Table Schema

The watermark table (`er_meta.pipeline_watermarks`) stores cursor positions:

```sql
CREATE TABLE IF NOT EXISTS `project.er_meta.pipeline_watermarks` (
  source_name    STRING NOT NULL,     -- e.g., "policy_holders"
  cursor_column  STRING NOT NULL,     -- e.g., "updated_at"
  cursor_value   STRING NOT NULL,     -- e.g., "2024-01-15T23:59:59+00:00"
  cursor_type    STRING NOT NULL,     -- e.g., "TIMESTAMP", "INT64", "STRING"
  updated_at     TIMESTAMP NOT NULL,  -- When this watermark was written
  run_id         STRING,              -- Pipeline run that wrote this
  is_current     BOOL NOT NULL DEFAULT TRUE  -- Only current rows are read
)
PARTITION BY DATE(updated_at)
CLUSTER BY source_name
```

**Key design points:**
- `is_current` flag enables reading only the latest watermark without a MAX query
- Atomic updates: `BEGIN TRANSACTION; UPDATE SET is_current=FALSE; INSERT new; COMMIT;`
- Full audit trail: old watermarks remain with `is_current=FALSE`
- Composite cursors: one row per cursor column (e.g., 2 rows for `[updated_at, policy_id]`)

---

## 5. Operational Runbook

### First Run (Full Refresh)

On the first execution, there is no watermark and no canonical_index. Use `--full-refresh`:

```bash
bq-er run --config config.yml --full-refresh
```

This:
1. Ignores any existing watermark (processes ALL source records)
2. Creates the `canonical_index` table (empty schema on first CREATE IF NOT EXISTS)
3. Runs the full pipeline
4. Populates `canonical_index` with all entities and their cluster_ids
5. Writes the initial watermark (MAX cursor values from the staged data)

**For large initial loads**, combine with drain mode:

```bash
bq-er run --config config.yml --full-refresh --drain
```

This processes the entire source table in batches of `batch_size`, iterating until all records are consumed.

### Daily Operations

After the first run, standard incremental processing requires no special flags:

```bash
bq-er run --config config.yml
```

The pipeline:
1. Reads the watermark from `pipeline_watermarks`
2. Stages records WHERE cursor > watermark (up to `batch_size`)
3. Processes the batch (features, blocking, matching, clustering)
4. Updates `canonical_index` (update changed cluster_ids, insert new entities)
5. Advances the watermark

**Typical scheduling:** Cloud Scheduler or cron triggers the pipeline at regular intervals (e.g., every hour, every 6 hours). Each invocation processes one batch.

### Backlog Drain

When data accumulates faster than the pipeline processes it (e.g., after an outage):

```bash
# Process all pending records in a loop
bq-er run --config config.yml --drain

# With explicit iteration limit
bq-er run --config config.yml --drain --drain-max-iterations 20
```

Or configure drain mode permanently in YAML:

```yaml
incremental:
  drain_mode: true
  drain_max_iterations: 50
```

### Monitoring

**Check watermark positions:**

```sql
-- Current watermark for each source
SELECT source_name, cursor_column, cursor_value, cursor_type, updated_at
FROM `project.er_meta.pipeline_watermarks`
WHERE is_current = TRUE
ORDER BY source_name, cursor_column;
```

**Check canonical_index size:**

```sql
-- Total entities in canonical index
SELECT COUNT(*) AS total_entities,
       COUNT(DISTINCT cluster_id) AS total_clusters
FROM `project.er_gold.canonical_index`;
```

**Check cluster quality:**

```sql
-- Cluster size distribution
SELECT
  CASE
    WHEN cluster_size = 1 THEN 'singleton'
    WHEN cluster_size BETWEEN 2 AND 5 THEN '2-5'
    WHEN cluster_size BETWEEN 6 AND 20 THEN '6-20'
    WHEN cluster_size BETWEEN 21 AND 100 THEN '21-100'
    ELSE '100+'
  END AS size_bucket,
  COUNT(*) AS cluster_count
FROM (
  SELECT cluster_id, COUNT(*) AS cluster_size
  FROM `project.er_gold.canonical_index`
  GROUP BY cluster_id
)
GROUP BY 1 ORDER BY 1;
```

**Check watermark history (audit trail):**

```sql
-- Watermark advance history for the last 7 days
SELECT source_name, cursor_column, cursor_value, updated_at, run_id
FROM `project.er_meta.pipeline_watermarks`
WHERE updated_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY updated_at DESC;
```

### Recovery

**Failed run (mid-batch):**

If the pipeline fails during execution, the watermark was NOT advanced (watermark advances only after successful completion). Simply re-run:

```bash
bq-er run --config config.yml
```

The pipeline picks up from exactly the same watermark position and reprocesses the same batch.

**Checkpoint/resume (for long-running pipelines):**

When `scale.checkpoint_enabled: true`, the pipeline persists completed stages to a checkpoint table. On crash and re-run:

```bash
bq-er run --config config.yml --resume
```

This auto-detects the last incomplete run, loads completed stages, and skips them -- resuming from the failed stage instead of re-running everything.

**Corrupt canonical_index:**

If the canonical_index is corrupted or needs rebuilding:

```bash
# Drop and rebuild from scratch
bq-er run --config config.yml --full-refresh
```

This reprocesses all source records and rebuilds the canonical_index from scratch.

**Schema changes:**

When `full_refresh_on_schema_change: true` (the default), the pipeline detects schema changes in source tables and auto-triggers a full refresh. This ensures the canonical_index schema stays aligned with the featured table schema.

### Watermark Reset

To manually reset the watermark and reprocess from a specific point:

```sql
-- Mark current watermarks as not current
UPDATE `project.er_meta.pipeline_watermarks`
SET is_current = FALSE
WHERE source_name = 'policy_holders' AND is_current = TRUE;

-- Insert new watermark at desired position
INSERT INTO `project.er_meta.pipeline_watermarks`
  (source_name, cursor_column, cursor_value, cursor_type, updated_at, run_id, is_current)
VALUES
  ('policy_holders', 'updated_at', '2024-01-01T00:00:00Z', 'TIMESTAMP',
   CURRENT_TIMESTAMP(), 'manual_reset', TRUE),
  ('policy_holders', 'policy_id', '0', 'INT64',
   CURRENT_TIMESTAMP(), 'manual_reset', TRUE);
```

Then run the pipeline normally -- it will process everything after the new watermark position.

---

## 6. Cursor Profiler Tool

The cursor profiler analyzes source table columns to recommend the best cursor strategy. It answers the question: "Which column should I use as my secondary cursor?"

### CLI Usage

```bash
# Auto-detect candidate columns from config
bq-er profile-cursors --config config.yml --batch-size 5000000

# Specify candidate columns explicitly
bq-er profile-cursors --config config.yml --candidates policy_id state region

# Use a specific column for hash cursor profiling
bq-er profile-cursors --config config.yml --hash-column record_id
```

### Python Usage

```python
from bq_entity_resolution.tools.cursor_profiler import CursorProfiler

profiler = CursorProfiler(backend)

# Profile natural columns
natural_results = profiler.profile(
    table="my-project.raw.customers",
    primary_cursor="updated_at",
    candidate_columns=["policy_id", "state", "region"],
    batch_size=5_000_000,
)

# Profile hash cursor with different modulus values
hash_results = profiler.profile_hash_cursor(
    table="my-project.raw.customers",
    hash_column="record_id",
    primary_cursor="updated_at",
    modulus_values=[100, 500, 1000],
    batch_size=5_000_000,
)

# Get recommendation summary
print(profiler.recommend(natural_results, hash_results, batch_size=5_000_000))
```

### What It Analyzes

For each candidate column, the profiler runs a BigQuery query that computes:

| Metric | Description |
|--------|-------------|
| `distinct_values` | Total distinct values of the column |
| `max_records_per_primary` | Worst-case records sharing the same primary cursor value |
| `avg_records_per_primary` | Average records per primary cursor value |
| `std_dev_records` | Standard deviation of records per primary value |
| `uniformity_score` | 0-1, higher = more uniform distribution (less skew) |
| `estimated_batches` | Estimated number of batches to process all records |

For hash cursors, it additionally measures:

| Metric | Description |
|--------|-------------|
| `avg_records_per_bucket` | Average records per hash bucket |
| `max_records_per_bucket` | Maximum records in any single bucket |

### Interpreting the Output

```
Cursor Strategy Recommendation (batch_size=5,000,000)
============================================================

Natural Columns (preferred -- no compute cost):
  policy_id: ***** (score=0.92)
    Excellent cursor -- high cardinality (999) and uniform distribution
    distinct=999, uniformity=0.95, est_batches=6
  state: ** (score=0.35)
    Marginal cursor -- low cardinality (51), consider hash fallback
    distinct=51, uniformity=0.72, est_batches=6
  region: * (score=0.18)
    Poor cursor -- very low cardinality (4), use hash cursor instead
    distinct=4, uniformity=0.65, est_batches=6

Hash Cursors (fallback -- adds FARM_FINGERPRINT cost):
  MOD 1000: score=0.78
    Good hash cursor -- max bucket (5,200) fits within batch_size
    avg/bucket=28,000, max/bucket=35,000, est_batches=6

RECOMMENDATION: Use natural column 'policy_id' as secondary cursor.
```

**Score interpretation:**
- 0.7+ : Excellent -- use this column
- 0.5-0.7: Good -- adequate for most workloads
- 0.3-0.5: Marginal -- consider hash cursor fallback instead
- Below 0.3: Poor -- do not use; prefer hash cursor

**Source code:** `src/bq_entity_resolution/tools/cursor_profiler.py`

---

## 7. Capacity Planning

### Batch Size Selection

The `batch_size` parameter controls how many records are processed per pipeline execution. It directly affects BigQuery slot consumption, execution time, and cost.

| Batch Size | Typical Use Case | Expected Duration | Notes |
|------------|-----------------|-------------------|-------|
| 500K | Development/testing | 2-5 minutes | Fast iteration, minimal cost |
| 2M | Low-volume production | 5-15 minutes | Default setting |
| 5M | High-volume production | 15-45 minutes | Recommended starting point |
| 10M | Very high volume | 30-90 minutes | Monitor slot utilization closely |
| 20M+ | Extreme volume | 60-180 minutes | May need reserved slots |

**Recommendation:** Start with 5M and monitor BigQuery slot utilization. Adjust based on:
- **Execution time:** If batches take too long, reduce batch_size
- **Slot utilization:** If slots are underutilized, increase batch_size
- **Throughput requirements:** Ensure batch_size x runs_per_day >= daily record volume

### BigQuery Slot Recommendations

| Daily Volume | On-Demand | Autoscaling Slots | Flat-Rate Slots |
|-------------|-----------|-------------------|-----------------|
| <1M records | Sufficient | Not needed | Not needed |
| 1-10M records | Adequate | 100-200 slots | 100 slots |
| 10-50M records | May throttle | 200-500 slots | 200-500 slots |
| 50-100M records | Unreliable | 500-1000 slots | 500-1000 slots |
| 100M+ records | Not recommended | 1000+ slots | 1000+ slots |

**Key cost drivers in the pipeline:**
1. **Blocking stage:** The most expensive stage. Cross-batch blocking joins `featured` (batch) against `canonical_index` (all historical). Cost scales with `batch_size x canonical_index_size`.
2. **Clustering:** Connected components iteration. Cost scales with number of match edges.
3. **Staging:** Full table scan with watermark filter. Cost depends on source table size and partition pruning effectiveness.

### Cross-Batch Blocking Performance

Cross-batch blocking is the primary scaling concern. As the canonical_index grows, the cross-batch JOIN becomes more expensive.

**Scaling characteristics:**

| Canonical Index Size | Cross-Batch JOIN Cost | Mitigation |
|---------------------|----------------------|------------|
| <1M entities | Negligible | None needed |
| 1-10M entities | Moderate | CLUSTER BY blocking keys |
| 10-50M entities | Significant | Reduce candidate_limit, add more selective keys |
| 50-100M entities | High | Consider partitioning canonical_index |
| 100M+ entities | Very high | Tiered canonical index, archival strategy |

**Optimization strategies:**

1. **CLUSTER BY blocking keys** on canonical_index:
   ```yaml
   scale:
     canonical_index_clustering: [entity_uid]
   ```

2. **Reduce candidate_limit** per blocking path:
   ```yaml
   blocking:
     paths:
       - keys: [bk_name_zip]
         candidate_limit: 100  # Lower = fewer candidates, faster
   ```

3. **Use more selective blocking keys** (multiple keys per path):
   ```yaml
   blocking:
     paths:
       - keys: [bk_name_zip, bk_state]  # Two keys = more selective join
   ```

4. **INT64 blocking keys** (FARM_FINGERPRINT-based) are 3-5x faster than STRING keys:
   ```yaml
   blocking_keys:
     - name: bk_name_zip
       function: farm_fingerprint_concat  # Produces INT64
       inputs: [name_soundex, zip5]
   ```

### Watermark Advance Strategy

The watermark advances to the MAX cursor values from the **staged batch**, not the raw source table. This prevents watermark drift:

```
Source has records up to date 2024-01-20
Watermark is at 2024-01-15
Batch stages records from 2024-01-15 to 2024-01-17 (5M records)
Watermark advances to 2024-01-17 (not 2024-01-20)
Next batch picks up from 2024-01-17
```

This ensures no records are skipped between the batch boundary and the source maximum.

**Source code:** `src/bq_entity_resolution/watermark/manager.py` -- `compute_new_watermark_from_staged()`

---

## 8. Example: Insurance Use Case

This section walks through a real-world configuration for an insurance entity resolution pipeline processing 28M+ records per day.

### Scenario

- **Source:** Insurance policy records, 28M+ new/updated records per day
- **Granularity:** All records for a given day share the same `source_date`
- **Secondary column:** `source_policyid` (integer, values 1-999 per date)
- **Goal:** Resolve insured entities across policy records into unique canonical entities
- **SLA:** All records processed within 24 hours

### Configuration

```yaml
version: "1.0"

project:
  name: "insurance_entity_resolution"
  bq_project: "${BQ_PROJECT}"
  bq_dataset_bronze: "er_bronze"
  bq_dataset_silver: "er_silver"
  bq_dataset_gold: "er_gold"
  watermark_dataset: "er_meta"

sources:
  - name: "policy_holders"
    table: "${BQ_PROJECT}.raw_insurance.insured_entities"
    unique_key: "record_id"
    updated_at: "source_date"
    columns:
      - name: "record_id"
        type: "STRING"
      - name: "source_policyid"
        type: "INT64"
      - name: "insured_name"
        type: "STRING"
      - name: "address_line_1"
        type: "STRING"
      - name: "city"
        type: "STRING"
      - name: "state"
        type: "STRING"
      - name: "zip_code"
        type: "STRING"
      - name: "phone"
        type: "STRING"
      - name: "email"
        type: "STRING"
      - name: "ein"
        type: "STRING"
    passthrough_columns:
      - "policy_id"
      - "file_id"

# -- Incremental processing: composite watermark --
incremental:
  enabled: true

  # Composite cursor: source_date + source_policyid
  # 28M records/day, ~28K per policyid value (28M / 999)
  # With batch_size=5M, each batch spans ~178 policyid values
  cursor_columns: [source_date, source_policyid]
  cursor_mode: ordered

  # 5M per batch: 28M / 5M = ~6 batches per day
  batch_size: 5_000_000

  # Re-scan 48 hours back to catch late arrivals
  grace_period_hours: 48

  # Drain mode: process all pending in a loop
  # Each invocation processes all pending records (6 iterations/day)
  drain_mode: true
  drain_max_iterations: 20

# -- Matching tiers with cross-batch blocking --
matching_tiers:
  - name: "exact_composite"
    blocking:
      paths:
        - keys: [ck_name_full_address]
          candidate_limit: 100
      cross_batch: true    # Match new 5M against ALL historical
    comparisons:
      - left: "ck_name_full_address"
        right: "ck_name_full_address"
        method: "exact"
        weight: 10.0
    threshold:
      method: "sum"
      min_score: 10.0

  - name: "fuzzy_name"
    blocking:
      paths:
        - keys: [bk_name_zip]
          candidate_limit: 200
        - keys: [bk_name_city]
          candidate_limit: 150
      cross_batch: true    # Critical: new records must match against history
    comparisons:
      - left: "name_clean"
        right: "name_clean"
        method: "levenshtein_normalized"
        params: { threshold: 0.75 }
        weight: 4.0
      - left: "address_clean"
        right: "address_clean"
        method: "levenshtein_normalized"
        params: { threshold: 0.75 }
        weight: 3.0
      - left: "zip5"
        right: "zip5"
        method: "exact"
        weight: 2.0
    threshold:
      method: "sum"
      min_score: 8.0

# -- Scale optimizations --
scale:
  staging_partition_by: "DATE(source_updated_at)"
  staging_clustering: [entity_uid, source_name]
  candidates_clustering: [l_entity_uid]
  matches_clustering: [l_entity_uid, r_entity_uid]
  canonical_index_clustering: [entity_uid]
  checkpoint_enabled: true

# -- Reconciliation --
reconciliation:
  clustering:
    method: "connected_components"
    max_iterations: 20
  canonical_selection:
    method: "completeness"
  output:
    entity_id_prefix: "INS"
```

### Processing Timeline

**Day 1 (initial load):**

```bash
# Full refresh with drain mode: process all historical records
bq-er run --config config.yml --full-refresh --drain
```

Processing: 200M historical records in 40 iterations of 5M each.
- Each iteration: ~30 minutes (staging + features + blocking + matching + clustering)
- Total: ~20 hours (can be parallelized with multiple batch ranges)
- Result: canonical_index populated with 200M entities, watermark set to latest

**Day 2+ (incremental):**

```bash
# Scheduled every 4 hours via Cloud Scheduler
bq-er run --config config.yml
```

Processing: 28M new records, drain mode active, ~6 iterations per invocation.
- Each iteration: ~15 minutes (5M records, cross-batch against 200M+ canonical)
- Total per invocation: ~90 minutes
- Watermark advances: source_date=2024-01-16, source_policyid=450 (midpoint of day)
- Next invocation picks up from (2024-01-16, 450)

### Generated SQL (Staging)

For the composite ordered cursor, the staging SQL looks like:

```sql
CREATE OR REPLACE TABLE `project.er_bronze.staged_policy_holders`
PARTITION BY DATE(source_updated_at)
CLUSTER BY entity_uid, source_name
AS

SELECT
  FARM_FINGERPRINT(
    CONCAT('policy_holders', '||', CAST(record_id AS STRING))
  ) AS entity_uid,

  'policy_holders' AS source_name,
  record_id,
  source_policyid,
  insured_name,
  address_line_1,
  city,
  state,
  zip_code,
  phone,
  email,
  ein,
  policy_id,
  file_id,
  source_date AS source_updated_at,
  CURRENT_TIMESTAMP() AS pipeline_loaded_at

FROM `project.raw_insurance.insured_entities` AS src
WHERE 1=1
AND (
  source_date > TIMESTAMP_SUB(TIMESTAMP('2024-01-15T00:00:00Z'), INTERVAL 48 HOUR)
  OR (source_date = TIMESTAMP('2024-01-15T00:00:00Z') AND source_policyid > 450)
)
ORDER BY source_date, source_policyid, entity_uid
LIMIT 5000000
```

### Generated SQL (Incremental Clustering)

```sql
DECLARE iteration INT64 DEFAULT 0;
DECLARE rows_updated INT64 DEFAULT 1;

-- Init: prior entities from canonical_index + new singletons
CREATE OR REPLACE TABLE `project.er_silver.entity_clusters` AS
SELECT entity_uid, cluster_id FROM `project.er_gold.canonical_index`
UNION ALL
SELECT DISTINCT entity_uid, entity_uid AS cluster_id
FROM `project.er_silver.featured`
WHERE entity_uid NOT IN (SELECT entity_uid FROM `project.er_gold.canonical_index`);

-- Iterative propagation
WHILE rows_updated > 0 AND iteration < 20 DO
  -- ... build edge list, compute MIN cluster_id, replace table ...
  SET iteration = iteration + 1;
END WHILE;
```

### Generated SQL (Canonical Index Populate)

```sql
-- Update cluster_ids for entities that were re-clustered
UPDATE `project.er_gold.canonical_index` ci
SET cluster_id = cl.cluster_id
FROM `project.er_silver.entity_clusters` cl
WHERE ci.entity_uid = cl.entity_uid
  AND ci.cluster_id != cl.cluster_id;

-- Insert new entities from current batch
INSERT INTO `project.er_gold.canonical_index`
SELECT f.*, cl.cluster_id
FROM `project.er_silver.featured` f
JOIN `project.er_silver.entity_clusters` cl USING (entity_uid)
WHERE f.entity_uid NOT IN (SELECT entity_uid FROM `project.er_gold.canonical_index`);
```

---

## Appendix: File Reference

| File | Purpose |
|------|---------|
| `src/bq_entity_resolution/config/models/infrastructure.py` | `IncrementalConfig`, `HashCursorConfig`, `PartitionCursorConfig` |
| `src/bq_entity_resolution/sql/builders/staging.py` | Staging SQL with watermark filtering, ordered tuple comparison |
| `src/bq_entity_resolution/sql/builders/watermark.py` | Watermark table DDL, read, atomic update |
| `src/bq_entity_resolution/sql/builders/blocking.py` | Multi-path blocking with intra-batch + cross-batch CTEs |
| `src/bq_entity_resolution/sql/builders/clustering.py` | Incremental clustering, canonical index init/populate |
| `src/bq_entity_resolution/watermark/manager.py` | `WatermarkManager` -- read, write, compute, drain check |
| `src/bq_entity_resolution/watermark/checkpoint.py` | `CheckpointManager` -- crash recovery persistence |
| `src/bq_entity_resolution/stages/staging.py` | `StagingStage` -- wires config to staging SQL builder |
| `src/bq_entity_resolution/stages/blocking.py` | `BlockingStage` -- wires cross_batch + canonical_index |
| `src/bq_entity_resolution/stages/reconciliation.py` | `ClusteringStage`, `CanonicalIndexInitStage`, `CanonicalIndexPopulateStage` |
| `src/bq_entity_resolution/pipeline/dag.py` | `build_pipeline_dag()` -- DAG wiring for incremental stages |
| `src/bq_entity_resolution/pipeline/pipeline.py` | `Pipeline.run()` -- drain mode loop, watermark integration |
| `src/bq_entity_resolution/tools/cursor_profiler.py` | `CursorProfiler` -- analyze columns for cursor strategies |
| `src/bq_entity_resolution/naming.py` | `canonical_index_table()`, `checkpoint_table()` |

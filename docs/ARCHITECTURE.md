# Architecture

## System Overview

bq-entity-resolution is a DAG-based entity resolution pipeline where Python handles configuration, validation, SQL generation, and orchestration while BigQuery (or DuckDB for local testing) executes all data processing.

```
                    YAML Config
                        │
                        ▼
              ┌─────────────────────┐
              │   PipelineConfig    │    config/schema.py (28 Pydantic v2 models)
              │   + Validators      │    config/validators.py (cross-field checks)
              └─────────┬───────────┘
                        │
              ┌─────────▼───────────┐
              │      Pipeline       │    pipeline/pipeline.py (main entry point)
              │   validate → plan   │
              │      → execute      │
              └─────────┬───────────┘
                        │
           ┌────────────▼────────────┐
           │       StageDAG          │    pipeline/dag.py
           │   (topological sort)    │
           │                         │
           │  build_pipeline_dag()   │    Constructs stages from config,
           │  wires tier chains:     │    sets up dependencies:
           │  staging → features     │    tier[i].blocking → tier[i-1].matching
           │  → blocking → matching  │
           │  → clustering → gold    │
           └────────────┬────────────┘
                        │
           ┌────────────▼────────────┐
           │      PipelinePlan       │    pipeline/plan.py
           │   (immutable SQL)       │    create_plan(): calls stage.plan()
           │                         │    for each stage in topo order
           │  StagePlan per stage:   │    Returns list[SQLExpression]
           │  [SQLExpression, ...]   │
           └────────────┬────────────┘
                        │
           ┌────────────▼────────────┐
           │    PipelineExecutor     │    pipeline/executor.py
           │                         │
           │  For each StagePlan:    │    Executes SQL via Backend
           │  1. Check dependencies  │    Enforces quality gates
           │  2. Execute SQL         │    Supports checkpoint/resume
           │  3. Run quality gates   │
           │  4. Mark checkpoint     │
           └────────────┬────────────┘
                        │
           ┌────────────▼────────────┐
           │     Backend Protocol    │    backends/protocol.py
           │                         │
           │  BigQueryBackend        │    backends/bigquery.py (production)
           │  DuckDBBackend          │    backends/duckdb.py (local testing)
           │  BQEmulatorBackend      │    backends/bqemulator.py (Docker)
           └─────────────────────────┘
```

## Module Dependency Graph

```
                      config/schema.py
                   (Pydantic v2 models)
                          │
          ┌───────────────┼───────────────────┐
          │               │                   │
          ▼               ▼                   ▼
config/loader.py   config/validators.py   naming.py
(YAML + env vars)  (cross-field checks)   (table names)
                                              │
          ┌───────────────┬───────────────────┤
          │               │                   │
          ▼               ▼                   ▼
features/registry   matching/comparisons   sql/builders/*
(60+ functions)     (30+ functions)        (14 modules)
          │               │                   │
          │         ┌─────┴─────┐             │
          │         │           │             │
          │    hard_negatives  soft_signals   ▼
          │         │           │         sql/expression.py
          │         └─────┬─────┘        (SQLExpression)
          │               │                   │
          ▼               ▼                   │
    stages/features   stages/matching    ◄────┘
    stages/staging    stages/blocking
    stages/reconciliation
    stages/active_learning
          │               │
          └───────┬───────┘
                  │
          pipeline/dag.py    → pipeline/plan.py → pipeline/executor.py
                  │
                  ▼
          pipeline/pipeline.py  ◄── pipeline/validator.py
                  │                  pipeline/gates.py
                  ▼                  pipeline/context.py
          backends/protocol.py
          (execution + retries)
```

No circular dependencies. Config modules never import stages. Stages never import the backend directly (the executor bridges them via the plan).

## SQL Builder Architecture

All SQL generation uses Python builder functions instead of templates. Every builder follows the same pattern:

```python
@dataclass(frozen=True)
class SomeParams:
    """Type-safe, immutable parameter container."""
    target_table: str
    source_table: str
    # ... all parameters with types and defaults

def build_some_sql(params: SomeParams) -> SQLExpression:
    """Pure function: params in, SQL out."""
    parts: list[str] = []
    # ... build SQL string
    return SQLExpression.from_raw("\n".join(parts))
```

### Builder Inventory (14 modules, 30 functions)

| Module | Builder Functions | Params |
|--------|------------------|--------|
| `staging.py` | `build_staging_sql` | `StagingParams`, `JoinDef` |
| `features.py` | `build_features_sql`, `build_term_frequencies_sql` | `FeatureParams`, `FeatureExpr`, `TFColumn` |
| `blocking.py` | `build_blocking_sql`, `build_blocking_metrics_sql` | `BlockingParams`, `BlockingPath`, `BlockingMetricsParams` |
| `comparison.py` | `build_sum_scoring_sql`, `build_fellegi_sunter_sql` | `SumScoringParams`, `FellegiSunterParams`, `ComparisonDef`, `ComparisonLevel`, `HardNegative`, `SoftSignal`, `Threshold` |
| `clustering.py` | `build_cluster_assignment_sql`, `build_incremental_cluster_sql`, `build_populate_canonical_index_sql`, `build_cluster_quality_metrics_sql` | `ClusteringParams`, `IncrementalClusteringParams`, `PopulateCanonicalIndexParams`, `ClusterMetricsParams` |
| `gold_output.py` | `build_gold_output_sql` | `GoldOutputParams` |
| `golden_record.py` | `build_golden_record_cte` | `GoldenRecordParams`, `FieldStrategy` |
| `em.py` | `build_em_estimation_sql`, `build_estimate_from_labels_sql`, `build_em_estep_sql`, `build_em_mstep_sql` | `EMParams`, `LabelEstimationParams`, `EMComparison`, `EMLevel` |
| `embeddings.py` | `build_embeddings_sql`, `build_lsh_buckets_sql` | `EmbeddingsParams`, `LSHParams` |
| `active_learning.py` | `build_active_learning_sql`, `build_ingest_labels_sql` | `ActiveLearningParams`, `IngestLabelsParams` |
| `watermark.py` | `build_create_watermark_table_sql`, `build_read_watermark_sql`, `build_update_watermark_sql`, `build_create_checkpoint_table_sql` | (simple params) |
| `udf.py` | `build_jaro_winkler_udf_sql` | (simple params) |
| `monitoring.py` | `build_persist_sql_log_sql` | (simple params) |

### SQLExpression

`sql/expression.py` provides the `SQLExpression` wrapper:
- **Raw mode** (`from_raw(sql_string)`): Wraps a SQL string. Used by all builders.
- **AST mode** (`from_node(sqlglot_node)`): Wraps a sqlglot AST for dialect translation.
- `.render(dialect="bigquery")`: Returns the SQL string, optionally transpiled to target dialect.

## Stage Architecture

Each stage is a composable unit of work:

```python
class Stage(ABC):
    """Base class for pipeline stages."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def inputs(self) -> list[TableRef]: ...

    @abstractmethod
    def outputs(self) -> list[TableRef]: ...

    @abstractmethod
    def plan(self) -> list[SQLExpression]: ...
```

### Stage Types

| Stage | Inputs | Outputs | Builder Used |
|-------|--------|---------|-------------|
| `StagingStage` | Source tables | `staged_{source}` | `staging.py` |
| `FeatureEngineeringStage` | Staged tables | `featured` | `features.py` |
| `TermFrequencyStage` | Featured table | `term_frequencies` | `features.py` |
| `BlockingStage` | Featured, (prior matches) | `candidates_{tier}` | `blocking.py` |
| `MatchingStage` | Candidates, featured | `matches_{tier}` | `comparison.py` |
| `ClusteringStage` | All matches, featured | `entity_clusters` | `clustering.py` |
| `GoldOutputStage` | Clusters, featured, matches | `resolved_entities` | `gold_output.py` |
| `ActiveLearningStage` | Matches | `al_review_queue_{tier}` | `active_learning.py` |

### DAG Wiring

The `build_pipeline_dag()` function constructs the stage graph:

```
StagingStage(src1) ─┐
StagingStage(src2) ─┤
                    └──► FeatureEngineeringStage ──► BlockingStage(tier1)
                                                         │
                                                         ▼
                                                    MatchingStage(tier1) ──► BlockingStage(tier2)
                                                                                │
                                                                                ▼
                                                                           MatchingStage(tier2)
                                                                                │
                                                         ┌──────────────────────┘
                                                         ▼
                                                    ClusteringStage ──► GoldOutputStage
```

Cross-tier dependency: `BlockingStage(tier N)` depends on `MatchingStage(tier N-1)` so prior matches can be excluded from candidate generation.

## Probabilistic Matching (Fellegi-Sunter)

When a tier uses `threshold.method: fellegi_sunter`, the pipeline uses log-likelihood ratio scoring:

```
                              ┌──────────────────┐
                              │  Training Config  │
                              │  (em / labeled /  │
                              │   none)           │
                              └────────┬─────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
           EM Estimation      Labeled Training     Manual m/u
           (BQ scripting)     (BQ SQL query)       (from config)
           build_em_          build_estimate_      ComparisonLevelDef
           estimation_sql()   from_labels_sql()    .m / .u
                    │                  │                  │
                    └──────────────────┼──────────────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │ TierParameters    │
                              │  per-comparison   │
                              │  per-level m/u    │
                              │  log_prior_odds   │
                              └────────┬─────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │ Log-weight calc   │
                              │ log2(m/u) per     │
                              │ level, clamped    │
                              │ [0.001, 0.999]    │
                              └────────┬─────────┘
                                       │
                                       ▼
                              ┌──────────────────────┐
                              │ build_fellegi_       │
                              │ sunter_sql()         │
                              │                      │
                              │ CASE/WHEN per        │
                              │ comparison level     │
                              │ total_score =        │
                              │ Σ log_weights        │
                              │ confidence =         │
                              │ 2^W / (1 + 2^W)     │
                              └────────┬─────────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │ Active Learning   │
                              │ (optional)        │
                              │ Review queue of   │
                              │ uncertain pairs   │
                              └──────────────────┘
```

### m/u Precedence

When resolving m and u probabilities for each comparison level:

1. **Config values** — `ComparisonLevelDef.m` / `.u` from YAML (highest priority)
2. **Estimation results** — From EM or labeled training
3. **Label defaults** — `exact` -> (0.9, 0.1), `fuzzy` -> (0.7, 0.2), `else` -> (0.1, 0.9)

### EM Algorithm (BigQuery Scripting)

The EM estimation runs entirely within BigQuery using scripting (`DECLARE`/`LOOP`/`SET`):

1. **Sample** — Random candidate pairs with comparison outcomes -> temp table
2. **Initialize** — m/u priors per level (match=0.9/0.1, else=0.1/0.9)
3. **E-step** — For each pair, compute match probability using current m/u (log-space)
4. **M-step** — Update m/u as weighted averages using soft match assignments
5. **Converge** — Stop when max delta < threshold or max iterations reached
6. **Clamp** — Final m/u clamped to [0.001, 0.999] to prevent log(0)

## Data Flow (Bronze -> Silver -> Gold)

```
Source Tables                    Bronze Layer                  Silver Layer                    Gold Layer
┌──────────┐    Staging SQL    ┌──────────────┐  Feature SQL  ┌──────────────┐               ┌──────────────┐
│ source_1 │ ──────────────►  │staged_source1│ ──────────►  │  featured    │               │  resolved    │
└──────────┘                  └──────────────┘              │  (all cols   │  Cluster SQL  │  _entities   │
┌──────────┐    Staging SQL    ┌──────────────┐  UNION ALL   │  + features  │ ──────────►  │  (cluster_id │
│ source_2 │ ──────────────►  │staged_source2│ ──────────►  │  + blocking  │               │  canonical   │
└──────────┘                  └──────────────┘              │  + composite)│               │  is_canonical│
                                                            └──────┬───────┘               │  match_meta) │
                                                                   │                       └──────────────┘
                                                                   ▼
                                                    ┌──────────────────────────┐
                                                    │  Per-Tier Tables:         │
                                                    │  candidates_{tier_name}   │
                                                    │  matches_{tier_name}      │
                                                    │  all_matched_pairs        │
                                                    │  entity_clusters          │
                                                    └──────────────────────────┘
```

## Table Naming Convention

All table names are constructed in `naming.py`. Pattern: `{bq_project}.{dataset}.{suffix}`

| Function | Dataset | Suffix | Example |
|----------|---------|--------|---------|
| `staged_table(cfg, "src1")` | bronze | `staged_src1` | `proj.er_bronze.staged_src1` |
| `featured_table(cfg)` | silver | `featured` | `proj.er_silver.featured` |
| `candidates_table(cfg, "fuzzy")` | silver | `candidates_fuzzy` | `proj.er_silver.candidates_fuzzy` |
| `matches_table(cfg, "fuzzy")` | silver | `matches_fuzzy` | `proj.er_silver.matches_fuzzy` |
| `all_matches_table(cfg)` | silver | `all_matched_pairs` | `proj.er_silver.all_matched_pairs` |
| `cluster_table(cfg)` | silver | `entity_clusters` | `proj.er_silver.entity_clusters` |
| `resolved_table(cfg)` | gold | `resolved_entities` | `proj.er_gold.resolved_entities` |
| `embeddings_table(cfg)` | silver | `entity_embeddings` | `proj.er_silver.entity_embeddings` |
| `lsh_buckets_table(cfg)` | silver | `lsh_buckets` | `proj.er_silver.lsh_buckets` |
| `parameters_table(cfg, "tier")` | silver | `fs_parameters_tier` | `proj.er_silver.fs_parameters_tier` |
| `review_queue_table(cfg, "tier")` | silver | `al_review_queue_tier` | `proj.er_silver.al_review_queue_tier` |
| `labels_table(cfg)` | silver | `al_labels` | `proj.er_silver.al_labels` |
| `term_frequency_table(cfg)` | silver | `term_frequencies` | `proj.er_silver.term_frequencies` |
| `checkpoint_table(cfg)` | silver | `pipeline_checkpoints` | `proj.er_silver.pipeline_checkpoints` |
| `sql_audit_table(cfg)` | silver | `pipeline_sql_audit` | `proj.er_silver.pipeline_sql_audit` |

## Registry Pattern

Feature functions and comparison functions use the same extensible pattern:

```python
FUNCTIONS: dict[str, Callable] = {}

def register(name: str):
    def decorator(func):
        FUNCTIONS[name] = func
        return func
    return decorator

@register("my_function")
def my_function(inputs, **kwargs):
    return "SQL expression"
```

YAML config references functions by name. Stages look them up at SQL generation time. Unknown names produce clear errors listing all available functions.

## Entity UID Generation

Every staged record gets a deterministic `entity_uid`:

```sql
FARM_FINGERPRINT(
  CONCAT('{source_name}', '||', CAST({unique_key} AS STRING))
) AS entity_uid
```

This means:
- Same source + same unique_key = same entity_uid (deterministic)
- Different sources with same key = different entity_uid (source-scoped)
- Renaming a source = new entity_uid (intentional — source identity matters)

## Connected Components Clustering

The clustering algorithm uses iterative BigQuery scripting:

1. **Initialize** — Every entity starts as its own cluster (entity_uid = cluster_id)
2. **Propagate** — For each edge in matches, propagate the minimum cluster_id to both endpoints
3. **Converge** — Repeat until no changes or max_iterations reached
4. **Result** — Each entity has a cluster_id. Entities in the same cluster are considered the same real-world entity.

Unmatched entities remain as singleton clusters (cluster of 1) in the gold output.

### Incremental Clustering

For incremental processing, `build_incremental_cluster_sql()` initializes from prior cluster assignments stored in the `canonical_index` table, then propagates new match edges. This preserves cluster stability across batches.

## Incremental Processing

The watermark system tracks the high-water mark of cursor columns (typically `updated_at`) per source:

1. **Read** — Before staging, read last watermark from `pipeline_watermarks` table
2. **Filter** — Staging SQL: `WHERE updated_at > watermark - grace_period`
3. **Grace Period** — Subtracts N hours from watermark to catch late-arriving records
4. **Advance** — After successful pipeline completion, write new watermark = MAX(cursor_column)
5. **Transactional** — Watermarks only advance on success. Failed runs don't corrupt state.

### Checkpoint/Resume

The `CheckpointManager` persists completed stage names to a BigQuery table. On restart:
1. Load completed stages for the current run_id
2. Skip stages already completed
3. Resume from the first incomplete stage

## Quality Gates

The executor runs quality gates after each stage:

| Gate | What It Checks |
|------|---------------|
| `OutputNotEmptyGate` | Table has at least 1 row (prevents silent data loss) |
| `ClusterSizeGate` | Max cluster size below threshold (prevents runaway merges) |

Gates can abort the pipeline with `PipelineAbortError` and structured diagnostics.

## Error Handling

```
EntityResolutionError (base)
├── ConfigurationError          — YAML/validation errors
├── SQLGenerationError          — Builder/SQL construction failures
├── SQLExecutionError           — BigQuery execution failures (has sql, job_id)
├── WatermarkError              — Watermark read/write failures
├── BlockingError               — Blocking SQL generation failures
├── MatchingError               — Matching SQL generation failures
├── ParameterEstimationError    — Fellegi-Sunter parameter estimation failures
├── ReconciliationError         — Clustering/gold output failures
├── EmbeddingError              — Embedding computation failures
└── PipelineAbortError          — Pipeline-level abort (quality gate failures)
```

BigQuery client retries `ServiceUnavailable` errors up to 3 times with exponential backoff (5s, 10s, 20s).

## Contract Validation

The `pipeline/validator.py` performs compile-time checks:

1. **Input satisfaction** — Every stage's declared inputs are produced by an earlier stage's outputs
2. **No dangling outputs** — All declared outputs are consumed by at least one downstream stage
3. **DAG acyclicity** — The stage graph has no cycles (guaranteed by topological sort)
4. **Schema alignment** — Source column sets are compatible for UNION operations

These checks run before any SQL is generated, catching configuration errors early.

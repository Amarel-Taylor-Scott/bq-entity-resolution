# Stages Package

## Purpose

Implements the individual pipeline stages. Each Stage subclass declares its table inputs/outputs (for DAG ordering) and implements `plan()` to generate SQL via the builders.

## Key Files

| File | Description |
|------|-------------|
| `base.py` | **Stage** abstract base class with `plan()`, `inputs`, `outputs` properties. **TableRef** for DAG edge declaration. |
| `staging.py` | **StagingStage** — creates staging tables with watermark-filtered data from source tables. |
| `features.py` | **FeaturesStage** — feature engineering: clean/transform columns, generate blocking keys, enrichment joins. |
| `blocking.py` | **BlockingStage** — generates candidate pairs via blocking key joins. One per matching tier. |
| `matching.py` | **MatchingStage** — scores candidate pairs using comparison functions. Supports sum scoring, Fellegi-Sunter, term frequency, signals framework. |
| `match_accumulation.py` | **MatchAccumulationStage** — accumulates match pairs across tiers into `all_matches` table. |
| `clustering.py` | **ClusteringStage** — connected components clustering (BQ scripting WHILE loop). Supports incremental mode via canonical index. |
| `canonical_index.py` | **CanonicalIndexInitStage / CanonicalIndexPopulateStage** — maintains a persistent index of all entities with their cluster IDs across batches. |
| `gold_output.py` | **GoldOutputStage** — writes final resolved entities to gold dataset. |
| `cluster_quality.py` | **ClusterQualityStage** — computes cluster quality metrics (size distribution, confidence). |
| `active_learning.py` | **ActiveLearningStage** — generates review queues of uncertain matches near the threshold. |
| `reconciliation.py` | **ReconciliationStage** — golden record construction from clusters. |
| `label_ingestion.py` | **LabelIngestionStage** — ingests human labels for active learning feedback. |
| `bqml_classification.py` | **BQMLClassificationStage** — BQML model training and prediction for match classification. |

## Architecture

```
build_pipeline_dag(config)
  → Stage instances created from config
  → StageDAG resolves execution order via topological sort
  → create_plan() calls stage.plan() for each stage in order
  → PipelinePlan with all SQL ready to execute
```

Per-tier stage chain (repeated for each matching tier):
```
BlockingStage(tier_N) → MatchingStage(tier_N) → MatchAccumulationStage(tier_N)
```

## Key Patterns

- **TableRef** — stages declare `inputs` and `outputs` as sets of `TableRef(dataset, table_name)`. The DAG resolver uses these to determine execution order.
- **Multi-tier matching** — `create_plan()` generates 3 stages per tier (blocking → matching → accumulation), injecting `excluded_pairs_table` for cross-tier exclusion.
- **Incremental pipeline** — `CanonicalIndexInitStage` → `ClusteringStage(incremental)` → `CanonicalIndexPopulateStage` for cross-batch entity accumulation.

## Dependencies

- `sql/builders/` — SQL generation
- `config/` — stage-specific configuration
- `features/` — feature function registry (FeaturesStage)
- `matching/` — comparison registry, parameters (MatchingStage)
- `naming.py` — table name generation
- `columns.py` — column constants

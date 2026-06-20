# CLAUDE.md — AI Agent Integration Guide

> This file provides step-by-step instructions for AI assistants and LLMs
> to help users integrate bq-entity-resolution into their environment.

## Project Overview

**bq-entity-resolution** is a config-driven entity resolution pipeline for BigQuery.
Python generates SQL; BigQuery (or DuckDB locally) executes it. No data leaves the warehouse.

- **3,833 tests**, all passing (160+ source files, 25,000+ LOC)
- **v0.2.0** — published to PyPI as `bq-entity-resolution`
- **Python 3.11+** with Pydantic v2, Click, structlog, sqlglot
- **19 entity types**, 57 column roles, 16 domain presets, 20 example configs

## Quick Reference

```bash
# Tests
python -m pytest tests/ -v                    # 3833 tests, ~90s
C:/Users/amare/AppData/Local/Programs/Python/Python312/python.exe -m pytest tests/ -v  # Windows

# Lint + Type Check
python -m ruff check src/ tests/
python -m mypy src/

# Build
python -m build                               # → dist/*.whl

# CLI
bq-er validate --config config.yml
bq-er preview-sql --config config.yml --tier exact --stage all
bq-er run --config config.yml --dry-run
bq-er run --config config.yml --full-refresh
bq-er run --config config.yml --drain              # Process all pending batches
bq-er profile-cursors --config config.yml           # Recommend cursor strategies
bq-er profile-placeholders --config config.yml      # Detect placeholder values
bq-er profile --config config.yml                   # Profile source data
bq-er describe --config config.yml                  # Describe pipeline configuration
```

---

## Step-by-Step: Help a User Set Up a New Pipeline

### Step 1: Environment & Authentication

**Local development (no BigQuery needed):**
```bash
pip install "bq-entity-resolution[local]"
# Uses DuckDB backend — no credentials required
```

**BigQuery production:**
```bash
pip install bq-entity-resolution

# Option A: gcloud CLI auth (developer workstation)
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# Option B: Service account key (CI/CD, Docker)
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Option C: Workload Identity (GKE / Argo Workflows)
# No env vars needed — credentials injected by GKE metadata server
# See "Kubernetes Deployment" section below
```

**Required BigQuery permissions:**
```
bigquery.datasets.create        # Create er_bronze, er_silver, er_gold, er_meta datasets
bigquery.tables.create          # Create staging, feature, candidate, match tables
bigquery.tables.updateData      # INSERT/UPDATE for watermarks, checkpoints
bigquery.tables.getData         # Read source tables
bigquery.jobs.create            # Run queries
bigquery.routines.create        # Create Jaro-Winkler JS UDF (if using jaro_winkler comparison)
```

**Minimal IAM role:** `roles/bigquery.dataEditor` + `roles/bigquery.jobUser`

### Step 2: Discover Source Tables

**If the user knows their table structure:**
```python
from bq_entity_resolution import quick_config, Pipeline

config = quick_config(
    bq_project="my-project",
    source_table="my-project.raw.customers",
    columns=["first_name", "last_name", "email", "phone"],
)
```

**If the user wants auto-discovery from a live table:**
```python
from bq_entity_resolution import Pipeline
from bq_entity_resolution.backends.bigquery import BigQueryBackend

backend = BigQueryBackend(project="my-project")
pipeline = Pipeline.from_table(
    "my-project.raw.customers",
    backend=backend,
)
# Auto-discovers columns, detects roles, generates features + tiers
print(pipeline.config.to_yaml())  # Inspect the generated config
```

**If the user wants to inspect column roles before committing:**
```python
from bq_entity_resolution.config.roles import detect_role

for col in ["first_name", "email", "policy_number", "claim_id"]:
    print(f"{col} -> {detect_role(col)}")
# first_name -> first_name
# email -> email
# policy_number -> policy_number
# claim_id -> claim_number
```

### Step 3: Configure Matching Logic

**Three levels of configuration (progressive disclosure):**

| Level | Method | Effort | Control |
|-------|--------|--------|---------|
| 1 | `quick_config()` or `Pipeline.from_table()` | 5 lines | Auto-everything |
| 2 | Role-based preset (`person_dedup_preset`, `insurance_dedup_preset`, etc.) | 10 lines | Choose columns + roles |
| 3 | Full YAML config | 50-500 lines | Complete control |

**Level 1 → Level 3 workflow (recommended):**
```python
# Start with auto-config
config = quick_config(bq_project="my-proj", source_table="...", columns=[...])

# Export to YAML for manual tuning
yaml_str = config.to_yaml()
with open("my_config.yml", "w") as f:
    f.write(yaml_str)

# Edit YAML, then reload
from bq_entity_resolution import load_config
config = load_config("my_config.yml")
```

**Key YAML sections to explain to users:**

```yaml
# 1. Project routing — where tables are created
project:
  name: customer_dedup
  bq_project: "${BQ_PROJECT}"      # Environment variable
  bq_dataset_bronze: er_bronze     # Staging tables
  bq_dataset_silver: er_silver     # Feature/match tables
  bq_dataset_gold: er_gold         # Final output

# 2. Sources — what tables to resolve
sources:
  - name: customers
    table: "${BQ_PROJECT}.raw.customers"
    unique_key: customer_id         # Primary key for entity UID generation
    updated_at: updated_at          # Timestamp for incremental processing
    columns:
      - name: first_name
        role: first_name            # Auto-generates features + comparisons
      - name: email
        role: email

# 3. Feature engineering — how columns are cleaned/transformed
feature_engineering:
  name_features:
    features:
      - name: first_name_clean
        function: name_clean         # One of 104 built-in functions
        input: first_name
  blocking_keys:
    - name: bk_email
      function: farm_fingerprint
      inputs: [email_clean]

# 4. Matching tiers — cascading match strategies
matching_tiers:
  - name: exact
    blocking:
      paths:
        - keys: [bk_email]
    comparisons:
      - left: email_clean
        right: email_clean
        method: exact                # One of 54 built-in methods
        weight: 5.0
    threshold:
      min_score: 5.0
```

### Step 4: Preview and Validate

```bash
# Validate config (catches errors before any SQL runs)
bq-er validate --config my_config.yml

# Preview generated SQL without executing
bq-er preview-sql --config my_config.yml --tier exact --stage all

# Dry run (generates full pipeline SQL plan)
bq-er run --config my_config.yml --dry-run
```

```python
# Python API preview
pipeline = Pipeline(config)
violations = pipeline.validate()    # Compile-time checks
plan = pipeline.plan()
print(plan.preview())               # See all SQL
```

### Step 5: Run the Pipeline

```python
# Local testing with DuckDB (no BigQuery needed)
from bq_entity_resolution.backends.duckdb import DuckDBBackend
result = pipeline.run(backend=DuckDBBackend())

# Production BigQuery
from bq_entity_resolution.backends.bigquery import BigQueryBackend
backend = BigQueryBackend(project="my-project")
result = pipeline.run(backend=backend)

# With crash recovery (resume from checkpoint on failure)
from bq_entity_resolution.watermark.checkpoint import CheckpointManager
checkpoint = CheckpointManager(backend, "my-project.er_meta.pipeline_checkpoints")
result = pipeline.run(backend=backend, checkpoint_manager=checkpoint, resume=True)

# With progress tracking
def on_progress(stage, idx, total, status):
    print(f"[{idx+1}/{total}] {stage}: {status}")

result = pipeline.run(backend=backend, on_progress=on_progress)
```

### Step 6: Inspect Results

```sql
-- Gold output: resolved entities with canonical records
SELECT * FROM `my-project.er_gold.customer_dedup_resolved_entities` LIMIT 100;

-- Match pairs with confidence scores
SELECT * FROM `my-project.er_silver.customer_dedup_all_matches` LIMIT 100;

-- Cluster assignments
SELECT * FROM `my-project.er_silver.customer_dedup_clusters` LIMIT 100;
```

---

## Kubernetes / Argo Workflows Deployment

### Docker

```bash
# Build
docker build -t bq-er .

# Run with gcloud credentials
docker run \
  -v ./config:/app/config/user \
  -v ~/.config/gcloud:/root/.config/gcloud:ro \
  bq-er run --config /app/config/user/my_config.yml
```

### Kubernetes with Workload Identity (GKE)

```yaml
# k8s-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: entity-resolution
spec:
  template:
    metadata:
      annotations:
        # Workload Identity: pod gets IAM role automatically
        iam.gke.io/gcp-service-account: er-pipeline@MY_PROJECT.iam.gserviceaccount.com
    spec:
      serviceAccountName: er-pipeline-ksa
      containers:
        - name: er-pipeline
          image: gcr.io/MY_PROJECT/bq-er:latest
          args:
            - run
            - --config
            - /app/config/user/config.yml
          env:
            - name: BQ_PROJECT
              value: "my-gcp-project"
          volumeMounts:
            - name: config
              mountPath: /app/config/user
      volumes:
        - name: config
          configMap:
            name: er-pipeline-config
      restartPolicy: Never
  backoffLimit: 2   # Retry on failure (checkpoint/resume handles idempotency)
```

### Argo Workflows

```yaml
# argo-workflow.yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: entity-resolution
spec:
  entrypoint: run-pipeline
  templates:
    - name: run-pipeline
      container:
        image: gcr.io/MY_PROJECT/bq-er:latest
        args:
          - run
          - --config
          - /app/config/user/config.yml
          - --full-refresh
        env:
          - name: BQ_PROJECT
            value: "my-gcp-project"
          - name: GOOGLE_APPLICATION_CREDENTIALS
            value: /secrets/sa-key.json
        volumeMounts:
          - name: config
            mountPath: /app/config/user
          - name: gcp-credentials
            mountPath: /secrets
            readOnly: true
      volumes:
        - name: config
          configMap:
            name: er-pipeline-config
        - name: gcp-credentials
          secret:
            secretName: gcp-sa-key
```

### Credential Loading Priority

The pipeline follows Google's Application Default Credentials (ADC):

| Priority | Method | Environment |
|----------|--------|-------------|
| 1 | `GOOGLE_APPLICATION_CREDENTIALS` env var | Docker, CI/CD, Argo |
| 2 | Workload Identity | GKE pods |
| 3 | `gcloud auth application-default login` | Developer workstation |
| 4 | Compute Engine metadata | GCE VMs |

---

## Project Structure

```
src/bq_entity_resolution/
  config/          Pydantic v2 schema (28 models), YAML loader, 16 presets, 57 roles, 29 validators, 19 entity types
  config/models/   7 domain-specific config sub-modules (blocking, features, matching, etc.)
  sql/builders/    23 Python SQL builder modules (type-safe, testable)
  sql/             SQLExpression wrapper (sqlglot), utilities
  features/        Feature function registry (104 functions via @register)
  matching/        Comparison registry (54 functions), F-S parameters, active learning
  blocking/        Blocking key validation, LSH bucket logic
  reconciliation/  Clustering descriptions, canonical output logic
  embeddings/      BigQuery ML embedding generation + LSH
  watermark/       Watermark tracking + checkpoint/resume
  compound/        Compound record detection + splitting (family names, slash-separated)
  stages/          15 Stage classes in focused modules (clustering, canonical_index, gold_output, bqml, etc.)
  pipeline/        Pipeline, StageDAG, Plan, Executor, Validator, Quality Gates
  backends/        Pluggable backends (BigQuery, DuckDB, BQ Emulator)
  profiling/       Column profiling + weight sensitivity analysis
  monitoring/      Structured logging + metrics
  clients/         BigQuery client wrapper with retries
  tools/           Cursor profiler for incremental processing
  naming.py        Centralized table naming
  columns.py       Centralized column name constants
  __main__.py      Click CLI entry point (13 commands)
```

## Key Patterns

1. **Registry** — `@register("name")` adds feature/comparison functions. Adding a function = 1 decorator + 1 YAML line.
2. **Config-driven** — All behavior from YAML. Pydantic v2 validates at load time. Env vars: `${VAR}`, `${VAR:-default}`.
3. **Centralized naming** — ALL table names via `naming.py`. ALL column names via `columns.py`.
4. **Builder pattern** — Frozen `@dataclass` params + `build_*()` → `SQLExpression`. No templates.
5. **Plan-Execute split** — `plan()` generates SQL, `run()` executes. Enables preview/testing.
6. **Checkpoint/resume** — `CheckpointManager` persists stage completion. Pipeline auto-resumes from last completed stage.
7. **Stage DAG** — Stages declare inputs/outputs as `TableRef`. `StageDAG` resolves execution order via topological sort.
8. **Incremental processing** — Composite ordered watermarks, drain mode, canonical_index persistence, cross-batch blocking.

## Adding New Things

| What | Where | How |
|------|-------|-----|
| Feature function | `features/<domain>.py` | Add `@register("name")` function |
| Comparison function | `matching/comparisons/<domain>.py` | Add `@register("name")` function |
| Matching tier | YAML config | Add block under `matching_tiers:` |
| Source table | YAML config | Add block under `sources:` |
| Column | YAML config | Add to source's `columns:` list |
| Blocking key | YAML config | Add to `feature_engineering.blocking_keys:` |
| SQL builder | `sql/builders/` | Frozen `@dataclass` + `build_*()` function |
| Pipeline stage | `stages/` | Subclass `Stage`, implement `plan()` |
| Backend | `backends/` | Implement `Backend` protocol |
| Compound pattern | `compound/patterns.py` | Add regex pattern to `COMPOUND_PATTERNS` |

## Important Files to Read First

1. `config/schema.py` — Complete YAML schema (30+ Pydantic models)
2. `pipeline/pipeline.py` — Pipeline class (main entry point)
3. `config/presets/` — quick_config() and 16 domain-specific presets (person, insurance, telecom, logistics, retail, etc.)
4. `config/roles.py` — 57 column roles → auto-feature/blocking/comparison mapping (10 industry role sets)
5. `features/registry.py` — All 104 feature functions (barrel import from 14 sub-modules)
6. `matching/comparisons/__init__.py` — All 54 comparison functions (barrel import from 7 sub-modules)
7. `naming.py` — All table names
8. `columns.py` — All column name constants
9. `config/examples/` — 20 example configs (minimal to production-grade, covering 10+ industries)

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `BQ_PROJECT` | Yes (production) | — | GCP project ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | ADC | Service account key path |
| `GOLD_DATASET` | No | `er_gold` | Override gold dataset name |
| `BQ_LOCATION` | No | `US` | BigQuery dataset location |

## Code Style

- **ruff** (E, F, I, N, W, UP rules, line length 100)
- **mypy** strict mode
- `from __future__ import annotations` everywhere
- `**_: Any` on registry functions for forward compatibility
- All SQL builder dataclasses use `frozen=True`
- All builder functions return `SQLExpression`

## Pipeline Execution Order

```
watermark read → stage sources (bronze) → engineer features (silver) →
embeddings + LSH (if enabled) → create UDFs → estimate F-S parameters (if configured) →
init matches table → init canonical_index (if incremental) →
tier 1..N (blocking → matching → accumulate) →
clustering → canonical_index populate (if incremental) →
gold output → cluster quality metrics →
active learning review queues (if configured) →
watermark advance → metrics
```

## Incremental Processing (15B-record scale)

```yaml
incremental:
  enabled: true
  cursor_columns: [source_date, source_policyid]  # Composite watermark
  cursor_mode: ordered       # Tuple comparison: (date, id) > (wm_date, wm_id)
  batch_size: 5_000_000
  drain_mode: true           # Auto-loop until all records consumed
  drain_max_iterations: 100  # Safety cap
```

Key concepts:
- **Composite ordered watermarks** — Clean batch boundaries even when a single date has 28M+ records
- **Drain mode** — `--drain` flag or `drain_mode: true` loops until source exhausted
- **Cross-batch blocking** — New records matched against canonical_index (all historical entities)
- **Canonical index** — Accumulates all entities with cluster_ids across batches
- **Cursor profiler** — `bq-er profile-cursors` recommends the best secondary cursor column
- **Hash cursor fallback** — `FARM_FINGERPRINT(col) MOD N` when no natural secondary cursor exists

See `docs/incremental_processing.md` for full guide and `config/examples/incremental_processing.yml` for example.

## Known Limitations

- `threshold.method`: only `sum` and `fellegi_sunter` implemented
- Comparison functions hardcode `l.` / `r.` table aliases
- Nickname mapping hardcoded in Python (not externally configurable)
- Jaro-Winkler requires BigQuery JS UDF (auto-created)
- Connected components and EM use BQ scripting — DuckDB interprets via Python loop
- DuckDB SQL adaptation uses regex rewriting (may miss edge cases)
- PII redaction in SQL audit logs (implemented in executor via `_redact_sql()`; runtime logs not yet covered)
- Distributed locking for concurrent runs (implemented in `pipeline/lock.py`)
- Audit trail is optional (should be mandatory for regulated industries)

See `docs/TUNING.md` for output schema reference and common tuning remediation steps.

## Scale Guidelines

| Records | Recommended Config |
|---------|-------------------|
| < 100K | Default settings, DuckDB for testing |
| 100K - 1M | Add `candidate_limit: 200` to blocking paths |
| 1M - 10M | Enable clustering on all tables, set `batch_size` |
| 10M - 100M | Partition staging tables, add partition cursors, tune blocking keys |
| 100M+ | Multi-dimensional watermarks, partition pruning, cost ceiling |

```yaml
# High-volume config additions
scale:
  max_bytes_billed: 10000000000    # 10 GB safety cap
  staging_partition_by: "DATE(source_updated_at)"
  staging_clustering: [entity_uid, source_name]

incremental:
  partition_cursors:
    - column: state
      strategy: equality
      value: "${TARGET_STATE}"     # Process one state at a time
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ConfigurationError: Environment variable '${BQ_PROJECT}' is not set` | Missing env var | `export BQ_PROJECT=your-project` |
| `Pipeline validation failed: blocking key 'bk_email' undefined` | Blocking key not in feature_engineering | Add to `feature_engineering.blocking_keys` |
| `Stage 'clustering' failed: WHILE loop exceeded max iterations` | Cluster graph too dense | Increase `clustering.max_iterations` or tighten blocking |
| Candidate pair explosion (>100M pairs) | Blocking key too coarse | Add more blocking keys or reduce `candidate_limit` |
| DuckDB: `Catalog Error: Scalar Function SOUNDEX does not exist` | Missing DuckDB shims | Use `DuckDBBackend()` (not raw duckdb.connect()) |
| `DefaultCredentialsError` | No BigQuery auth | Run `gcloud auth application-default login` |

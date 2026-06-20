# Getting Started with bq-entity-resolution

A 15-minute tutorial to run your first entity resolution pipeline.

By the end of this guide you will have installed the library, run a deduplication
pipeline locally with DuckDB, exported a YAML configuration for customization,
and understood the output tables.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Quick Start -- 10 Lines to a Pipeline](#2-quick-start----10-lines-to-a-pipeline)
3. [Your First Configuration File](#3-your-first-configuration-file)
4. [Understanding Results](#4-understanding-results)
5. [CLI Tools](#5-cli-tools)
6. [Auto-Discovery with Pipeline.from_table()](#6-auto-discovery-with-pipelinefrom_table)
7. [Progress Tracking](#7-progress-tracking)
8. [Switching from DuckDB to BigQuery](#8-switching-from-duckdb-to-bigquery)
9. [Next Steps](#9-next-steps)

---

## 1. Installation

### Local development (no cloud credentials required)

Install with the `[local]` extra to get the DuckDB backend for testing
on your laptop -- no BigQuery project or Google credentials needed:

```bash
pip install "bq-entity-resolution[local]"
```

### Production (BigQuery)

For production workloads against BigQuery:

```bash
pip install bq-entity-resolution
```

You will also need to authenticate with Google Cloud:

```bash
# Option A: Developer workstation
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# Option B: Service account (CI/CD, Docker)
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

The minimum BigQuery IAM role required is `roles/bigquery.dataEditor` plus
`roles/bigquery.jobUser`.

### Verify the installation

```bash
python -c "from bq_entity_resolution import __version__; print(__version__)"
# Should print: 0.2.0
```

---

## 2. Quick Start -- 10 Lines to a Pipeline

The fastest path from zero to a running pipeline uses `quick_config()` and
the DuckDB backend. No YAML files, no cloud credentials.

```python
from bq_entity_resolution import Pipeline, quick_config
from bq_entity_resolution.backends.duckdb import DuckDBBackend

# 1. Generate a complete config from minimal inputs
config = quick_config(
    bq_project="my-project",
    source_table="my-project.raw.customers",
    columns=["first_name", "last_name", "email", "phone"],
)

# 2. Build the pipeline
pipeline = Pipeline(config)

# 3. Preview the execution plan (all SQL, no execution)
plan = pipeline.plan()
print(plan.preview())

# 4. Run locally with DuckDB
result = pipeline.run(backend=DuckDBBackend())

# 5. Check the result
print(f"Status: {result.status}")
print(f"Stages completed: {result.completed_stages}")
print(f"Duration: {result.duration_seconds:.1f}s")
```

### What just happened?

`quick_config()` auto-detected semantic roles from the column names:

| Column        | Detected Role   | Generated Features                         |
|---------------|-----------------|--------------------------------------------|
| `first_name`  | `first_name`    | `name_clean`, `soundex`, `metaphone`       |
| `last_name`   | `last_name`     | `name_clean`, `soundex`, `metaphone`       |
| `email`       | `email`         | `lower_trim`, `email_domain`, `local_part` |
| `phone`       | `phone`         | `phone_standardize`, `phone_last_four`     |

It then generated blocking keys, comparison methods, and two matching tiers
(exact and fuzzy) -- a complete pipeline configuration from four column names.

---

## 3. Your First Configuration File

Auto-generated configs are a starting point. For production use you will want
to export to YAML, review the generated logic, and customize it.

### Export to YAML

```python
from bq_entity_resolution import quick_config

config = quick_config(
    bq_project="my-project",
    source_table="my-project.raw.customers",
    columns=["first_name", "last_name", "email", "phone"],
)

# Export to a YAML file
yaml_str = config.to_yaml()
with open("my_config.yml", "w") as f:
    f.write(yaml_str)

print("Config written to my_config.yml")
```

### Customize the YAML

Open `my_config.yml` in your editor. The key sections are:

```yaml
# -- Project: where output tables are created ----------------------------
project:
  name: customers                   # Pipeline name (used in table names)
  bq_project: "my-project"         # GCP project ID
  bq_dataset_bronze: er_bronze     # Staging tables (raw data intake)
  bq_dataset_silver: er_silver     # Feature and match tables
  bq_dataset_gold: er_gold         # Final resolved entities

# -- Sources: what tables to deduplicate ----------------------------------
sources:
  - name: customers
    table: "my-project.raw.customers"
    unique_key: id                  # Primary key column
    updated_at: updated_at          # Timestamp for incremental processing
    columns:
      - name: first_name
        role: first_name            # Semantic role drives auto-features
      - name: last_name
        role: last_name
      - name: email
        role: email
      - name: phone
        role: phone

# -- Feature Engineering: how columns are cleaned/transformed -------------
feature_engineering:
  name_features:
    features:
      - name: first_name_clean
        function: name_clean        # Built-in: trims, uppercases, strips accents
        input: first_name
      - name: last_name_clean
        function: name_clean
        input: last_name
      - name: email_clean
        function: lower_trim
        input: email
      - name: phone_std
        function: phone_standardize # Built-in: strips non-digits
        input: phone

  blocking_keys:
    - name: bk_email
      function: farm_fingerprint
      inputs: [email_clean]
    - name: bk_phone
      function: farm_fingerprint
      inputs: [phone_std]

# -- Matching Tiers: cascading match strategies ---------------------------
matching_tiers:
  - name: exact
    description: "High-confidence exact matches"
    blocking:
      paths:
        - keys: [bk_email]
    comparisons:
      - left: email_clean
        right: email_clean
        method: exact               # Built-in: exact string equality
        weight: 5.0
      - left: last_name_clean
        right: last_name_clean
        method: levenshtein          # Built-in: edit distance
        params: { max_distance: 2 }
        weight: 3.0
    threshold:
      min_score: 5.0                # Pairs scoring >= 5.0 are matches

  - name: fuzzy
    description: "Fuzzy probabilistic matches"
    blocking:
      paths:
        - keys: [bk_phone]
    comparisons:
      - left: first_name_clean
        right: first_name_clean
        method: levenshtein_normalized
        params: { threshold: 0.8 }
        weight: 3.0
      - left: last_name_clean
        right: last_name_clean
        method: levenshtein_normalized
        params: { threshold: 0.8 }
        weight: 3.0
    threshold:
      min_score: 4.0
```

### Reload and run

```python
from bq_entity_resolution import Pipeline, load_config
from bq_entity_resolution.backends.duckdb import DuckDBBackend

# Load the customized YAML
config = load_config("my_config.yml")

# Build and run
pipeline = Pipeline(config)
result = pipeline.run(backend=DuckDBBackend())
```

### Environment variable support

YAML configs support `${VAR}` and `${VAR:-default}` syntax for environment
variables. This keeps secrets out of config files:

```yaml
project:
  bq_project: "${BQ_PROJECT}"
  bq_location: "${BQ_LOCATION:-US}"
```

```bash
export BQ_PROJECT=my-gcp-project
bq-er run --config my_config.yml
```

---

## 4. Understanding Results

### Pipeline output tables

The pipeline creates tables across three datasets (bronze, silver, gold):

| Dataset  | Table                          | Contents                                                |
|----------|--------------------------------|---------------------------------------------------------|
| Bronze   | `staged_{source_name}`         | Cleaned copy of source data with entity UIDs            |
| Silver   | `featured`                     | All engineered features (cleaned names, blocking keys)  |
| Silver   | `candidates_{tier_name}`       | Candidate pairs generated by blocking                   |
| Silver   | `matches_{tier_name}`          | Scored match pairs that passed the threshold            |
| Silver   | `all_matched_pairs`            | Accumulated matches across all tiers                    |
| Silver   | `entity_clusters`              | Cluster assignments (which records belong together)     |
| Gold     | `resolved_entities`            | Final output: one row per resolved entity               |

### Reading the gold output

The `resolved_entities` table is the primary output. Each row represents a
resolved entity with a canonical (best) record selected from the cluster:

```sql
SELECT
    entity_id,          -- Unique entity identifier (e.g., "CUST_00001")
    cluster_id,         -- Internal cluster ID
    cluster_size,       -- Number of source records in this entity
    source_name,        -- Which source table this canonical record came from
    first_name_clean,   -- Canonical first name
    last_name_clean,    -- Canonical last name
    email_clean,        -- Canonical email
    phone_std           -- Canonical phone
FROM `my-project.er_gold.customers_resolved_entities`
LIMIT 100;
```

### Reading match pairs

To understand why two records were linked, query the match tables:

```sql
SELECT
    left_entity_uid,
    right_entity_uid,
    match_score,
    tier_name
FROM `my-project.er_silver.customers_all_matched_pairs`
ORDER BY match_score DESC
LIMIT 100;
```

### Reading cluster assignments

To see which source records belong to the same entity:

```sql
SELECT
    entity_uid,
    cluster_id,
    source_name,
    source_key
FROM `my-project.er_silver.customers_entity_clusters`
ORDER BY cluster_id
LIMIT 100;
```

### Inspecting the PipelineResult object

When running from Python, the `PipelineResult` object provides structured
information about the run:

```python
result = pipeline.run(backend=DuckDBBackend())

# Overall status
print(f"Success: {result.success}")
print(f"Status: {result.status}")          # "success" or "error"
print(f"Duration: {result.duration_seconds:.1f}s")

# Per-stage results
for stage_result in result.stage_results:
    print(
        f"  {stage_result.stage_name}: "
        f"{'OK' if stage_result.success else 'FAILED'} "
        f"({stage_result.duration_seconds:.1f}s, "
        f"{stage_result.sql_count} SQL statements)"
    )

# SQL audit trail
for entry in result.sql_log:
    print(f"  [{entry.get('stage')}] {entry.get('sql', '')[:80]}...")
```

---

## 5. CLI Tools

The `bq-er` CLI provides commands for validation, preview, and execution
without writing Python code.

### Validate a config

Catches errors before any SQL runs -- missing columns, undefined blocking keys,
invalid feature functions:

```bash
bq-er validate --config my_config.yml
```

### Preview generated SQL

See every SQL statement the pipeline would execute, without running anything:

```bash
# Preview all stages for a specific tier
bq-er preview-sql --config my_config.yml --tier exact --stage all

# Preview just the blocking stage
bq-er preview-sql --config my_config.yml --tier exact --stage blocking
```

### Dry run

Generates the full pipeline plan and shows stage counts, but does not execute:

```bash
bq-er run --config my_config.yml --dry-run
```

### Full execution

```bash
# Standard run (incremental, reads watermark)
bq-er run --config my_config.yml

# Full refresh (ignore watermarks, reprocess everything)
bq-er run --config my_config.yml --full-refresh

# Drain mode (loop through all pending batches)
bq-er run --config my_config.yml --drain
```

### Describe a pipeline

Print a human-readable summary of the pipeline structure:

```bash
bq-er describe --config my_config.yml
```

### Profile source data

Analyze column distributions and blocking key selectivity:

```bash
bq-er profile --config my_config.yml
```

---

## 6. Auto-Discovery with Pipeline.from_table()

If your data is already in BigQuery, `Pipeline.from_table()` can introspect
the table schema, detect column roles, and generate the full pipeline
configuration automatically:

```python
from bq_entity_resolution import Pipeline
from bq_entity_resolution.backends.bigquery import BigQueryBackend

backend = BigQueryBackend(project="my-project")

# Auto-discover columns and generate pipeline
pipeline = Pipeline.from_table(
    "my-project.raw.customers",
    backend=backend,
)

# Inspect what was generated
print(pipeline.config.to_yaml())

# Run it
result = pipeline.run(backend=backend)
```

You can override specific role assignments if auto-detection gets a column
wrong:

```python
pipeline = Pipeline.from_table(
    "my-project.raw.customers",
    backend=backend,
    column_roles={
        "cust_nm": "last_name",      # Auto-detection would miss this
        "dob_dt": "date_of_birth",   # Non-standard column name
    },
)
```

### Checking role detection

To see what role the system would assign to a column name without building
a full pipeline:

```python
from bq_entity_resolution import detect_role

columns = ["first_name", "email", "policy_number", "cust_addr"]
for col in columns:
    print(f"{col} -> {detect_role(col)}")

# first_name -> first_name
# email -> email
# policy_number -> policy_number
# cust_addr -> None  (would need explicit role assignment)
```

---

## 7. Progress Tracking

For long-running pipelines, use a progress callback to monitor execution:

```python
from bq_entity_resolution import Pipeline, quick_config
from bq_entity_resolution.backends.duckdb import DuckDBBackend

config = quick_config(
    bq_project="my-project",
    source_table="my-project.raw.customers",
    columns=["first_name", "last_name", "email", "phone"],
)

def on_progress(stage_name: str, stage_index: int, total_stages: int, status: str):
    pct = (stage_index + 1) / total_stages * 100
    print(f"[{pct:5.1f}%] {stage_name}: {status}")

pipeline = Pipeline(config)
result = pipeline.run(
    backend=DuckDBBackend(),
    on_progress=on_progress,
)
```

Example output:

```
[  8.3%] staging_customers: running
[ 16.7%] feature_engineering: running
[ 25.0%] create_udfs: running
[ 33.3%] init_matches: running
[ 41.7%] blocking_exact: running
[ 50.0%] matching_exact: running
[ 58.3%] accumulate_exact: running
[ 66.7%] blocking_fuzzy: running
[ 75.0%] matching_fuzzy: running
[ 83.3%] accumulate_fuzzy: running
[ 91.7%] clustering: running
[100.0%] gold_output: running
```

The `ProgressCallback` protocol accepts four arguments:

| Argument       | Type  | Description                                        |
|----------------|-------|----------------------------------------------------|
| `stage_name`   | `str` | Name of the current stage                          |
| `stage_index`  | `int` | Zero-based index of the current stage              |
| `total_stages` | `int` | Total number of stages in the plan                 |
| `status`       | `str` | Current status (`"running"`, `"complete"`, etc.)   |

---

## 8. Switching from DuckDB to BigQuery

The only change needed to move from local testing to production BigQuery is
the backend object. The config, pipeline, and all generated SQL remain the same.

### DuckDB (local testing)

```python
from bq_entity_resolution.backends.duckdb import DuckDBBackend

result = pipeline.run(backend=DuckDBBackend())
```

### BigQuery (production)

```python
from bq_entity_resolution.backends.bigquery import BigQueryBackend

backend = BigQueryBackend(project="my-gcp-project")
result = pipeline.run(backend=backend)
```

### BigQuery with checkpoint/resume

For production workloads, enable checkpoint persistence so the pipeline can
resume from the last completed stage after a crash:

```python
from bq_entity_resolution.backends.bigquery import BigQueryBackend
from bq_entity_resolution.watermark.checkpoint import CheckpointManager

backend = BigQueryBackend(project="my-project")
checkpoint = CheckpointManager(
    backend,
    "my-project.er_meta.pipeline_checkpoints",
)

result = pipeline.run(
    backend=backend,
    checkpoint_manager=checkpoint,
    resume=True,             # Auto-resume from last incomplete run
)
```

### BigQuery with a cost ceiling

Set `max_bytes_billed` to prevent runaway queries:

```yaml
scale:
  max_bytes_billed: 10000000000   # 10 GB safety cap
```

---

## 9. Next Steps

### Learn more

| Resource | Description |
|----------|-------------|
| [CONFIGURATION.md](CONFIGURATION.md) | Full reference for every YAML option |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, stage DAG, SQL builders |
| [incremental_processing.md](incremental_processing.md) | Composite watermarks, drain mode, canonical index |

### Example configs

The `config/examples/` directory contains complete, annotated configurations
for common use cases:

| File | Use Case |
|------|----------|
| `minimal_dedup.yml` | Simplest possible config: one source, one tier |
| `customer_dedup.yml` | Customer deduplication with name, address, phone, email |
| `person_linkage.yml` | Cross-source record linkage (multiple source tables) |
| `probabilistic_matching.yml` | Fellegi-Sunter probabilistic matching with EM |
| `insurance_entity.yml` | Insurance domain: policies, claims, SSN |
| `enrichment_geocoding.yml` | Census geocoding enrichment joins |
| `compound_detection.yml` | Compound record splitting (family names, slash-separated) |
| `incremental_processing.yml` | Composite watermarks and drain mode |

### Presets for common domains

Instead of writing YAML from scratch, use a domain preset that generates a
complete configuration from column-role mappings:

```python
from bq_entity_resolution import (
    person_dedup_preset,
    person_linkage_preset,
    business_dedup_preset,
    insurance_dedup_preset,
    healthcare_patient_preset,
    financial_transaction_preset,
)

# Example: insurance deduplication
config = insurance_dedup_preset(
    bq_project="my-project",
    source_table="my-project.claims.records",
    columns={
        "first_name": "first_name",
        "last_name": "last_name",
        "dob": "date_of_birth",
        "ssn": "ssn",
        "policy_num": "policy_number",
        "claim_num": "claim_number",
    },
)
```

Available presets:

| Preset | Domain | Key Roles |
|--------|--------|-----------|
| `quick_config()` | Any | Auto-detects from column names |
| `person_dedup_preset()` | Person dedup | first/last name, DOB, email, phone, SSN |
| `person_linkage_preset()` | Cross-source linkage | Same as person, multiple sources |
| `business_dedup_preset()` | Business/company | company_name, EIN, address |
| `insurance_dedup_preset()` | Insurance | policy/claim number, insured name, DOB |
| `healthcare_patient_preset()` | Healthcare | NPI, MRN, patient name, DOB |
| `financial_transaction_preset()` | Financial | account/routing number, amount, date |

### Extending the pipeline

Register custom feature functions or comparison methods:

```python
from bq_entity_resolution import register_feature, register_comparison

@register_feature("my_custom_clean")
def my_custom_clean(inputs, **_):
    return f"REGEXP_REPLACE(UPPER(TRIM({inputs[0]})), r'[^A-Z0-9]', '')"

@register_comparison("weighted_exact")
def weighted_exact(left, right, params=None, **_):
    boost = (params or {}).get("boost", 1.0)
    return f"CASE WHEN {left} = {right} THEN {boost} ELSE 0.0 END"
```

These are immediately available in YAML configs:

```yaml
feature_engineering:
  name_features:
    features:
      - name: id_clean
        function: my_custom_clean
        input: raw_id

matching_tiers:
  - name: exact
    comparisons:
      - left: id_clean
        right: id_clean
        method: weighted_exact
        params: { boost: 10.0 }
        weight: 10.0
```

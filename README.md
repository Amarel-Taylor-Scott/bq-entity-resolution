# bq-entity-resolution

[![PyPI version](https://img.shields.io/pypi/v/bq-entity-resolution.svg)](https://pypi.org/project/bq-entity-resolution/)
[![Python](https://img.shields.io/pypi/pyversions/bq-entity-resolution.svg)](https://pypi.org/project/bq-entity-resolution/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/your-org/bq-entity-resolution/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-3894%20passing%2C%2024%20skipped-brightgreen.svg)]()

A configurable, multi-tier entity resolution pipeline for Google BigQuery. Python handles configuration and SQL generation; BigQuery executes all data processing. No data leaves the warehouse.

## New: Leaf-Based Resolution

Every other entity-resolution tool — Splink, dedupe, recordlinkage, and the classic single-pass pipeline — compares records in **one undifferentiated space**. That has two costs: you can't tune the comparison of *fresh duplicates* differently from *new-record-to-existing-entity* attachment, and once two canonical entities have been split, **they stay split forever** — there is no re-resolution path.

**Leaf-based resolution** replaces the single pass with a generic **N×M comparison model**. A *leaf* compares an ordered pair of *partitions* of the entity space (`left × right`) and owns its **own blocking, matching tiers, thresholds, and heuristics**. The three incremental strata become first-class presets:

| Leaf preset | Compares | Purpose | Tuned heuristics |
|-------------|----------|---------|------------------|
| `new × new` | this batch vs itself | intra-batch dedup of same-load typos | tightest thresholds, full blocking, symmetric self-join |
| `new × old` | this batch vs canonical store | attach new records to resolved entities | exact-key short-circuit (email/phone/national-id), reuse canonical blocking keys, entity-level features |
| `old × old` | canonical vs canonical | **periodic re-resolution / merge repair** | schedule-gated, conservative thresholds, `touched_only` scoping |

Leaves are just *presets* — the underlying model is fully generic, so you can define arbitrary partitions (`source_crm × source_erp`, `region_us × region_eu`, `high_trust × low_trust`, time-window × time-window). Each leaf emits tagged candidate pairs that **`UNION ALL` into one pair graph and feed a single clustering step**, so connected-components clustering stays leaf-blind and untouched.

The `old × old` repair leaf is the headline capability no single-pass tool offers: when later data or a config change reveals that two existing canonicals should merge, a scheduled repair leaf re-compares them and emits the merge — instead of leaving them split forever.

### Status — honest

This is shipping in stages, presented exactly as far as it has landed:

- **Design** — full design doc: [`docs/leaf-resolution-design.md`](docs/leaf-resolution-design.md) (abstraction, SQL shape, executor flow, heuristics catalogue, migration, test plan, phasing).
- **Working prototype** — [`examples/leaf_prototype.py`](examples/leaf_prototype.py), a standalone DuckDB script (no BigQuery needed) that runs `new×new` / `new×old` / `old×old` end to end and demonstrates the `old×old` repair leaf merging two canonicals that a single-pass pipeline leaves permanently split:

  ```bash
  python examples/leaf_prototype.py
  # ── leaf new_x_new  [new × new] — intra-batch dedup
  # ── leaf new_x_old  [new × canonical] — attach to canonical store (short-circuit)
  # ── leaf old_x_old  [old_touched × canonical] — merge repair
  # ══ resolved clusters (4 entities from 8 records) ══
  #    (was C1,C3)  101:Robert Lee + 103:Bob Lee + 203:Roberto Lee   ← repair merged C1+C3
  ```

- **Config layer (landed)** — Pydantic v2 models in [`config/models/leaves.py`](src/bq_entity_resolution/config/models/leaves.py) (`PartitionDef`, `LeafDef`, `LeafHeuristics`, preset synthesis with back-compat), covered by [`tests/unit/config/test_leaves.py`](tests/unit/config/test_leaves.py). Configs without a `leaves:` block synthesize the current behaviour, so existing pipelines are byte-identical and unchanged.
- **SQL builder (landed)** — [`sql/builders/leaf.py`](src/bq_entity_resolution/sql/builders/leaf.py): a frozen-dataclass builder (`LeafSQLParams` → `build_leaf_sql()` → `SQLExpression`) that emits each leaf's candidate-pair SQL — partition selection, blocking join, scoring, self-join dedup guard, exact-key short-circuit `UNION ALL`, and `max_pairs` cap. Unit-tested in [`tests/unit/sql/builders/test_leaf.py`](tests/unit/sql/builders/test_leaf.py).
- **Executor stage (landed)** — [`stages/leaf_resolution.py`](src/bq_entity_resolution/stages/leaf_resolution.py) runs every enabled leaf, tags the pairs by leaf name, and unions them into the existing clustering step. Wired into the DAG only when a config opts into `leaves:`, so the historical pipeline is untouched by default.
- **Runnable demo (landed)** — [`examples/leaf_resolution_demo.py`](examples/leaf_resolution_demo.py) drives the *packaged* builder against the DuckDB backend (no BigQuery) end to end:

  ```bash
  python examples/leaf_resolution_demo.py
  # ── leaf new_x_new — 201 ↔ 202 (same email)
  # ── leaf new_x_old — 203 → 101, 204 → 102 (exact-key short-circuit)
  # ── leaf old_x_old — 101 ↔ 103 (merge repair)
  # ══ resolved clusters (4 entities from 8 records) ══
  # OK: 8 records resolved to 4 entities.
  ```

  End-to-end coverage on the DuckDB backend lives in [`tests/integration/test_leaf_resolution_e2e.py`](tests/integration/test_leaf_resolution_e2e.py).

## Why This Tool?

| Feature | bq-entity-resolution | Splink | dedupe | recordlinkage |
|---------|---------------------|--------|--------|----------------|
| **Zero data movement** | All compute in BigQuery | Spark/DuckDB (data leaves warehouse) | Local Python (must export) | Local pandas |
| **Config-driven** | YAML-first, no Python required | Python scripting | Python scripting | Python scripting |
| **Multi-tier matching** | Exact -> fuzzy -> probabilistic cascade | Single pass | Single pass | Single pass |
| **Incremental processing** | Watermarks + cross-batch clustering | Full reprocess | Full reprocess | Full reprocess |
| **Scale** | Billions of records (BigQuery native) | Millions (Spark) | Millions | Thousands |
| **Local testing** | DuckDB backend, no credentials needed | DuckDB | N/A | N/A |
| **Progressive disclosure** | 5-line quick start -> 500-line production | Moderate | Simple | Simple |

## Install

```bash
pip install bq-entity-resolution

# With DuckDB for local testing (no BigQuery credentials needed):
pip install "bq-entity-resolution[local]"

# For development:
pip install -e ".[dev,local]"
```

## Quick Start

### 5-Line Python Config

```python
from bq_entity_resolution import quick_config, Pipeline

config = quick_config(
    bq_project="my-gcp-project",
    source_table="my-gcp-project.raw.customers",
    columns=["first_name", "last_name", "email", "phone"],
)

pipeline = Pipeline(config)
plan = pipeline.plan()
print(plan.preview())  # See all generated SQL
```

### YAML Config

For full control, write a YAML config:

```yaml
project:
  name: customer_dedup
  bq_project: "${BQ_PROJECT}"

sources:
  - name: customers
    table: "${BQ_PROJECT}.raw.customers"
    unique_key: customer_id
    updated_at: updated_at
    columns:
      - name: first_name
      - name: last_name
      - name: email
      - name: phone

feature_engineering:
  name_features:
    features:
      - name: first_name_clean
        function: name_clean
        input: first_name
      - name: last_name_clean
        function: name_clean
        input: last_name
  contact_features:
    features:
      - name: email_lower
        function: lower_trim
        input: email
  blocking_keys:
    - name: bk_last_first
      function: farm_fingerprint_concat
      inputs: [last_name_clean, first_name_clean]

matching_tiers:
  - name: exact_match
    blocking:
      paths:
        - keys: [bk_last_first]
          candidate_limit: 200
    comparisons:
      - left: first_name_clean
        right: first_name_clean
        method: exact
        weight: 3.0
      - left: last_name_clean
        right: last_name_clean
        method: exact
        weight: 3.0
      - left: email_lower
        right: email_lower
        method: exact
        weight: 5.0
    threshold:
      min_score: 6.0
```

### Validate and Preview

```bash
bq-er validate --config my_config.yml
bq-er preview-sql --config my_config.yml --tier exact_match --stage all
```

### Run the Pipeline

```bash
# Full refresh (reprocess everything)
bq-er run --config my_config.yml --full-refresh

# Incremental (uses watermarks)
bq-er run --config my_config.yml

# Dry run (generate SQL without executing)
bq-er run --config my_config.yml --dry-run

# Run specific tiers only
bq-er run --config my_config.yml --tier exact_match --tier fuzzy_name
```

### Local Testing with DuckDB

Run the full pipeline locally without BigQuery credentials:

```python
from bq_entity_resolution import Pipeline, load_config
from bq_entity_resolution.backends.duckdb import DuckDBBackend

config = load_config("my_config.yml")
pipeline = Pipeline(config)
result = pipeline.run(backend=DuckDBBackend())
print(f"Completed: {result.completed_stages}")
```

## Configuration Presets

For common use cases, presets auto-generate features, blocking keys, and comparisons from column roles:

```python
from bq_entity_resolution import person_dedup_preset

config = person_dedup_preset(
    bq_project="my-gcp-project",
    source_table="my-gcp-project.raw.customers",
    columns={
        "first_name": "first_name",
        "last_name": "last_name",
        "date_of_birth": "dob",
        "email": "email",
        "phone": "phone",
    },
)
```

### Multi-Source Record Linkage

Link records across two or more systems:

```python
from bq_entity_resolution import person_linkage_preset

config = person_linkage_preset(
    bq_project="my-gcp-project",
    source_tables=[
        {"name": "crm", "table": "my-gcp-project.raw.crm_contacts"},
        {"name": "erp", "table": "my-gcp-project.raw.erp_customers"},
    ],
    columns={
        "first_name": "first_name",
        "last_name": "last_name",
        "email": "email",
        "phone": "phone",
    },
)
```

Available presets: `quick_config`, `person_dedup_preset`, `person_linkage_preset`, `business_dedup_preset`, `insurance_dedup_preset`, `financial_transaction_preset`, `healthcare_patient_preset`.

## Comparison Pool

Define comparisons once, reference across tiers:

```yaml
comparison_pool:
  email_exact:
    left: email_clean
    right: email_clean
    method: exact
    weight: 5.0
  name_jw:
    left: first_name_clean
    right: first_name_clean
    method: jaro_winkler
    params: { threshold: 0.85 }
    weight: 3.0

matching_tiers:
  - name: exact
    comparisons:
      - ref: email_exact         # Use pool definition
      - ref: name_jw
    threshold: { min_score: 8.0 }
  - name: fuzzy
    comparisons:
      - ref: email_exact
      - ref: name_jw
        weight: 1.5              # Override pool weight for this tier
    threshold: { min_score: 3.0 }
```

## Architecture

```
                    +---------------------------------------------+
                    |               YAML Config                    |
                    |  (sources, features, blocking, tiers)        |
                    +---------------------+-----------------------+
                                          |
                             +------------v------------+
                             |   Pydantic v2 Schema     |
                             |   28 config models       |
                             |   + cross-field checks   |
                             +------------+------------+
                                          |
              +---------------------------v---------------------------+
              |                    Pipeline                           |
              |  (entry point: Pipeline(config).run())                |
              |                                                       |
              |  +----------+  +----------+  +--------------------+  |
              |  | StageDAG |->|  Plan    |->|    Executor        |  |
              |  | (topo    |  | (immut.  |  | (quality gates,    |  |
              |  |  sort)   |  |  SQL)    |  |  checkpoints)      |  |
              |  +----------+  +----------+  +--------------------+  |
              +---------------------------+---------------------------+
                                          |
        +---------------------------------v---------------------------------+
        |                       Stages (10 types)                            |
        |                                                                    |
        |  Staging -> Features -> Blocking -> Matching -> Clustering         |
        |                 TermFreq    (per tier)     GoldOutput              |
        |                                            ActiveLearning          |
        |                                            LabelIngestion          |
        |                                                                    |
        |  Each stage: inputs/outputs -> plan() -> list[SQLExpression]       |
        +---------------------------------+---------------------------------+
                                          |
        +---------------------------------v---------------------------------+
        |               SQL Builders (23 modules, 30 functions)              |
        |                                                                    |
        |  Frozen @dataclass params -> build_*() -> SQLExpression            |
        |  Type-safe, unit-testable, no templates                            |
        +---------------------------------+---------------------------------+
                                          | SQL
        +---------------------------------v---------------------------------+
        |                   Backend (pluggable)                              |
        |                                                                    |
        |  BigQueryBackend  |  DuckDBBackend  |  BQEmulatorBackend           |
        |  (production)     |  (local test)   |  (Docker emulator)           |
        +-------------------------------------------------------------------+
```

## Pipeline Stages

| Stage | Layer | What Happens |
|-------|-------|-------------|
| 1. Watermark Read | Meta | Read cursor positions for incremental load |
| 2. Stage Sources | Bronze | Incremental load from source tables with grace period |
| 3. Feature Engineering | Silver | Compute features, blocking keys, composite keys |
| 4. Term Frequencies | Silver | (Optional) Compute TF statistics for TF-IDF scoring |
| 5. Embeddings + LSH | Silver | (Optional) Generate ML embeddings and LSH buckets |
| 6. Create UDFs | Setup | Create Jaro-Winkler JS UDF if needed |
| 7. Tier Execution | Silver | For each tier: blocking -> comparison -> scoring -> threshold |
| 8. Clustering | Silver | Connected components to assign entity clusters |
| 9. Gold Output | Gold | Elect canonical records, produce resolved_entities |
| 10. Active Learning | Silver | (Optional) Generate review queue for uncertain pairs |
| 11. Watermark Advance | Meta | Update cursor positions on success |

### Scoring Methods

| Method | How It Works | When to Use |
|--------|-------------|-------------|
| `sum` | Weighted sum of binary comparisons. Confidence = score / max_possible. | Simple, interpretable rules |
| `fellegi_sunter` | Log-likelihood ratio scoring with m/u probabilities. Confidence = 2^W / (1 + 2^W). | Probabilistic matching with training data |

### Canonical Record Election

| Method | Strategy |
|--------|----------|
| `completeness` | Record with the most non-null fields (default) |
| `recency` | Most recently updated record |
| `source_priority` | Record from highest-priority source |
| `field_merge` | Golden record assembled per-field from best source |

## Custom Functions

Register your own feature and comparison functions without modifying the package:

```python
from bq_entity_resolution import register_feature, register_comparison

@register_feature("company_suffix_clean")
def company_suffix_clean(inputs, **_):
    """Strip common business suffixes (LLC, Inc, Corp)."""
    col = inputs[0]
    return f"REGEXP_REPLACE(UPPER(TRIM({col})), r'\\b(LLC|INC|CORP|LTD)\\b', '')"

@register_comparison("fuzzy_phone")
def fuzzy_phone(left, right, last_n=7, **_):
    """Match on last N digits of phone numbers."""
    return f"(RIGHT(l.{left}, {last_n}) = RIGHT(r.{right}, {last_n}) AND l.{left} IS NOT NULL)"
```

Then use in YAML:
```yaml
feature_engineering:
  features:
    - name: company_clean
      function: company_suffix_clean
      input: company_name

matching_tiers:
  - name: phone_match
    comparisons:
      - left: phone_clean
        right: phone_clean
        method: fuzzy_phone
        params: { last_n: 7 }
        weight: 3.0
```

## Built-in Functions

### Feature Functions (104)

| Category | Functions |
|----------|-----------|
| Name | `name_clean`, `name_clean_strict`, `first_letter`, `first_n_chars`, `char_length`, `soundex`, `extract_salutation`, `strip_salutation`, `extract_suffix`, `strip_suffix`, `word_count`, `first_word`, `last_word`, `initials`, `strip_business_suffix`, `name_fingerprint`, `sorted_name_tokens`, `sorted_name_fingerprint`, `nickname_canonical`, `nickname_match_key` |
| Entity | `entity_type_classify`, `name_format_detect`, `is_multi_person` |
| Email | `email_is_role_address`, `email_local_part`, `email_domain`, `email_domain_category` |
| Business | `dba_extract`, `dba_normalize`, `business_type_extract`, `business_core_name` |
| Negative Flags | `extract_generational_suffix`, `extract_roman_numeral`, `is_hoa_trust_careof`, `extract_numbered_entity_suffix`, `geographic_qualifier` |
| Address | `address_standardize` (40+ USPS abbreviations), `extract_street_number`, `extract_street_name`, `extract_unit_number` |
| Contact | `phone_standardize` (handles country codes), `phone_area_code`, `phone_last_four`, `email_domain_type` |
| Blocking | `farm_fingerprint`, `farm_fingerprint_concat` |
| Zip/Date | `zip5`, `zip3`, `year_of_date`, `date_to_string` |
| Industry | `policy_number_normalize`, `claim_number_normalize`, `npi_validate`, `mrn_normalize`, and 12 more |
| Geo | `geo_hash`, `lat_lon_bucket`, `geo_region_code` |
| Utility | `upper_trim`, `lower_trim`, `left`, `right`, `coalesce`, `concat`, `nullif_empty`, `identity`, and more |

### Comparison Functions (54)

| Category | Functions |
|----------|-----------|
| Exact | `exact`, `exact_case_insensitive`, `exact_or_null` |
| Edit Distance | `levenshtein`, `levenshtein_normalized`, `levenshtein_score` |
| Jaro-Winkler | `jaro_winkler`, `jaro_winkler_score` (BigQuery JS UDF, auto-created) |
| Phonetic | `soundex_match`, `metaphone_match` |
| Vector | `cosine_similarity`, `cosine_similarity_score` (via `ML.DISTANCE`) |
| Numeric/Date | `numeric_within`, `date_within_days`, `date_within_months` |
| String | `contains`, `starts_with` |
| Token | `token_set_match`, `token_set_score`, `initials_match`, `abbreviation_match`, `dice_coefficient`, `dice_coefficient_score`, `overlap_coefficient`, `overlap_coefficient_score`, `monge_elkan`, `monge_elkan_score`, `token_sort_ratio`, `token_sort_ratio_score` |
| Composite | 9 composite comparison functions |
| Hard Negative | `different`, `null_either`, `length_mismatch` |

## CLI Commands

| Command | Description |
|---------|-------------|
| `bq-er run` | Execute the full pipeline |
| `bq-er validate` | Validate configuration |
| `bq-er preview-sql` | Preview generated SQL for a tier |
| `bq-er estimate-params` | Estimate Fellegi-Sunter m/u parameters |
| `bq-er review-queue` | Generate active learning review queue |
| `bq-er ingest-labels` | Ingest human labels and optionally retrain |
| `bq-er profile` | Profile source columns for weight suggestions |
| `bq-er analyze` | Analyze weight sensitivity |
| `bq-er init` | Generate starter config from source table |
| `bq-er check-env` | Check BigQuery credentials and permissions |
| `bq-er describe` | Describe pipeline configuration |
| `bq-er profile-cursors` | Recommend cursor strategies for incremental processing |
| `bq-er profile-placeholders` | Detect placeholder values in source data |

## Environment Variables

Config values support `${VAR}` and `${VAR:-default}` syntax:

```yaml
project:
  bq_project: "${BQ_PROJECT}"
  bq_dataset_gold: "${GOLD_DATASET:-er_gold}"
```

## Python API

```python
from bq_entity_resolution import Pipeline, load_config

config = load_config("my_config.yml")

# Preview SQL without executing
pipeline = Pipeline(config)
plan = pipeline.plan()
for stage_plan in plan.stages:
    print(f"--- {stage_plan.stage_name} ---")
    for expr in stage_plan.sql_expressions:
        print(expr.render())

# Execute against BigQuery
from bq_entity_resolution.backends.bigquery import BigQueryBackend
backend = BigQueryBackend(project="my-project", location="US")
pipeline.run(backend=backend)

# Execute locally with DuckDB (for testing)
from bq_entity_resolution.backends.duckdb import DuckDBBackend
pipeline.run(backend=DuckDBBackend())
```

## Example Configs

| Config | Description |
|--------|-------------|
| [`minimal_dedup.yml`](config/examples/minimal_dedup.yml) | Simplest possible config (1 source, 1 tier, 2 comparisons) |
| [`customer_dedup.yml`](config/examples/customer_dedup.yml) | 3-tier CRM customer deduplication |
| [`person_linkage.yml`](config/examples/person_linkage.yml) | Cross-source record linkage with comparison pool |
| [`probabilistic_matching.yml`](config/examples/probabilistic_matching.yml) | Fellegi-Sunter with EM training and active learning |
| [`insurance_entity.yml`](config/examples/insurance_entity.yml) | 7-tier insurance entity resolution (production-grade) |
| [`enrichment_geocoding.yml`](config/examples/enrichment_geocoding.yml) | Census geocoding enrichment joins |
| [`compound_detection.yml`](config/examples/compound_detection.yml) | Compound name detection and splitting |
| [`incremental_processing.yml`](config/examples/incremental_processing.yml) | Incremental processing with composite watermarks |
| [`banking_kyc.yml`](config/examples/banking_kyc.yml) | Banking KYC entity resolution |
| [`healthcare_patient.yml`](config/examples/healthcare_patient.yml) | Healthcare patient matching |
| [`advanced_signal_framework.yml`](config/examples/advanced_signal_framework.yml) | Hard positives, severity classes, score banding |

## Development

```bash
pip install -e ".[dev,local]"
python -m pytest tests/ -q               # 3894 passing, 24 skipped, ~60s
python -m ruff check src/ tests/          # lint (matches CI)
python -m mypy src/                       # type check
```

### Project Structure

```
src/bq_entity_resolution/
  config/        Pydantic v2 schema, YAML loader, presets, role mapping, validators
  sql/builders/  23 Python SQL builder modules (type-safe, testable)
  sql/           SQLExpression wrapper (sqlglot-based), SQL utilities
  features/      Feature function registry (104 functions via @register)
  matching/      Comparison registry (54 functions), parameters, active learning
  blocking/      Blocking key validation, LSH bucket logic
  reconciliation/  Clustering strategy descriptions, canonical output logic
  embeddings/    BigQuery ML embedding generation + LSH
  watermark/     Incremental watermark tracking + checkpoint/resume
  stages/        10 Stage classes (composable DAG nodes with inputs/outputs)
  pipeline/      Pipeline, StageDAG, Plan, Executor, Validator, Quality Gates
  backends/      Pluggable backends (BigQuery, DuckDB, BQ Emulator)
  profiling/     Column profiling + weight sensitivity analysis
  monitoring/    Structured logging + metrics
  clients/       BigQuery client wrapper with retries
  naming.py      Centralized table naming (single source of truth)
  columns.py     Centralized column name constants
  constants.py   Shared constants
  exceptions.py  Exception hierarchy
```

### Docker

```bash
docker build -t bq-er .
docker run -v ./config:/app/config/user -v ./secrets:/app/secrets \
  bq-er run --config /app/config/user/my_config.yml
```

## License

MIT

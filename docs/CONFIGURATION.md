# Configuration Reference

All pipeline behavior is driven by a single YAML file validated against Pydantic v2 models at load time. Configuration errors surface immediately — before any SQL is generated or BigQuery resources are consumed.

## Environment Variable Interpolation

Values can reference environment variables:

```yaml
bq_project: "${BQ_PROJECT}"                    # required — fails if unset
bq_dataset_gold: "${GOLD_DATASET:-er_gold}"    # optional — falls back to er_gold
```

## Complete Schema

### `project` (required)

```yaml
project:
  name: my_pipeline                     # Pipeline name (for logging/metrics)
  description: "Customer dedup"         # Optional description
  bq_project: my-gcp-project           # GCP project ID
  bq_dataset_bronze: er_bronze          # Bronze layer dataset (default: er_bronze)
  bq_dataset_silver: er_silver          # Silver layer dataset (default: er_silver)
  bq_dataset_gold: er_gold              # Gold layer dataset (default: er_gold)
  bq_location: US                       # BigQuery location (default: US)
  watermark_dataset: er_meta            # Watermark metadata dataset (default: er_meta)
  udf_dataset: er_udfs                  # UDF storage dataset (default: er_udfs)
```

### `sources` (required, at least 1)

```yaml
sources:
  - name: customers                     # Unique source name (used in table naming)
    table: project.dataset.table        # Fully-qualified BigQuery table
    unique_key: customer_id             # Column that uniquely identifies a record
    updated_at: updated_at              # Cursor column for incremental loads
    partition_column: _PARTITIONDATE    # Optional partition column for pruning
    batch_size: 2000000                 # Max records per incremental batch (default: 2M)
    entity_type_column: entity_type     # Optional column distinguishing entity types
    filter: "status = 'ACTIVE'"         # Optional WHERE clause fragment
    columns:                            # Columns to use in the pipeline
      - name: first_name
        type: STRING                    # BigQuery type (default: STRING)
        role: first_name                # Optional semantic role
        nullable: true                  # Default: true
      - name: last_name
      - name: email
    passthrough_columns:                # Columns to carry through without processing
      - raw_address_line2
      - notes
    joins:                              # Optional supplemental joins
      - table: project.dataset.lookup
        alias: lkp
        on: "src.type_code = lkp.code"
        type: LEFT                      # LEFT or INNER (default: LEFT)
```

### `feature_engineering`

```yaml
feature_engineering:
  name_features:
    enabled: true                       # Default: true
    features:
      - name: first_name_clean          # Output column name
        function: name_clean            # Registered function name
        input: first_name               # Single input column
      - name: full_name
        function: concat                # Multi-input function
        inputs: [first_name, last_name]
        params: {separator: " "}        # Function-specific parameters
      - name: custom_feature
        sql: "UPPER(TRIM(my_col))"      # Raw SQL override (bypasses registry)
        depends_on: [my_col]            # Declare dependencies for validation

  address_features:
    enabled: true
    features:
      - name: addr_std
        function: address_standardize
        input: address_line_1

  contact_features:
    enabled: true
    features:
      - name: phone_std
        function: phone_standardize
        input: phone

  # Dynamic extra groups (no code changes needed)
  extra_groups:
    temporal_features:
      enabled: true
      features:
        - name: birth_year
          function: year_of_date
          input: date_of_birth

  blocking_keys:
    - name: bk_name
      function: farm_fingerprint_concat
      inputs: [last_name_clean, first_name_clean]
    - name: bk_soundex
      function: farm_fingerprint
      inputs: [last_name_soundex]

  composite_keys:
    - name: ck_exact
      function: farm_fingerprint_concat
      inputs: [last_name_clean, first_name_clean, zip5]

  custom_features:
    - name: combined_score
      sql: "COALESCE(score_a, 0) + COALESCE(score_b, 0)"
```

### `embeddings` (optional)

```yaml
embeddings:
  enabled: false                        # Default: false
  model: text-embedding-004             # BigQuery ML embedding model
  source_columns: [first_name_clean, last_name_clean, addr_std]
  concat_separator: " | "              # Separator for concatenating columns
  dimensions: 768                       # Embedding dimensionality
  batch_size: 5000                      # Records per embedding batch
  lsh:
    num_hash_tables: 20                 # Number of LSH hash tables (more = higher recall)
    num_hash_functions_per_table: 8     # Hash functions per table (more = higher precision)
    bucket_column_prefix: lsh_bucket    # Column naming prefix
    projection_seed: 42                 # Seed for reproducible projections
```

### `training` (optional, global default)

Global training configuration for Fellegi-Sunter parameter estimation. Individual tiers can override.

```yaml
training:
  method: em                             # none | em | labeled
  em_max_iterations: 10                  # Max EM iterations (default: 10)
  em_convergence_threshold: 0.001        # Stop when max m/u delta < this (default: 0.001)
  em_sample_size: 100000                 # Candidate pairs to sample for EM (default: 100K)
  em_initial_match_proportion: 0.1       # Prior probability of match for EM init (default: 0.1)
  labeled_pairs_table: proj.ds.labels    # For method: labeled — table with labeled pairs
  parameters_table: proj.ds.params       # Optional — persist learned m/u to this table
```

Training methods:
- **`none`** — Use manual m/u values from comparison levels (default)
- **`em`** — Expectation-Maximization: unsupervised, learns m/u from candidate pair statistics entirely within BigQuery scripting
- **`labeled`** — Supervised: learns m/u from a table of human-labeled pairs (`l_entity_uid STRING, r_entity_uid STRING, is_match BOOL`)

### `matching_tiers` (required)

Tiers execute in order. Each tier processes pairs not yet matched by prior tiers.

```yaml
matching_tiers:
  - name: exact_composite               # Unique tier name (alphanumeric/underscore/dash)
    description: "Exact match on composite key"
    enabled: true                        # Default: true (set false to skip)

    blocking:
      paths:
        - keys: [ck_exact]              # Blocking key columns (must be defined above)
          candidate_limit: 200           # Max candidates per entity per path (default: 200)
          lsh_min_bands: 1              # For LSH paths: min matching bands
        - keys: [bk_name, bk_state]    # Multiple keys = AND condition
          candidate_limit: 500
      cross_batch: true                  # Also match against gold canonicals (default: true)

    comparisons:
      - left: first_name_clean           # Left column (from featured table)
        right: first_name_clean          # Right column (same for self-join)
        method: exact                    # Registered comparison function
        weight: 3.0                      # Score contribution when match (sum scoring)
        params: {}                       # Method-specific parameters

      - left: last_name_clean
        right: last_name_clean
        method: levenshtein
        params: {max_distance: 2}
        weight: 3.0

      - left: phone_std
        right: phone_std
        method: exact
        weight: 5.0

    threshold:
      method: sum                        # sum | fellegi_sunter
      min_score: 8.0                     # Minimum total score to qualify as match

    confidence: 0.99                     # Fixed confidence (omit for auto-calculated)

    hard_negatives:                      # Rules that disqualify candidate pairs
      - left: entity_type
        right: entity_type               # Defaults to same as left if omitted
        method: different                # Comparison function name
        action: disqualify               # disqualify = filter out, penalize = subtract score
      - left: first_name_clean
        method: different
        action: penalize
        penalty: -5.0                    # Score penalty (negative number)
      - sql: "l.ein IS NOT NULL AND r.ein IS NOT NULL AND l.ein != r.ein"
        action: disqualify               # Raw SQL override

    soft_signals:                        # Rules that adjust score
      - left: phone_area_code
        method: exact
        bonus: 1.0                       # Positive = boost, negative = penalty
      - left: email_domain
        method: exact
        bonus: 0.5
      - sql: "l.zip5 = r.zip5"
        bonus: 1.5                       # Raw SQL override
```

### Comparison Levels (Fellegi-Sunter)

For probabilistic matching, comparisons can have multi-level outcomes instead of binary match/no-match. Each level has its own m (probability of this outcome given a true match) and u (probability given a non-match).

```yaml
comparisons:
  - left: first_name_clean
    right: first_name_clean
    method: jaro_winkler                 # Overall method (used for auto binary levels)
    levels:                              # Multi-level outcomes (evaluated top to bottom)
      - label: exact                     # First check: exact match
        method: exact
        m: 0.95                          # P(exact match | true match)
        u: 0.01                          # P(exact match | non-match)
      - label: fuzzy_high                # Second check: close fuzzy match
        method: jaro_winkler
        params: { threshold: 0.9 }
        m: 0.70
        u: 0.05
      - label: fuzzy_low                 # Third check: loose fuzzy match
        method: jaro_winkler
        params: { threshold: 0.7 }
        m: 0.50
        u: 0.15
      - label: else                      # Fallthrough (no method)
        m: 0.05
        u: 0.79
```

Level rules:
- Levels are evaluated top-to-bottom as SQL `CASE WHEN ... THEN ... ELSE ... END`
- The last level should be `label: else` with no method (the fallthrough)
- m/u values can be omitted if a training method (EM or labeled) will estimate them
- When `levels` is omitted, the engine auto-creates binary levels (`match` + `else`)
- m/u must be in [0, 1] when specified

### Fellegi-Sunter Threshold

For probabilistic tiers, use `method: fellegi_sunter`:

```yaml
threshold:
  method: fellegi_sunter
  match_threshold: 6.0                   # Minimum log-likelihood ratio to classify as match
```

Scoring:
- Each comparison level contributes `log2(m/u)` to the total score
- Total score = `log_prior_odds + Σ per-comparison log-weights`
- Confidence = `2^total_score / (1 + 2^total_score)` (posterior match probability)
- Pairs with `total_score >= match_threshold` are classified as matches

### Active Learning (per tier)

Surface uncertain pairs for human review to iteratively improve matching quality.

```yaml
matching_tiers:
  - name: probabilistic_fuzzy
    # ... blocking, comparisons, threshold ...
    active_learning:
      enabled: true                      # Default: false
      queue_size: 500                    # Max pairs in review queue (default: 200)
      uncertainty_window: 0.15           # How close to boundary to consider "uncertain"
      review_queue_table: proj.ds.queue  # Optional custom table name
```

The review queue contains pairs closest to the decision boundary (most uncertain), ranked by uncertainty score. For Fellegi-Sunter tiers, uncertainty = `ABS(match_confidence - 0.5)`. For sum-based tiers, uncertainty = `ABS(total_score - min_score)`.

### Tier-Level Training Override

Individual tiers can override the global training config:

```yaml
training:
  method: em                             # Global: use EM for all F-S tiers

matching_tiers:
  - name: tier_with_em
    threshold:
      method: fellegi_sunter
      match_threshold: 5.0
    # Uses global EM training (inherited)

  - name: tier_with_manual
    training:
      method: none                       # Override: use manual m/u for this tier
    threshold:
      method: fellegi_sunter
      match_threshold: 8.0
    comparisons:
      - left: name_clean
        right: name_clean
        method: exact
        levels:
          - { label: exact, method: exact, m: 0.95, u: 0.08 }
          - { label: else, m: 0.05, u: 0.92 }
```

### `reconciliation`

```yaml
reconciliation:
  strategy: tier_priority                # tier_priority | highest_score | manual_review

  clustering:
    method: connected_components         # connected_components | star | best_match
    max_iterations: 20                   # Safety bound for convergence loop
    min_cluster_confidence: 0.0          # Minimum confidence to include in cluster

  canonical_selection:
    method: completeness                 # completeness | recency | source_priority
    source_priority: [system_a, system_b] # For source_priority method

  output:
    include_match_metadata: true         # Include tier_name, match_score in gold table
    include_passthrough: true            # Include passthrough columns
    entity_id_prefix: ENT               # Prefix for resolved_entity_id
    partition_column: null               # Optional partition column
    cluster_columns: [source_name]       # Optional clustering columns
```

### `incremental`

```yaml
incremental:
  enabled: true                          # Default: true
  grace_period_hours: 48                 # Look back N hours from watermark (catches late data)
  cursor_columns: [updated_at]           # Columns to track watermark position
  batch_size: 2000000                    # Global batch size limit
  full_refresh_on_schema_change: true    # Auto full-refresh if schema changes detected
```

### `monitoring`

```yaml
monitoring:
  log_level: INFO                        # DEBUG | INFO | WARNING | ERROR
  log_format: json                       # json | text
  metrics:
    enabled: true
    destination: bigquery                # bigquery | stdout
  profiling:
    enabled: false
    sample_rate: 0.01
```

## Available Feature Functions

### Name Functions
| Function | Input(s) | Params | Description |
|----------|----------|--------|-------------|
| `name_clean` | 1 | | Uppercase, keep alpha/space/hyphen, collapse whitespace |
| `name_clean_strict` | 1 | | Uppercase, keep only letters, collapse whitespace |
| `first_letter` | 1 | | First character |
| `first_n_chars` | 1 | `length` (default: 3) | First N characters |
| `char_length` | 1 | | String length |
| `soundex` | 1 | | Soundex phonetic code |
| `extract_salutation` | 1 | | Extract MR/MRS/MS/DR/PROF/REV/HON |
| `strip_salutation` | 1 | | Remove salutation prefix |
| `extract_suffix` | 1 | | Extract JR/SR/II/III/IV/ESQ/PHD/MD |
| `strip_suffix` | 1 | | Remove name suffix |
| `word_count` | 1 | | Number of words |
| `first_word` | 1 | | First word |
| `last_word` | 1 | | Last word |
| `initials` | 1 | | First letter of each word (e.g., "JAS") |
| `strip_business_suffix` | 1 | | Remove LLC/INC/CORP/LTD/LP/etc. |
| `name_fingerprint` | 1 | | FARM_FINGERPRINT of alpha-only chars |
| `nickname_canonical` | 1 | | Map Bob->ROBERT, Bill->WILLIAM (70+ pairs) |
| `nickname_match_key` | 1 | | FARM_FINGERPRINT of canonical name |
| `sorted_name_tokens` | 1 | | Sort words alphabetically (catches transpositions) |
| `sorted_name_fingerprint` | 1 | | FARM_FINGERPRINT of sorted tokens |

### Address Functions
| Function | Input(s) | Params | Description |
|----------|----------|--------|-------------|
| `address_standardize` | 1 | | Uppercase + 40+ abbreviations (USPS Pub 28) |
| `extract_street_number` | 1 | | Leading digits |
| `extract_street_name` | 1 | | Street name between number and suffix |
| `extract_unit_number` | 1 | | APT/SUITE/STE/UNIT number |

### Contact Functions
| Function | Input(s) | Params | Description |
|----------|----------|--------|-------------|
| `phone_standardize` | 1 | | Strip non-digits, handle country codes |
| `phone_area_code` | 1 | | First 3 digits of normalized phone |
| `phone_last_four` | 1 | | Last 4 digits |
| `email_domain` | 1 | | Domain after @ (lowercased) |
| `email_local_part` | 1 | | Part before @ (lowercased) |
| `email_domain_type` | 1 | | FREE/BUSINESS/NULL classification |

### Utility Functions
| Function | Input(s) | Params | Description |
|----------|----------|--------|-------------|
| `upper_trim` | 1 | | Uppercase + trim |
| `lower_trim` | 1 | | Lowercase + trim |
| `left` | 1 | `length` (default: 5) | Leftmost N chars |
| `right` | 1 | `length` (default: 4) | Rightmost N chars |
| `coalesce` | N | | COALESCE(col1, col2, ...) |
| `concat` | N | `separator` (default: " ") | Concatenate with separator |
| `nullif_empty` | 1 | | Empty string -> NULL |
| `identity` | 1 | | Pass through unchanged |
| `farm_fingerprint` | 1 | | FARM_FINGERPRINT(CAST ... AS STRING) |
| `farm_fingerprint_concat` | N | | FARM_FINGERPRINT of concatenated columns |
| `zip5` | 1 | | First 5 digits of zip |
| `zip3` | 1 | | First 3 digits of zip |
| `year_of_date` | 1 | | EXTRACT(YEAR FROM ...) |
| `date_to_string` | 1 | `fmt` (default: "%Y%m%d") | FORMAT_DATE |

## Available Comparison Functions

| Function | Params | Returns | Description |
|----------|--------|---------|-------------|
| `exact` | | boolean | Exact equality (both non-null) |
| `exact_case_insensitive` | | boolean | Case-insensitive equality |
| `exact_or_null` | | boolean | Equal OR either is null (permissive) |
| `levenshtein` | `max_distance` (2) | boolean | EDIT_DISTANCE <= threshold |
| `levenshtein_normalized` | `threshold` (0.8) | boolean | Normalized similarity >= threshold |
| `levenshtein_score` | | score 0-1 | Normalized edit distance similarity |
| `jaro_winkler` | `threshold` (0.85) | boolean | Jaro-Winkler >= threshold (JS UDF) |
| `jaro_winkler_score` | | score 0-1 | Jaro-Winkler similarity |
| `soundex_match` | | boolean | SOUNDEX codes match |
| `cosine_similarity` | `min_similarity` (0.85) | boolean | ML.DISTANCE cosine <= (1 - min) |
| `cosine_similarity_score` | | score 0-1 | 1 - cosine distance |
| `numeric_within` | `tolerance` (0) | boolean | Numeric values within tolerance |
| `date_within_days` | `days` (0) | boolean | Dates within N days |
| `contains` | | boolean | Either string contains the other |
| `starts_with` | | boolean | Left starts with right |
| `token_set_match` | `min_overlap` (0.5) | boolean | Jaccard similarity of word tokens |
| `token_set_score` | | score 0-1 | Jaccard similarity of word tokens |
| `initials_match` | | boolean | Initials of both names match |
| `abbreviation_match` | | boolean | One is prefix abbreviation of other |
| `different` | | boolean | Values differ (for hard negatives) |
| `null_either` | | boolean | Either value is null |
| `length_mismatch` | `max_diff` (5) | boolean | String lengths differ by > threshold |

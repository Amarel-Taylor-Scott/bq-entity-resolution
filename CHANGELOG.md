# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Placeholder nullification for name/address roles: `nullify_placeholder_name` and `nullify_placeholder_address` feature functions with auto-injection for first_name, last_name, middle_name, full_name, address_line_1, address_line_2 roles
- Per-run cost alerting and budget guards: `cost_alert_threshold_bytes` (warning) and `cost_abort_threshold_bytes` (abort) on `JobTrackingConfig` with cumulative tracking in `PipelineExecutor`
- Run comparison queries: `build_run_comparison_sql()` FULL OUTER JOINs two pipeline runs by `sql_hash` showing bytes_billed_delta, duration_delta, and comparison_status (NEW/REMOVED/MATCHED)
- Blocking key effectiveness dashboard: `build_blocking_effectiveness_sql()` produces cross-tier UNION ALL with reduction_ratio, avg/max candidates_per_entity, and cartesian_baseline
- Placeholder auto-detection via profiling: `PlaceholderProfiler` class + `bq-er profile-placeholders` CLI command scanning source data for known and suspected placeholder values with YAML snippet generation
- Data quality score: `DataQualityScorer` computes 0-100 aggregate metric from placeholder rates, null rates, and blocking effectiveness; `DataQualityScoreGate` integrates with pipeline quality gates
- `PipelineCostExceededError` exception for budget guard enforcement
- `min_data_quality_score` config option on `MonitoringConfig` (0-100, 0=disabled)
- Extensibility APIs: `Pipeline.from_stages()`, `stage_overrides`, `exclude_stages`, `dag_builder`
- Entry point plugins for features (`bq_er.features`) and comparisons (`bq_er.comparisons`)
- Entity type templates (19 built-in: Person, Organization, PostalAddress, InsuredEntity, FinancialAccount, Patient, Thing, Subscriber, ServiceLocation, Carrier, Property, Vehicle, Device, Merchant, Student, Guest, Claimant, Vendor, DigitalIdentity) with schema.org aliases and hierarchy resolution
- 37 new cross-industry column roles covering Telecom, Logistics, Retail, Real Estate, Public Sector, Education, Travel, Manufacturing/IoT, Vendor Master, and Identity/Fraud
- 10 new domain presets: telecom_subscriber, logistics_carrier, retail_customer, real_estate_property, public_sector, education_student, travel_guest, vendor_master, identity_fraud
- 10 new config validators: embedding_source_columns, hash_cursor_column, hard_positive_target_band, score_band_name_uniqueness, clustering_method, golden_record_columns, canonical_field_strategies, active_learning_config, enrichment_join_table_format, skip_stages, incremental_cursor_columns (29 total)
- Advanced signal framework: HardPositiveDef (boost/auto_match/elevate_band), HardNegativeDef (4 severity classes), SoftSignalDef (entity_type_condition), ScoreBandingConfig, ConfidenceShapingConfig
- Token comparison functions: dice, overlap, monge_elkan, token_sort_ratio (set semantics)
- Compound record detection: `is_compound_name`, `compound_pattern`, `extract_compound_first/second` features + `compound/` package
- BQML classification stage for ML-assisted matching
- Distributed locking (`pipeline/lock.py`) for concurrent run safety
- Health probe updates on stage completion for Kubernetes liveness checks
- Graceful shutdown handling (`pipeline/shutdown.py`)
- 3 CLI commands: `init-config`, `check-env`, `describe`
- 20 example configs covering: minimal, customer, person linkage, insurance, healthcare, banking, telecom, logistics, retail, real estate, education, vendor master, probabilistic, compound detection, enrichment, entity types, signals, multi-source, Kubernetes, incremental
- SQL injection prevention in EM builder, DuckDB backend, init-config CLI, and 3 additional SQL builder dataclasses (features, golden_record, bqml)
- `sql_escape()` applied to tier names in all scoring/blocking/active-learning SQL builders
- 24+ numeric range validators on Pydantic config fields (LSH params, embedding dims, batch sizes, EM training params, clustering iterations, blocking limits, confidence shaping thresholds)
- String min_length validators on source names, blocking key names, feature names, enrichment join fields, project config
- Cross-field validator `validate_source_priority()` checks golden record source_priority references
- Entity type registration overwrite protection with logging warnings
- PII redaction in SQL audit logs (`_redact_sql()` in executor)
- Safe default for `bucket_size_limit` (10,000) to prevent candidate pair explosion
- Remediation hints in validator error messages
- `docs/TUNING.md` — output schema reference, diagnostic scenarios, and key tuning parameters
- 4 new feature modules: entity_features, email_features, business_features, negative_features
- 5 length-aware comparison functions: `levenshtein_length_aware`, `levenshtein_length_aware_score`, `length_ratio`, `length_ratio_score`, `exact_diacritics_insensitive`
- 2 length-aware feature functions: `length_bucket` (groups strings by character length ranges), `length_category` (S/M/L classification)
- Watermark DATE and NUMERIC/BIGNUMERIC type support for incremental processing cursors
- 5 new config validators: `validate_incremental_config`, `validate_clustering_compatibility`, `validate_threshold_consistency`, `validate_name_collisions`, `validate_feature_dependencies` (DFS cycle detection)
- Right-column normalization on HardNegativeDef, HardPositiveDef, SoftSignalDef (auto-sets `right = left` when omitted)
- Checkpoint abort after 3 consecutive write failures (prevents silent data loss)
- Drain mode consecutive empty batch detection (breaks after 2 empty batches)
- SQL audit log duration tracking (`duration_seconds`, `bytes_billed` per query) with summary properties
- Progress callback error details (elapsed time + error message on stage failure)
- Blocking effectiveness summary log (tier name, path count, per-path key/limit breakdown)
- Include depth guard (max 50 levels) to prevent infinite recursion in config includes
- Sigmoid confidence normalization (`confidence_method: "sigmoid"`) for sum scoring — `1/(1+exp(-score))` for calibrated probabilities
- `min_matching_comparisons` threshold parameter — requires N comparisons to agree before accepting match (applies to both sum and F-S scoring)
- Comparison input validation via `get_comparison_safe()` / `_validated_call()` — prevents SQL injection through column names
- Expanded PII redaction patterns: phone, SSN, email detection; redaction always-on for SQL audit logs
- Confidence shaping now updates `match_confidence` column (was previously computed but not applied)
- Source table format validation (`project.dataset.table` enforcement)
- `TrainingConfig` model validator (method=labeled requires labeled_pairs_table)
- `CanonicalSelectionConfig` model validator (method=field_merge requires field_strategies)
- Zero-weight comparison warning in `validate_comparison_weights()`
- `table_expiration_days` in ScaleConfig — optional TTL for generated BigQuery tables
- `weighted_sum` deprecation warning (normalized to `sum` at load time)
- Cluster stability tracking SQL builder (`build_cluster_stability_sql`) — detects entity reassignment, new entities, stable entities across runs
- Full barrel exports in `stages/__init__.py` — all 18 stage classes importable from top-level package
- Stage-level debug logging in all 15 plan() methods for production observability

### Changed

- 8 monolithic files split into domain-specific sub-modules (features, CLI, config, comparisons, DuckDB, clustering, comparison, presets) — all use barrel-import pattern
- Feature function count: 92 → 97; Comparison function count: 49 → 54; SQL builder count: 14 → 21; test count: 1,721 → 3,309
- `BlockingPathDef.bucket_size_limit` default changed from 0 (no limit) to 10,000
- EM estimation SQL uses atomic `CREATE OR REPLACE` instead of `DROP TABLE` + `ALTER RENAME` in WHILE loop
- Quality gates now run BEFORE checkpoint persistence (prevents persisting failed stages)

### Fixed

- DuckDB backend gaps: COUNTIF macro, TIMESTAMP_DIFF rewrite, TO_JSON_STRING(STRUCT) rewrite, spatial extension error handling
- `detect_role()` word-boundary matching prevents substring false positives (e.g., "name" no longer matches "username")
- EM column naming uses `LEFT_ENTITY_UID`/`RIGHT_ENTITY_UID` constants instead of hardcoded strings
- Thread-safe feature and comparison registries (prevents race conditions in multi-threaded environments)
- CheckpointManager SQL injection prevention via strict character allowlist sanitization
- Pipeline lock refresh failure now aborts with RuntimeError instead of silently warning
- Drain mode watermark advance failure now propagates exception instead of logging warning
- `has_unprocessed_records()` failure now assumes more records exist (prevents data loss)
- Empty string handling in `name_clean()` and `name_clean_strict()` — `NULLIF(TRIM(...), '')` prevents false positive matches on empty strings
- Quality gates differentiate "table not found" (expected) vs connection errors (unexpected); error-severity gates re-raise unexpected exceptions
- Cross-tier exclusion in pipeline plan uses explicit tier-index set instead of stateful flag
- DuckDB type adaptation: NUMERIC→DECIMAL(38,9), BIGNUMERIC→DECIMAL(76,38)
- BQ scripting detection uses line-start anchored regex (`^\s*DECLARE\b`) to prevent false positives on column names like `declared_at`
- EM convergence uses OR instead of AND for dual criteria (converges when parameters OR log-likelihood stabilize)
- `resolved_entity_id` kept as INT64 (was STRING-cast with prefix); format at presentation time
- Canonical index populate uses atomic MERGE instead of separate UPDATE+INSERT (prevents data loss on crash)
- Empty environment variables caught at config load time (was silently passing empty string)
- TF formula in Fellegi-Sunter scoring documented (non-standard heuristic explained in docstring)

## [0.2.0] - 2026-02-23

### Added

- DAG-based pipeline architecture: `Pipeline` -> `StageDAG` -> `Stage.plan()` -> `PipelineExecutor`
- 8 composable Stage classes with declared inputs/outputs and compile-time contract validation
- 14 Python SQL builder modules (30 functions, 28 frozen dataclasses) replacing all Jinja2 templates
- `SQLExpression` wrapper (sqlglot-based) for dialect-aware SQL generation
- Pluggable backend system: `BigQueryBackend`, `DuckDBBackend`, `BQEmulatorBackend`
- DuckDB backend with comprehensive BigQuery SQL shims (SOUNDEX, metaphone, FARM_FINGERPRINT, BQ scripting interpreter)
- Progressive disclosure config presets: `quick_config()`, `person_dedup_preset`, `business_dedup_preset`, etc.
- Column role detection and auto-generation of features, blocking keys, and comparisons
- Compile-time schema contract validation (`pipeline/validator.py`)
- Runtime quality gates: `OutputNotEmptyGate`, `ClusterSizeGate`
- Checkpoint/resume for crash-resilient incremental processing
- Incremental clustering with cross-batch canonical index
- Column profiling and weight sensitivity analysis (`profiling/`)
- Config includes with circular dependency detection
- Field-level golden record assembly (`field_merge` canonical method)
- Term frequency (TF-IDF) adjusted scoring
- 1,721 tests (unit + integration) with DuckDB-based execution verification
- Comprehensive architectural documentation (`docs/ARCHITECTURE.md`)

### Removed

- All 25 Jinja2 SQL templates (`sql/templates/` directory)
- `SQLGenerator` class and Jinja2 rendering infrastructure (`sql/generator.py`)
- Legacy engine classes: `FeatureEngine`, `BlockingEngine`, `MatchingEngine`, `ReconciliationEngine`
- Legacy `PipelineOrchestrator` (replaced by `Pipeline` + `StageDAG`)
- `jinja2` dependency from `pyproject.toml`

### Changed

- All SQL generation now uses Python builder functions (type-safe, unit-testable)
- `WatermarkManager`, `CheckpointManager`, `EmbeddingManager`, `ActiveLearningEngine`, `ParameterEstimator` no longer depend on `SQLGenerator`
- CLI commands use `Pipeline`/`Stage` classes instead of legacy engines
- Feature function count increased from 45+ to 92
- Comparison function count increased from 22+ to 49

## [0.1.0] - 2026-02-22

### Added

- Multi-tier entity resolution pipeline driven by YAML configuration
- Python orchestrator that generates and executes SQL against BigQuery
- 45+ feature functions: name cleaning, address standardization, phone normalization, nickname resolution, phonetic encoding, date/zip extraction, geo hashing, and more
- 22+ comparison functions: exact, Levenshtein, Jaro-Winkler, Soundex, cosine similarity, token overlap, geo distance, and more
- Multi-path blocking with per-path candidate limits
- LSH (Locality-Sensitive Hashing) blocking for embedding-based matching
- Fellegi-Sunter probabilistic matching with EM parameter estimation
- Active learning with review queue generation and label ingestion
- Hard negative disqualification and soft signal scoring
- Connected components clustering with canonical record election
- Incremental processing with runtime watermarks and grace periods
- Full Pydantic v2 configuration validation with cross-field checks
- `bq-er` CLI with commands: `run`, `validate`, `preview-sql`, `estimate-params`, `review-queue`, `ingest-labels`
- Docker packaging with multi-stage build and non-root execution
- Three production-quality example configs (insurance entity, customer dedup, probabilistic matching)
- Environment variable interpolation in YAML configs
- SQL audit logging and pipeline diagnostics

[0.2.0]: https://github.com/bq-entity-resolution/bq-entity-resolution/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bq-entity-resolution/bq-entity-resolution/releases/tag/v0.1.0

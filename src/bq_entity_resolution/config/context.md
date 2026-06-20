# Config Package

## Purpose

Defines, loads, validates, and provides presets for pipeline configuration. Uses Pydantic v2 for type-safe YAML-driven config with environment variable interpolation, progressive disclosure (quick_config → presets → full YAML), and entity type templates.

## Key Files

| File | Description |
|------|-------------|
| `schema.py` | **Barrel re-export** of all config models. Import from here for convenience. |
| `loader.py` | YAML loading with `${VAR}` / `${VAR:-default}` environment variable interpolation. Supports `!include` for config composition. |
| `validators.py` | Cross-field validators: blocking key existence, comparison column references, feature dependency chains, typo suggestions via difflib. |
| `roles.py` | Column role detection: maps column names to semantic roles (`first_name`, `email`, `date_of_birth`, etc.). Drives auto-feature/blocking/comparison generation. Schema.org aliases supported. |
| `entity_types.py` | **EntityTypeTemplate** registry — 7 built-in types (Person, Organization, PostalAddress, etc.) with hierarchy resolution, valid roles, and default signals. |

## Sub-Packages

| Sub-Package | Description |
|-------------|-------------|
| `models/` | 7 domain-specific Pydantic v2 models: `source.py`, `features.py`, `blocking.py`, `matching.py`, `reconciliation.py`, `infrastructure.py`, `pipeline.py` |
| `presets/` | `quick_config.py` (minimal 5-line setup), `domain_presets.py` (person_dedup, insurance, etc.), `helpers.py` (shared preset utilities) |

## Architecture

```
YAML file
  → loader.py (env var interpolation, !include)
  → PipelineConfig (Pydantic v2 validation)
    ├── ProjectConfig           (BQ project/dataset routing)
    ├── SourceConfig[]          (tables, columns, roles, entity_type)
    ├── FeatureEngineeringConfig (features, blocking keys, enrichments)
    ├── MatchingTierConfig[]    (blocking, comparisons, thresholds)
    ├── ReconciliationConfig    (clustering, golden record, output)
    ├── IncrementalConfig       (watermarks, drain mode, batch size)
    ├── DeploymentConfig        (health probe, lock, graceful shutdown)
    └── MonitoringConfig        (metrics, logging)
```

## Key Patterns

- **Progressive disclosure** — `quick_config()` → domain presets → full YAML. Users start simple and customize as needed.
- **Role-based auto-generation** — `detect_role(column_name)` triggers automatic feature, blocking key, and comparison generation.
- **Entity type templates** — `entity_type: "Person"` on a source auto-injects validated roles and default hard negative/soft signal rules.
- **Cross-field validation** — validators catch mismatches between blocking keys, features, comparisons, and source columns at load time with helpful error messages.
- **Comparison pool** — reusable comparison definitions referenced by `ref` in tiers.

## Dependencies

- Used by every other package (this is the configuration layer)
- `features/registry.py` — validates feature function names exist
- `matching/comparisons/` — validates comparison method names exist

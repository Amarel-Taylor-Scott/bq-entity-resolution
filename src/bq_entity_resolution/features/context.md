# Features Package

## Purpose

Feature function registry: 92 `@register("name")` functions across 13 domain sub-modules. Each function takes a column name and optional kwargs, returning a SQL expression string for use in the feature engineering CTE.

## Key Files

| File | Description |
|------|-------------|
| `registry.py` | **Barrel import** — imports all sub-modules to populate the registry. `get_feature_function()`, `list_feature_functions()`. Thread-safe with `threading.Lock`. |
| `name_features.py` | Name processing: `name_clean`, `name_tokens`, `name_metaphone`, `name_soundex`, `extract_suffix`, `extract_roman_numeral`, etc. |
| `address_features.py` | Address normalization: `address_clean`, `address_tokens`, `street_number`, `po_box_flag`, `address_hash`. |
| `contact_features.py` | Contact info: `phone_digits`, `phone_area_code`, `email_domain`, `email_local_part`. |
| `date_identity_features.py` | Date/ID: `date_year`, `date_month`, `ssn_last4`, `dob_hash`. |
| `geo_features.py` | Geography: `lat_lon_bucket`, `geo_state_code`, `geo_precision`. |
| `blocking_keys.py` | Blocking key functions: `farm_fingerprint`, `first3_last3`, `soundex_key`, `metaphone_key`. |
| `utility_features.py` | General utilities: `upper`, `lower`, `length`, `null_flag`, `coalesce_columns`. |
| `phonetic_features.py` | Phonetic encoding: `soundex`, `metaphone`, `double_metaphone`. |
| `zip_features.py` | ZIP code features: `zip5`, `zip3`, `zip_first_digit`. |
| `entity_features.py` | Entity type classification: `entity_type_classify`, `is_business_name`, `is_person_name`. |
| `email_features.py` | Email-specific: `email_local_part_safe`, `email_domain_safe`. |
| `business_features.py` | Business names: `business_name_clean`, `strip_legal_suffix`, `business_acronym`. |
| `negative_features.py` | Negative signal features: `is_placeholder`, `is_test_record`, `data_quality_score`. |
| `industry_features.py` | Industry-specific: `sic_code`, `naics_sector`. |

## Architecture

```
@register("name_clean")     ← decorator adds function to _REGISTRY dict
def name_clean(col, **_):   ← takes column name, returns SQL expression string
    return f"UPPER(TRIM(REGEXP_REPLACE({col}, ...)))"

FeaturesStage.plan()
  → config.feature_engineering.features[]
  → get_feature_function(name)
  → function(input_column, **kwargs)
  → SQL expression used in CTE
```

## Key Patterns

- **`@register("name")` decorator** — registers function in global `_REGISTRY` dict. Warns on duplicate registration.
- **`**_: Any` on all functions** — forward compatibility for new kwargs.
- **Two-pass generation** — independent features (no feature-to-feature deps) in pass 1; dependent features in pass 2 via CTE chain.
- **Thread-safe registry** — `threading.Lock` protects `_REGISTRY` and `_plugins_loaded`.
- **Entry point plugins** — `bq_er.features` group in pyproject.toml for third-party feature functions.

## Dependencies

- `config/` — FeatureDef configuration
- `sql/builders/features.py` — feature SQL CTE assembly

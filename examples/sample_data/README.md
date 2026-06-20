# Sample Data for Local End-to-End Testing

## What the Sample Data Contains

`customers.csv` contains 50 synthetic customer records with deliberate duplicates and near-matches designed to exercise the entity resolution pipeline.

### Match Groups (5 clusters, ~22 duplicate records)

| Group | Entity | Records | Variations |
|-------|--------|---------|------------|
| 1 | John Smith | 1-5 | Name variants (John/Jon/Jonathan/Smyth), address typos, email changes |
| 2 | Jane Doe | 6-9 | Maiden/married name (Doe/Williams/Doe-Williams), abbreviated first name |
| 3 | Robert Johnson | 10-14 | Nicknames (Robert/Robt/Bob/Bobby), transposed digits in phone, last name typo |
| 4 | Maria Garcia | 15-18 | Nickname (Mari/Mary), hyphenated married name, address unit variation |
| 5 | James Williams | 19-22 | Moving addresses across Denver metro, nickname (Jim), email changes |

### Unique Records (28 non-duplicate records)

Records 23-50 are unique individuals with realistic US data: distinct names, addresses across different states, and unique contact information. These should remain as singleton clusters after resolution.

### Data Characteristics

- **Names**: Drawn from common US census name distributions
- **Addresses**: Plausible US street addresses in real cities with correct state/zip pairings
- **Phone numbers**: All use the 555 prefix (fictitious range)
- **Emails**: Realistic patterns (firstname.lastname@domain.com, firstlast@domain.com, initials@domain.com)
- **Dates of birth**: Consistent within each match group, varied across groups

## Configuration

`sample_dedup.yml` defines a two-tier matching pipeline:

1. **Exact tier**: Blocks on last name SOUNDEX + ZIP code, compares cleaned names and email with exact matching. Threshold: sum >= 2.0.
2. **Fuzzy tier**: Blocks on last name SOUNDEX only (broader recall), compares names using Levenshtein normalized distance and Jaro-Winkler similarity, plus exact email and phone. Threshold: sum >= 2.0.

Reconciliation uses connected components clustering with field-level merge strategies (most_common for names, most_complete for email).

## Running Locally with DuckDB

Once the DuckDB backend is available, you can run the full pipeline locally without BigQuery:

```python
from bq_entity_resolution.pipeline.pipeline import Pipeline
from bq_entity_resolution.config.loader import load_config
from bq_entity_resolution.backends.duckdb import DuckDBBackend

# Load config (skip env var interpolation since we use literal values)
config = load_config(
    "examples/sample_data/sample_dedup.yml",
    skip_env_interpolation=True,
    validate=False,
)

# Create DuckDB backend
backend = DuckDBBackend(":memory:")

# Load sample data into DuckDB
conn = backend._conn
conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
conn.execute("CREATE SCHEMA IF NOT EXISTS silver")
conn.execute("CREATE SCHEMA IF NOT EXISTS gold")
conn.execute("""
    CREATE TABLE local.bronze.customers AS
    SELECT * FROM read_csv_auto('examples/sample_data/customers.csv')
""")

# Run pipeline
pipeline = Pipeline(config)
result = pipeline.run(backend=backend, full_refresh=True)

print(f"Status: {result.status}")
print(f"Completed stages: {result.completed_stages}")
```

## Validating the Config (Works Today)

You can validate that the YAML config parses correctly against the Pydantic schema without running the pipeline:

```python
from bq_entity_resolution.config.loader import load_config

config = load_config(
    "examples/sample_data/sample_dedup.yml",
    skip_env_interpolation=True,
    validate=False,
)

print(f"Project: {config.project.name}")
print(f"Sources: {[s.name for s in config.sources]}")
print(f"Tiers: {[t.name for t in config.matching_tiers]}")
print(f"Blocking keys: {[bk.name for bk in config.feature_engineering.blocking_keys]}")
```

## Previewing Generated SQL

```bash
bq-er preview-sql --config examples/sample_data/sample_dedup.yml --tier exact --stage blocking
bq-er preview-sql --config examples/sample_data/sample_dedup.yml --tier fuzzy --stage matching
```

## Expected Results

When the pipeline completes successfully, you should see approximately:

- **5 match clusters** containing 2-5 records each (groups 1-5 above)
- **28 singleton clusters** (unique records 23-50)
- **~33 total clusters** in the gold output table

The exact number of matches depends on threshold tuning. With the provided thresholds (sum >= 2.0), the exact tier should catch records with identical cleaned names or shared emails, while the fuzzy tier catches nickname variants and records with typos.

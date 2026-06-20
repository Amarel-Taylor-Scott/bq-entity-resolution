# SQL Builders Package

## Purpose

Generates all SQL for the entity resolution pipeline. Pure Python functions — no Jinja2 templates. Each builder module contains frozen dataclass params and `build_*()` functions that return `SQLExpression` objects.

## Key Files

| File | Description |
|------|-------------|
| `staging.py` | Staging table DDL, watermark-filtered SELECT, hash cursor generation. |
| `features.py` | Feature engineering SQL: two-pass CTE (independent → dependent), enrichment joins, entity UID generation. |
| `blocking.py` | Blocking key candidate pair generation, bucket size limits, cross-batch blocking via canonical index. |
| `em.py` | Expectation-Maximization for Fellegi-Sunter parameter estimation (BQ scripting WHILE loop). |
| `embeddings.py` | BQML text embedding generation and LSH bucket computation. |
| `watermark.py` | Watermark/checkpoint table DDL, watermark read/update/fenced-update, fenced checkpoint insert. |
| `gold_output.py` | Gold layer resolved entities output. |
| `golden_record.py` | Golden record (canonical) construction from clusters. |
| `active_learning.py` | Active learning review queue generation (uncertain pairs near threshold). |
| `monitoring.py` | Metrics persistence SQL. |
| `bqml.py` | BQML model training and prediction SQL. |
| `udf.py` | UDF creation (Jaro-Winkler JS UDF for BigQuery). |

## Sub-Packages

| Sub-Package | Description |
|-------------|-------------|
| `comparison/` | Comparison scoring: `models.py` (dataclasses), `signals.py` (hard neg/pos, soft signals), `sum_scoring.py`, `fellegi_sunter.py`, `accumulation.py` |
| `clustering/` | Clustering algorithms: `connected_components.py` (BQ scripting WHILE loop), `incremental.py` (canonical index), `alternatives.py` (star, best-match), `metrics.py` (cluster quality) |

## Architecture

```
Stage.plan()
  → build_*_sql(params)
  → SQLExpression.from_raw(sql_string)
  → PipelinePlan.stages[].sql_expressions[]
  → PipelineExecutor renders and executes
```

## Key Patterns

- **Frozen dataclass params** — builder inputs are immutable, testable, inspectable.
- **`SQLExpression`** — all generated SQL wrapped in `SQLExpression` for consistent rendering and adaptation (DuckDB rewrites).
- **`sql_escape()`** — all string interpolation uses `sql/utils.py:sql_escape()` (ANSI `''` escaping). Strict regex validation for watermark values.
- **Two-pass feature SQL** — `base → enriched (optional) → features_pass1 → featured → final` CTE chain. Independent features first, dependent features second.
- **Fenced writes** — watermark and checkpoint builders have fenced variants that verify fencing tokens via BQ scripting blocks (DECLARE/IF/ROLLBACK).

## Dependencies

- `columns.py` — column name constants
- `sql/expression.py` — SQLExpression wrapper
- `sql/utils.py` — sql_escape, validate_identifier
- `naming.py` — table name generation
- `config/` — builder params derived from config models

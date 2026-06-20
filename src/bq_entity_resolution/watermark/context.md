# Watermark Package

## Purpose

Manages incremental processing state: tracks which records have been processed (watermarks) and which pipeline stages have completed (checkpoints). Enables crash recovery and efficient batch processing at scale.

## Key Files

| File | Description |
|------|-------------|
| `manager.py` | **WatermarkManager** — read/write/advance watermark cursors. Supports composite ordered watermarks, fenced writes with lock verification, and unprocessed record detection. |
| `checkpoint.py` | **CheckpointManager** — persists stage completion for crash recovery. Supports fenced checkpoint writes (verifies fencing token before INSERT). |
| `store.py` | Low-level watermark storage abstractions. |

## BigQuery Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `pipeline_watermarks` | Tracks cursor positions per source | `source_name`, `cursor_column`, `cursor_value`, `cursor_type`, `is_current` |
| `pipeline_checkpoints` | Tracks completed stages per run | `run_id`, `stage_name`, `completed_at`, `status` |

## Architecture

```
WatermarkManager
  ├── read(source_name)                  → current cursor values
  ├── write(source_name, cursors, ...)   → advance watermark (fenced or unfenced)
  ├── compute_new_watermark_from_staged  → MAX() from staged table
  └── has_unprocessed_records(...)       → bool (ordered or independent mode)

CheckpointManager
  ├── ensure_table_exists()
  ├── load_completed_stages(run_id)      → set of stage names
  ├── find_resumable_run()               → most recent incomplete run_id
  ├── mark_stage_complete(run_id, stage, *, fencing_token, ...)
  └── mark_run_complete(run_id, *, fencing_token, ...)
```

## Key Patterns

- **Composite ordered watermarks** — `cursor_mode="ordered"` generates tuple comparison: `(col1 > wm1) OR (col1 = wm1 AND col2 > wm2)`.
- **Fenced writes** — when fencing params provided, watermark/checkpoint writes use BQ scripting blocks that verify the fencing token before committing.
- **Unfenced fallback** — when `fencing_token=None` (DuckDB, local dev), falls back to standard transactional writes.
- **Input sanitization** — all user-supplied values validated against strict character allowlist before SQL interpolation.

## Dependencies

- `sql/builders/watermark.py` — SQL generation for watermark/checkpoint DDL and DML
- `pipeline/lock.py` — fencing token source (PipelineLock)
- `columns.py` — column name constants

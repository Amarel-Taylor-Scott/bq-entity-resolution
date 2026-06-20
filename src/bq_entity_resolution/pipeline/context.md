# Pipeline Package

## Purpose

Orchestrates the complete entity resolution pipeline — from validation through planning to execution. This is the main entry point for running pipelines.

## Key Files

| File | Description |
|------|-------------|
| `pipeline.py` | **Pipeline class** — the recommended API. Combines validation, planning, execution, drain mode, watermark management, distributed locking, health probes, and graceful shutdown. |
| `executor.py` | **PipelineExecutor** — runs a `PipelinePlan` against a `Backend`. Handles quality gates, checkpoint persistence, cost ceiling, health heartbeats. |
| `plan.py` | **PipelinePlan / StagePlan** — frozen dataclasses holding pre-generated SQL. `create_plan()` walks the DAG and calls each stage's `plan()` method. |
| `dag.py` | **StageDAG** — topological sort of Stage objects by their input/output `TableRef` declarations. `build_pipeline_dag()` constructs the default DAG from config. |
| `validator.py` | Compile-time validation: checks all stage inputs are produced by upstream stages, validates stage-specific config. |
| `gates.py` | **DataQualityGate** — runtime assertions after each stage (e.g., "candidate pairs < 100M"). |
| `lock.py` | **PipelineLock** — distributed lock via BigQuery MERGE with fencing tokens. Prevents concurrent K8s pods from running the same pipeline. |
| `health.py` | **HealthProbe** — file-based K8s liveness probe. Writes JSON to a configurable path. |
| `shutdown.py` | **GracefulShutdown** — SIGTERM handler that cancels BQ jobs, releases locks, marks health probe unhealthy. |
| `diagnostics.py` | Pipeline diagnostic helpers (SQL audit, stage timings). |
| `runner.py` | Legacy runner (thin wrapper, prefer `Pipeline` class). |
| `context.py` | Pipeline execution context dataclass. |

## Architecture

```
Pipeline.run()
  ├── validate()           → ContractViolation list
  ├── Infrastructure setup
  │   ├── HealthProbe
  │   ├── GracefulShutdown (SIGTERM handler)
  │   └── PipelineLock (atomic MERGE, fencing tokens)
  ├── _run_loop()
  │   ├── plan()           → PipelinePlan (immutable SQL)
  │   ├── execute()        → PipelineExecutor
  │   │   ├── per-stage:   run SQL, quality gates, checkpoint, heartbeat
  │   │   └── mark_run_complete
  │   ├── record metrics
  │   ├── refresh lock heartbeat
  │   ├── advance watermarks (fenced)
  │   └── drain loop (repeat if more records)
  └── finally: release lock, update health probe
```

## Key Patterns

- **Plan-Execute split** — all SQL is pre-generated and inspectable before any execution.
- **Fencing tokens** — sequence-based (COALESCE + 1 in MERGE), verified before watermark and checkpoint writes.
- **Quality gates before checkpoints** — gates run before checkpoint persistence so failed gates aren't persisted as completed.
- **Checkpoint/resume** — `CheckpointManager` persists stage completion; `PipelineExecutor` skips completed stages on resume.

## Dependencies

- `stages/` — Stage implementations (plan generation)
- `config/` — PipelineConfig (configuration)
- `backends/` — Backend protocol (SQL execution)
- `watermark/` — WatermarkManager, CheckpointManager
- `monitoring/` — MetricsCollector
- `sql/` — SQLExpression

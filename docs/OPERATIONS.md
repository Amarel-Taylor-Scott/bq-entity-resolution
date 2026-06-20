# Operations Guide

Production operations reference for bq-entity-resolution pipelines.
Covers health checks, troubleshooting, alerting, and manual recovery.

## Pipeline Health Checks

### Kubernetes Liveness Probe

The pipeline writes a JSON health file at each stage completion:

```yaml
livenessProbe:
  exec:
    command: ["cat", "/tmp/pipeline_healthy"]
  initialDelaySeconds: 60
  periodSeconds: 30
```

If the file is not updated for >60s, the pod is considered unhealthy.
Long-running stages (clustering, EM parameter estimation) update the
probe per SQL query via heartbeat.

### Manual Health Check

```bash
# Check if pipeline is running
cat /tmp/pipeline_healthy
# Returns JSON: {"timestamp": "...", "stage": "matching_tier_1", "run_id": "...", "pid": 1234}

# Check BigQuery job status
bq ls -j --project_id=YOUR_PROJECT | head -20

# Check watermark position
bq query "SELECT * FROM \`project.er_meta.pipeline_watermarks\` ORDER BY last_updated DESC LIMIT 5"

# Check checkpoint state
bq query "SELECT * FROM \`project.er_meta.pipeline_checkpoints\` WHERE run_id = 'er_run_YYYYMMDD_HHMMSS' ORDER BY completed_at"
```

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Pipeline hangs at "clustering" | WHILE loop iteration limit or dense cluster graph | Increase `clustering.max_iterations` in config, or tighten blocking keys to reduce candidate pairs |
| `PipelineAbortError: Circuit breaker open` | 5+ consecutive non-retryable BQ errors | Check BQ permissions, project ID, dataset existence. Fix root cause, then restart pipeline |
| `PipelineAbortError: cost ceiling exceeded` | Query bytes exceed `scale.max_bytes_billed` | Increase ceiling, add partition pruning, or tighten blocking |
| `RuntimeError: Lock refresh matched 0 rows` | Lock stolen by another pod after TTL expiry | Increase `ttl_minutes` or add lock refresh calls. Pipeline auto-aborts safely |
| `ValueError: Partial fencing config` | 1-2 of 3 fencing params provided | Provide all three (fencing_token, lock_table, pipeline_name) or none |
| `ConfigurationError: blocking key undefined` | Blocking key referenced in tier but not in feature_engineering | Add the key to `feature_engineering.blocking_keys` |
| Candidate pair explosion (>100M pairs) | Blocking key too coarse (low cardinality) | Add more blocking keys, use composite keys, or set `candidate_limit` |
| `DefaultCredentialsError` | Missing BigQuery auth | Run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS` |
| Stage re-executes on resume | Checkpoint write failed (but stage succeeded) | Normal behavior; stages are idempotent (CREATE OR REPLACE TABLE). Safe to re-run |
| `SQLExecutionError: Query timed out` | Single query exceeded `default_timeout` | Increase timeout, optimize blocking to reduce candidate pairs, or add partition hints |

## Alerting Thresholds

### Recommended Alerts

| Metric | Warning | Critical | Source |
|--------|---------|----------|--------|
| Pipeline duration | >2x historical average | >4x or timeout | Pipeline logs (`duration_seconds`) |
| Stage duration | >1 hour for any stage | >3 hours | Per-stage SQL log entries |
| Bytes billed per run | >50% of `max_bytes_billed` | >80% of ceiling | `PipelineResult.total_bytes_billed` |
| Checkpoint write failures | 1 consecutive | 3 consecutive (auto-aborts) | Executor logs |
| Lock contention | >30s wait for lock | >5min / timeout | Lock acquisition logs |
| Watermark lag | >24h behind source data | >72h behind | Compare watermark to MAX(updated_at) |
| Empty drain batches | 2 consecutive (auto-stops) | N/A | Drain mode logs |

### Log Patterns to Monitor

```bash
# Errors (pipeline failures)
grep "Pipeline failed" /var/log/pipeline.log

# Lock contention
grep "Lock for.*held by.*retrying" /var/log/pipeline.log

# Checkpoint failures
grep "Failed to persist checkpoint" /var/log/pipeline.log

# Cost warnings
grep "cost ceiling" /var/log/pipeline.log

# Circuit breaker trips
grep "Circuit breaker open" /var/log/pipeline.log
```

## Manual Recovery Procedures

### Stuck Pipeline (hung stage)

```bash
# 1. Identify the stuck BigQuery job
bq ls -j --project_id=YOUR_PROJECT --max_results=10

# 2. Cancel the job
bq cancel JOB_ID

# 3. If the pod is still running, send SIGTERM for graceful shutdown
kill -TERM $PID
# Pipeline will cancel active jobs, release lock, mark unhealthy

# 4. Restart with --resume to skip completed stages
bq-er run --config config.yml --resume
```

### Corrupted Checkpoint Table

```sql
-- 1. Inspect checkpoint state
SELECT * FROM `project.er_meta.pipeline_checkpoints`
WHERE run_id = 'er_run_YYYYMMDD_HHMMSS'
ORDER BY completed_at;

-- 2. If a stage is marked complete but its output table is missing/corrupt,
--    delete that checkpoint entry so it re-runs on resume
DELETE FROM `project.er_meta.pipeline_checkpoints`
WHERE run_id = 'er_run_YYYYMMDD_HHMMSS'
AND stage_name = 'matching_tier_1';

-- 3. Resume
-- bq-er run --config config.yml --resume
```

### Stale Watermark

```sql
-- 1. Check current watermark
SELECT * FROM `project.er_meta.pipeline_watermarks`
WHERE pipeline_name = 'customer_dedup';

-- 2. Manually advance watermark (use with caution)
UPDATE `project.er_meta.pipeline_watermarks`
SET last_processed_value = '2025-01-15T00:00:00'
WHERE pipeline_name = 'customer_dedup';

-- 3. Or reset to process all data from scratch
-- bq-er run --config config.yml --full-refresh
```

### Stale Lock

```sql
-- 1. Check lock state
SELECT * FROM `project.er_meta.pipeline_locks`;

-- 2. If the lock holder process is dead (check PID), delete the lock
DELETE FROM `project.er_meta.pipeline_locks`
WHERE pipeline_name = 'customer_dedup'
AND expires_at < CURRENT_TIMESTAMP();

-- 3. If the lock hasn't expired but the holder is dead, force-delete
DELETE FROM `project.er_meta.pipeline_locks`
WHERE pipeline_name = 'customer_dedup';
-- WARNING: Only do this if you are certain the holder is dead.
-- If another pod is still running, this could cause concurrent execution.
```

### Circuit Breaker Reset

The circuit breaker is in-memory and resets when the process restarts.
There is no persistent state to clear.

```bash
# Simply restart the pipeline process
bq-er run --config config.yml --resume
```

If the circuit breaker keeps tripping, the root cause is likely:
- Wrong `bq_project` or dataset name in config
- IAM permissions revoked
- BigQuery quota exhausted
- Network connectivity issue

## Incremental Processing Recovery

### Drain Mode Stalls

Drain mode automatically stops after 2 consecutive empty batches.
If it stalls mid-drain:

```bash
# Check current batch position
bq query "SELECT * FROM \`project.er_meta.pipeline_watermarks\`"

# Force one more drain iteration
bq-er run --config config.yml --drain

# Or switch to full refresh
bq-er run --config config.yml --full-refresh
```

### Partial Batch Recovery

If a pipeline crash leaves a partial batch (some stages completed, others not):

```bash
# Resume from checkpoint — completed stages are skipped
bq-er run --config config.yml --resume

# If resume fails, identify the problem stage from logs, then
# either fix the config or do a full refresh
bq-er run --config config.yml --full-refresh
```

### Canonical Index Corruption

The canonical index accumulates entities across batches. If corrupted:

```sql
-- Check canonical index health
SELECT COUNT(*) as total, COUNT(DISTINCT cluster_id) as clusters
FROM `project.er_silver.pipeline_canonical_index`;

-- If corrupt, drop and rebuild from gold output
DROP TABLE IF EXISTS `project.er_silver.pipeline_canonical_index`;
-- Then run full refresh to rebuild
-- bq-er run --config config.yml --full-refresh
```

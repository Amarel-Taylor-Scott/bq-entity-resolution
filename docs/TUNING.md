# Tuning Guide

Practical guidance for diagnosing and resolving common pipeline issues.

## Output Schema Reference

The pipeline produces tables across four BigQuery datasets (bronze, silver, gold, meta).
Table names are centralized in `naming.py`; column names in `columns.py`.

### Bronze Layer (`er_bronze`)

| Table | Description |
|-------|-------------|
| `staged_{source}` | Cleaned source records with `entity_uid`, `source_name`, `source_updated_at`, `pipeline_loaded_at` |

### Silver Layer (`er_silver`)

| Table | Description |
|-------|-------------|
| `featured` | All engineered features + blocking keys per entity |
| `candidates_{tier}` | Candidate pairs from blocking (per tier): `left_entity_uid`, `right_entity_uid`, `blocking_path` |
| `matches_{tier}` | Scored match pairs (per tier): `left_entity_uid`, `right_entity_uid`, `match_total_score`, `match_confidence`, `match_detail` |
| `all_matched_pairs` | Accumulated matches across all tiers: includes `match_tier_name`, `match_tier_priority`, `matched_at` |
| `entity_clusters` | Cluster assignments: `entity_uid`, `cluster_id` (INT64, connected components output) |
| `entity_embeddings` | BQML embeddings (if enabled): `entity_uid`, `bqml_predicted_embedding`, `embedding_input_text` |
| `lsh_buckets` | LSH bucket assignments (if enabled): `entity_uid`, `fp_lsh_bucket_0`, ... |
| `fs_parameters_{tier}` | Fellegi-Sunter m/u parameters (if EM enabled): `comparison_name`, `level_label`, `m_probability`, `u_probability` |
| `al_review_queue_{tier}` | Active learning review queue: uncertain pairs for human labeling |
| `al_labels` | Human-provided match labels: `left_entity_uid`, `right_entity_uid`, `is_match`, `label_source` |
| `term_frequencies` | TF statistics: `term_frequency_column`, `term_frequency_value`, `term_frequency_count`, `term_frequency_ratio` |

### Gold Layer (`er_gold`)

| Table | Description |
|-------|-------------|
| `resolved_entities` | Final output: canonical records with `resolved_entity_id`, `canonical_entity_uid`, `is_canonical`, `canonical_score`, `completeness_score` |
| `canonical_index` | Incremental entity index: `entity_uid`, `cluster_id` (persists across batches) |

### Meta Layer (`er_meta` / watermark dataset)

| Table | Description |
|-------|-------------|
| `watermarks` | Cursor positions: `source_name`, `cursor_column`, `cursor_value`, `is_current` |
| `pipeline_checkpoints` | Stage completion: `run_id`, `stage_name`, `completed_at`, `status` |
| `pipeline_sql_audit` | SQL audit trail: `run_id`, `stage`, `sql_text`, `executed_at` |

---

## Common Symptoms and Remediation

### 1. Slow Blocking / Too Many Candidate Pairs

**Symptoms:**
- Blocking stage takes >10 minutes on moderate data (<1M records)
- `candidates_{tier}` table has >50M rows
- BigQuery slot usage spikes during blocking

**Diagnostic queries:**
```sql
-- Check candidate pair count per tier
SELECT COUNT(*) AS pair_count
FROM `project.er_silver.candidates_exact`;

-- Check blocking key cardinality (low cardinality = too many pairs)
SELECT bk_column, COUNT(*) AS bucket_size
FROM `project.er_silver.featured`
GROUP BY bk_column
ORDER BY bucket_size DESC
LIMIT 20;
```

**Remediation:**
- Add `bucket_size_limit` to blocking paths (default: 10,000; lower for tighter control):
  ```yaml
  blocking:
    paths:
      - keys: [bk_email]
        bucket_size_limit: 5000
  ```
- Add `candidate_limit` to cap pairs per entity (default: 200):
  ```yaml
  blocking:
    paths:
      - keys: [bk_last_soundex, bk_zip5]
        candidate_limit: 100
  ```
- Use composite blocking keys (`[bk_zip5, bk_last_soundex]`) instead of single broad keys
- Use INT64 `fp_` fingerprint keys instead of STRING `bk_` keys for faster JOINs

### 2. Poor Match Quality (False Positives)

**Symptoms:**
- Unrelated records clustered together
- Large clusters (>20 records) with mixed entities
- Low `match_confidence` scores in `all_matched_pairs`

**Diagnostic queries:**
```sql
-- Find suspiciously large clusters
SELECT cluster_id, COUNT(*) AS size
FROM `project.er_silver.entity_clusters`
GROUP BY cluster_id
HAVING COUNT(*) > 10
ORDER BY size DESC;

-- Inspect match details for a large cluster
SELECT m.left_entity_uid, m.right_entity_uid,
       m.match_total_score, m.match_detail
FROM `project.er_silver.all_matched_pairs` m
JOIN `project.er_silver.entity_clusters` c1
  ON m.left_entity_uid = c1.entity_uid
WHERE c1.cluster_id = <suspect_cluster_id>
ORDER BY m.match_total_score ASC;
```

**Remediation:**
- Raise `threshold.min_score` to reject weak matches:
  ```yaml
  threshold:
    min_score: 8.0  # was 5.0
  ```
- Add hard negatives to disqualify impossible matches:
  ```yaml
  hard_negatives:
    - left: gen_suffix
      right: gen_suffix
      method: different
      severity: hn2_structural
  ```
- Enable score banding to separate high/medium/low confidence:
  ```yaml
  score_banding:
    enabled: true
    bands:
      - name: HIGH
        min_score: 10.0
        action: accept
      - name: REVIEW
        min_score: 6.0
        max_score: 10.0
        action: review
      - name: LOW
        min_score: 0.0
        max_score: 6.0
        action: reject
  ```

### 3. Poor Match Quality (False Negatives / Missing Matches)

**Symptoms:**
- Known duplicates not matched
- Very few candidate pairs generated
- Most entities remain singletons after clustering

**Diagnostic queries:**
```sql
-- Singleton ratio (should be <80% for typical dedup)
SELECT
  COUNT(*) AS total_clusters,
  COUNTIF(size = 1) AS singletons,
  ROUND(COUNTIF(size = 1) / COUNT(*) * 100, 1) AS singleton_pct
FROM (
  SELECT cluster_id, COUNT(*) AS size
  FROM `project.er_silver.entity_clusters`
  GROUP BY cluster_id
);
```

**Remediation:**
- Lower `threshold.min_score` to allow more matches through
- Add additional blocking paths (more paths = more recall):
  ```yaml
  blocking:
    paths:
      - keys: [bk_email]           # Exact email match
      - keys: [bk_last_soundex, bk_zip5]  # Phonetic + geographic
      - keys: [bk_phone]           # Phone match
  ```
- Add fuzzy comparisons (levenshtein, jaro_winkler) alongside exact comparisons
- Check that blocking keys are not too restrictive (high cardinality is good for precision but bad for recall)

### 4. Clustering Timeout

**Symptoms:**
- `Stage 'clustering' failed: WHILE loop exceeded max iterations`
- Clustering stage runs for >30 minutes
- Connected components loop does not converge

**Diagnostic queries:**
```sql
-- Check cluster graph density (high average degree = slow convergence)
SELECT
  AVG(degree) AS avg_degree,
  MAX(degree) AS max_degree
FROM (
  SELECT left_entity_uid, COUNT(*) AS degree
  FROM `project.er_silver.all_matched_pairs`
  GROUP BY left_entity_uid
);
```

**Remediation:**
- Increase `max_iterations` in clustering config:
  ```yaml
  reconciliation:
    clustering:
      max_iterations: 50  # default: 20
  ```
- Tighten blocking to reduce candidate pairs (fewer edges = faster convergence)
- Raise threshold to remove weak edges from the cluster graph
- Enable confidence shaping to penalize hub nodes:
  ```yaml
  reconciliation:
    clustering:
      confidence_shaping:
        hub_node_detection: true
        hub_degree_threshold: 15
  ```

### 5. Slow Incremental Processing

**Symptoms:**
- Incremental batches take as long as full refresh
- Watermark not advancing
- Same records processed repeatedly

**Diagnostic queries:**
```sql
-- Check current watermark position
SELECT * FROM `project.er_meta.watermarks`
WHERE is_current = TRUE;

-- Check unprocessed record count
SELECT COUNT(*) AS pending
FROM `project.raw.source_table`
WHERE updated_at > (
  SELECT cursor_value FROM `project.er_meta.watermarks`
  WHERE cursor_column = 'updated_at' AND is_current = TRUE
);
```

**Remediation:**
- Ensure `updated_at` column is indexed/clustered in the source table
- Use composite cursors for large tables with duplicate timestamps:
  ```yaml
  incremental:
    cursor_columns: [updated_at, record_id]
    cursor_mode: ordered
  ```
- Enable drain mode to process all pending batches:
  ```yaml
  incremental:
    drain_mode: true
    drain_max_iterations: 50
    batch_size: 1_000_000
  ```
- Run `bq-er profile-cursors --config config.yml` to find the optimal cursor strategy

---

## Key Tuning Parameters

| Parameter | Location | Default | Description |
|-----------|----------|---------|-------------|
| `threshold.min_score` | `matching_tiers[].threshold` | 5.0 | Minimum score to accept a match. Higher = fewer false positives, lower = fewer false negatives |
| `candidate_limit` | `blocking.paths[]` | 200 | Max candidate pairs per entity per blocking path. Caps pair explosion |
| `bucket_size_limit` | `blocking.paths[]` | 10,000 | Max entities per blocking bucket. Buckets exceeding this are dropped |
| `batch_size` | `incremental` | 1,000,000 | Records per incremental batch. Larger = fewer batches but more memory |
| `max_iterations` | `reconciliation.clustering` | 20 | Max connected components iterations. Increase for dense graphs |
| `max_bytes_billed` | `scale` | None | BigQuery cost ceiling in bytes. Pipeline aborts if exceeded |
| `drain_max_iterations` | `incremental` | 100 | Safety cap on drain mode loops |
| `sample_size` | `parameter_estimation` | 10,000 | Pairs sampled for EM estimation. Larger = more accurate m/u but slower |
| `convergence_threshold` | `parameter_estimation` | 0.001 | EM convergence delta. Smaller = more iterations but more precise |
| `comparison weight` | `matching_tiers[].comparisons[]` | 1.0 | Score contribution of each comparison. Sum of weights = max possible score |

### Quick Calibration Workflow

1. Start with default thresholds and run on a sample
2. Inspect `all_matched_pairs` — sort by `match_total_score` ascending
3. Find the score where matches become clearly wrong (false positives)
4. Set `min_score` just above that boundary
5. Check singleton ratio in clusters — if >90%, lower threshold or add blocking paths
6. Enable score banding to separate confident matches from borderline cases

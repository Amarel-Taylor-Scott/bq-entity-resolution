# Match-Quality Opportunities (Leaderboard Score Roadmap)

> Generated 2026-06-20 from a two-model adversarial review (deep match-quality
> lens + SOTA-gap lens) of the matching, blocking, scoring, and clustering paths.
> Oriented toward raising entity-resolution **precision/recall/F1** — the metrics
> behind a Kaggle-style public/private leaderboard. Each item is file-grounded.

Legend — Effort: S/M/L · Impact: High/Med/Low · Lever: Recall ↑ / Precision ↑ / Calibration.

## Already addressed in the leaf build-out

- **Wire `leaf.scoring` → production scorer.** `leaf.scoring` was declared but
  never read; the leaf stage always used the lightweight `GREATEST` scorer and
  `build_leaf_candidates_sql` was dead code. **Done:** leaves now route to the
  production `sum`/`fellegi_sunter` engine (soft signals, hard negatives,
  banding, TF) against a blocking-only candidate table, with per-side source
  tables (featured × canonical_index). `greatest` remains an explicit fast
  pre-screen. (`stages/leaf_resolution.py`, `sql/builders/leaf.py`,
  `sql/builders/comparison/{models,sum_scoring,fellegi_sunter}.py`)

## Top priorities (highest ROI first)

| # | Opportunity | Lever | Effort | Impact | Where |
|---|---|---|---|---|---|
| 1 | **Blocking recall gap** — only exact equi-join blocking. Add q-gram/token (UNNEST inverted index), phonetic (soundex/metaphone), and sorted-neighborhood blocking paths. A true pair absent from every block is unrecoverable. | Recall | M | High | `sql/builders/blocking.py`, `features/blocking_keys.py`, `blocking/lsh.py` |
| 2 | **Connected-components over-merge** — CC/incremental clustering ignore `min_cluster_confidence`; every above-threshold edge is a hard transitive merge. One false bridge edge collapses two true clusters. Add a confidence/band floor on merge edges + a bridge/cluster-size guard. | Precision | S (floor) / L (corr. clustering) | High | `stages/clustering.py`, `sql/builders/clustering/{connected_components,incremental}.py` |
| 3 | **Correlation clustering (greedy GAEC)** — weight-aware partitioning that cuts contradictory edges (A–B, B–C high but A–C low). New method alongside CC/star/best_match. | Precision | M | High | new `sql/builders/clustering/correlation.py` + `ClusteringConfig.method` |
| 4 | **Multi-level comparisons in sum scoring** — `ComparisonLevelDef` (m/u/levels) only used by F-S; sum scoring is binary 0/1. Emit weighted CASE levels (exact/high/med/low/null). Config already supports it. | Precision/Recall | S | High | `stages/matching.py:_plan_sum_scoring`, `sql/builders/comparison/sum_scoring.py` |
| 5 | **Score calibration (isotonic/Platt)** — raw F-S log-odds / `score÷max` are miscalibrated when blocking is non-random, so fixed thresholds are mis-placed. Fit calibration on labels (BQML `LOGISTIC_REG`/isotonic) → calibrated `match_confidence`. | Calibration | M | High | new `stages/calibration.py`, `sql/builders/comparison/calibration.py` |
| 6 | **EM sample bias + non-exclusive levels** — EM u-estimates come only from *blocked* pairs (biased up) and every level inits to (m=.9,u=.1) and is treated as independent (double-counts evidence). Stratify the sample (random + near-threshold) and make levels mutually exclusive + monotone priors. | Calibration | M | Med-High | `sql/builders/em.py` |
| 7 | **One-sided / mis-specified TF adjustment** — TF join keys only `l.<col>`; weight uses `log2(m) − log2(max(u,tf))` (not a likelihood ratio). Use both-side frequency and the proper F-S frequency form `log2(m/u_value)`. | Precision | M | High | `sql/builders/comparison/{fellegi_sunter,signals}.py` |
| 8 | **Hard-negative mining** — AL is uncertainty-only. Mine top-scoring *rejected* candidates (confusable non-matches) for labeling + EM. | Calibration | S | High | `sql/builders/active_learning.py`, `sql/builders/em.py` |

## Per-stratum (leaf) precision/recall

| # | Opportunity | Lever | Effort | Impact | Where |
|---|---|---|---|---|---|
| 9 | **Carry `match_confidence`/`match_band` through the leaf union** so the clustering confidence floor (#2) and per-stratum gates can act on leaf-produced edges. Today the union drops them. | Precision | S | Med-High | `stages/leaf_resolution.py:_build_union_sql` |
| 10 | **Per-stratum thresholds + new×old short-circuit defaults** — synthesize new×old with email/phone/national-id `exact_key_short_circuit`; give old×old a conservative `threshold_override` and a low per-stratum `log_prior_odds`. A false old×old merge is maximally damaging. | Precision/Recall | M | Med | `config/models/leaves.py`, `stages/leaf_resolution.py` |
| 11 | **Entity-level (aggregated) comparison for new×old** — compare new-raw against canonical *aggregated* features (most-frequent / value-set membership) and reuse canonical precomputed blocking keys. | Precision | M | Med | `stages/leaf_resolution.py` |

## Feature / comparison coverage

| # | Opportunity | Lever | Effort | Impact | Where |
|---|---|---|---|---|---|
| 12 | **N-gram / MinHash blocking keys** (`ngram_fingerprint`, UNNEST) for noisy text. | Recall | S | Med | `features/blocking_keys.py` |
| 13 | **Configurable nickname/name-variant map** (YAML) — replace hard-coded ~60 English pairs; add phonetic blocking beyond the fixed list. | Recall | S | Med | `features/name_features.py`, `config/models/features.py` |
| 14 | **Address component multi-field comparison** (number/street/city/state/zip weighted rollup). | Precision/Recall | M | Med-High | `matching/comparisons/composite_comparisons.py` |
| 15 | **Transliteration / Unicode normalization** (Cyrillic/Arabic/CJK → Latin, NFKC). | Recall | S-M | Med (intl) | `features/name_features.py` |

## Tuning / ensembling

| # | Opportunity | Lever | Effort | Impact | Where |
|---|---|---|---|---|---|
| 16 | **Monotone threshold optimization** — `bq-er estimate-threshold` sweeps a P/R grid on labels → F1-optimal threshold. | Calibration | S-M | Med | new `cli/commands/estimate_threshold.py` |
| 17 | **Rule + BQML ensemble score** — blend `rule_confidence` and ML probability (the BQML stage already emits both). | Precision | S | Med | new `sql/builders/comparison/ensemble.py` |
| 18 | **Cluster coherence score → review queue** — route low-coherence clusters (`AVG/STDDEV(confidence)`) to review; catches transitive-closure errors per-pair sampling misses. | Precision | M | Med | `sql/builders/clustering/metrics.py` |
| 19 | **Fix blocking metrics** — reduction-ratio denominator wrong for cross-batch link; "precision" is acceptance rate, not pair-completeness. Add pairs-completeness (recall) vs labels, per leaf. | Diagnostic | S | Med | `sql/builders/blocking.py` |

**Suggested order for a leaderboard push:** #1 + #2 (set the recall ceiling and
fix the dominant precision failure) → #4 + #9/#10 (real per-stratum scoring) →
#5/#6/#7 (calibration) → the rest as time allows.

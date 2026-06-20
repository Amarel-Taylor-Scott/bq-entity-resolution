# Matching Package

## Purpose

Comparison function registry, scoring strategies (sum, Fellegi-Sunter), signal framework (hard negatives/positives, soft signals), active learning, and term frequency adjustment. Drives the core matching logic of the pipeline.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Barrel import for comparison registry. |
| `parameters.py` | **Fellegi-Sunter parameters**: m/u probabilities, log-weights, EM estimation config. |
| `hard_negatives.py` | Hard negative signal logic: 4 severity levels (hn1_critical → hn4_contextual), entity_type_condition gating. |
| `soft_signals.py` | Soft signal definitions: category, weight, entity_type_condition, params. |
| `active_learning.py` | Active learning review queue generation: uncertain pairs near decision threshold. |

## Sub-Package: `comparisons/`

49 comparison functions via `@register` across 7 domain modules:

| File | Methods |
|------|---------|
| `string_comparisons.py` | `exact`, `jaro_winkler`, `levenshtein`, `soundex_match`, `metaphone_match`, `ngram_similarity`, etc. |
| `numeric_comparisons.py` | `numeric_exact`, `numeric_difference`, `numeric_ratio`, `numeric_range`. |
| `date_comparisons.py` | `date_exact`, `date_proximity`, `date_year_match`, `date_component_match`. |
| `geo_comparisons.py` | `geo_distance`, `geo_bucket_match`, `haversine_km`. |
| `null_comparisons.py` | `both_null`, `either_null`, `null_agreement`. |
| `composite_comparisons.py` | `all_match`, `any_match`, `weighted_ensemble`, `hierarchical_match`. |
| `token_comparisons.py` | `dice_coefficient`, `overlap_coefficient`, `monge_elkan`, `token_sort_ratio` (DISTINCT set semantics). |

## Architecture

```
MatchingStage.plan()
  ├── For each comparison in tier:
  │   ├── get_comparison_function(method)
  │   └── function(left, right, **params) → SQL CASE expression
  ├── Signal framework:
  │   ├── Hard negatives → disqualify/penalize
  │   ├── Hard positives → boost/auto_match/elevate_band
  │   └── Soft signals → adjust score
  ├── Scoring:
  │   ├── Sum scoring → SUM(weights)
  │   └── Fellegi-Sunter → log-likelihood ratios
  └── Score banding → HIGH/MEDIUM/LOW/REJECT
```

## Key Patterns

- **`@register("method")` decorator** — same pattern as features. Thread-safe, warns on duplicates.
- **Comparison functions use `l.` / `r.` aliases** — hardcoded for left/right candidate pair tables.
- **`COMPARISON_COSTS` dict** — ranks methods by relative compute cost (1-50) for blocking path optimization.
- **Entity type gating** — `entity_type_condition` wraps signal SQL with `(l.<col> = 'VALUE' AND r.<col> = 'VALUE' AND ...)` guard.
- **Global + tier signals** — `effective_hard_negatives()` merges global and per-tier definitions.
- **Severity-aware behavior** — `hn4_contextual` forced to "penalize" (never disqualify).

## Dependencies

- `config/models/matching.py` — ComparisonDef, HardNegativeDef, SoftSignalDef, etc.
- `sql/builders/comparison/` — SQL generation for scoring
- `sql/builders/em.py` — EM parameter estimation SQL

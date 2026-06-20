"""
Comparison function registry.

Maps comparison method names to BigQuery SQL expression generators.
Each function generates a boolean SQL expression comparing left and right columns.

Usage in YAML:
  comparisons:
    - left: "first_name_clean"
      right: "first_name_clean"
      method: "levenshtein"
      params: {max_distance: 2}

BigQuery Comparison Performance Notes
======================================
Comparison functions are evaluated PER CANDIDATE PAIR in the scoring stage.
If blocking produces 10M candidate pairs, each comparison runs 10M times.
The cost difference between comparison methods is therefore amplified by
the number of candidates:

    Cost tier 1  (INT64 equality):          ~0.001 slot-seconds per 1M pairs
    Cost tier 2  (short STRING equality):   ~0.003 slot-seconds per 1M pairs
    Cost tier 3  (EDIT_DISTANCE):           ~0.05  slot-seconds per 1M pairs
    Cost tier 4  (JS UDF jaro_winkler):     ~0.5   slot-seconds per 1M pairs
    Cost tier 5  (ML.DISTANCE cosine):      ~1.0   slot-seconds per 1M pairs

Key optimization: When columns being compared are INT64 (e.g., pre-computed
FARM_FINGERPRINT features), "exact" comparisons use INT64 = INT64 which is
a single 8-byte comparison. When columns are STRING, BQ must compare
byte-by-byte. For high-volume matching, pre-compute fingerprints of
cleaned values and do INT64 exact-match before expensive fuzzy comparisons.

The COMPARISON_COSTS dict below ranks methods by relative cost. SQL builders
should order comparisons cheapest-first so BigQuery's short-circuit
evaluation can skip expensive comparisons when cheap ones already fail.
"""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable
from typing import Any

from bq_entity_resolution.sql.utils import validate_identifier

logger = logging.getLogger(__name__)

ComparisonFunction = Callable[..., str]

COMPARISON_FUNCTIONS: dict[str, ComparisonFunction] = {}

_plugins_loaded = False
_lock = threading.Lock()

# Relative cost of each comparison method (lower = cheaper).
# SQL builders should sort comparisons by this cost so that BigQuery
# evaluates cheap comparisons first. In CASE WHEN chains, BQ can
# short-circuit: if an early cheap check fails, expensive checks
# are never evaluated for that pair.
#
# IMPORTANT: The actual cost depends on the column TYPE being compared:
#   - "exact" on INT64 columns (e.g. fp_ fingerprints):  cost ~1
#   - "exact" on short STRING columns (e.g. state):       cost ~2
#   - "exact" on long STRING columns (e.g. full address): cost ~5
# The costs below assume typical column types. Pre-computing
# FARM_FINGERPRINT features effectively moves STRING comparisons
# from cost tier 2 down to cost tier 1.
COMPARISON_COSTS: dict[str, int] = {
    # Tier 1: O(1) integer/hash/null comparisons — 8-byte fixed-width
    # These are essentially free. INT64 = INT64 is a single CPU instruction.
    "exact": 1,
    "exact_or_null": 1,
    "different": 1,
    "null_either": 1,
    "numeric_within": 1,       # ABS(INT64 - INT64) — fast arithmetic
    "date_within_days": 1,     # DATE_DIFF — fast on DATE type (INT32 internal)
    "date_within_months": 1,   # DATE_DIFF MONTH — same cost as days
    "date_within_years": 1,    # DATE_DIFF YEAR — same cost as days
    "exact_case_insensitive": 2,  # UPPER() per row adds STRING allocation
    "length_mismatch": 2,     # CHAR_LENGTH → INT64 comparison
    "length_ratio": 2,         # LEAST/GREATEST CHAR_LENGTH + division
    "length_ratio_score": 2,
    "numeric_ratio": 2,       # SAFE_DIVIDE on FLOAT64 — fast arithmetic
    "numeric_ratio_score": 2,
    "numeric_percent_diff": 2, # ABS + SAFE_DIVIDE — fast arithmetic
    "age_difference": 2,       # Two DATE_DIFFs + subtraction
    "date_overlap": 2,         # Four date comparisons — all INT32
    "date_overlap_score": 3,   # Date arithmetic + GREATEST/LEAST + division
    # Tier 2: simple string ops — O(n) where n = string length
    "soundex_match": 3,        # SOUNDEX computes 4-char code, then STRING =
    "starts_with": 5,          # STARTS_WITH — prefix scan, early exit
    "contains": 5,             # STRPOS — substring scan both directions
    "abbreviation_match": 5,   # STARTS_WITH + CHAR_LENGTH
    "exact_diacritics_insensitive": 5,  # NORMALIZE(NFD) + REGEXP_REPLACE per pair
    "regex_match": 5,          # REGEXP_CONTAINS — regex engine per value
    # Tier 3: O(n*m) edit distance — quadratic in string length
    # For a 20-char name, this is ~400 character comparisons per pair.
    "levenshtein": 10,
    "levenshtein_normalized": 12,  # edit_distance + division
    "levenshtein_score": 12,
    "levenshtein_length_aware": 12,       # EDIT_DISTANCE + LEAST division
    "levenshtein_length_aware_score": 12,
    # Tier 4: UDF calls (JS execution overhead ~10-50x native)
    # Each call serializes data to V8 JS engine and back.
    "metaphone_match": 15,     # JS UDF called twice (left + right)
    "double_metaphone_match": 15,  # JS UDF called 4x (primary + alternate)
    "initials_match": 15,      # UNNEST + STRING_AGG subquery per side
    "jaccard_ngram": 15,       # Character n-gram Jaccard — UNNEST + COUNTIF
    "jaccard_ngram_score": 15,
    "jaro_winkler": 20,        # JS UDF — most expensive string comparison
    "jaro_winkler_score": 20,
    # Tier 5: complex subqueries / ML / geo — avoid at scale if possible
    "geo_within_km": 25,       # ST_DISTANCE — geodesic math per pair
    "geo_distance_score": 25,
    "token_set_match": 30,     # UNNEST + IN + COUNTIF subquery per pair
    "token_set_score": 30,
    "manhattan_distance": 45,  # ML.DISTANCE MANHATTAN — L1 norm on arrays
    "manhattan_distance_score": 45,
    "cosine_similarity": 50,   # ML.DISTANCE COSINE — vector math on FLOAT64 arrays
    "cosine_similarity_score": 50,
    "euclidean_distance": 50,  # ML.DISTANCE EUCLIDEAN — L2 norm on arrays
    "euclidean_distance_score": 50,
    # Tier 5 (continued): token-based comparisons — correlated UNNEST subqueries
    "token_sort_ratio": 25,       # ARRAY sort + EDIT_DISTANCE on sorted strings
    "token_sort_ratio_score": 25,
    "dice_coefficient": 30,       # SPLIT + UNNEST + COUNTIF intersection per pair
    "dice_coefficient_score": 30,
    "overlap_coefficient": 30,    # SPLIT + UNNEST + COUNTIF / MIN(|A|, |B|)
    "overlap_coefficient_score": 30,
    "monge_elkan": 35,            # Nested UNNEST + CROSS JOIN + EDIT_DISTANCE
    "monge_elkan_score": 35,
}


def register(name: str) -> Callable[[ComparisonFunction], ComparisonFunction]:
    """Decorator to register a comparison function.

    Can be used by external packages to add custom comparison methods::

        from bq_entity_resolution import register_comparison

        @register_comparison("my_similarity")
        def my_similarity(left: str, right: str, **_: Any) -> str:
            return f"(l.{left} = r.{right})"

    The function is then available in YAML config::

        comparisons:
          - left: col_a
            right: col_a
            method: my_similarity
            weight: 3.0

    External packages can also auto-register via entry_points::

        [project.entry-points."bq_er.comparisons"]
        my_pkg = "my_pkg.comparisons"
    """

    def decorator(func: ComparisonFunction) -> ComparisonFunction:
        @functools.wraps(func)
        def _validated_wrapper(left: str, right: str, **kwargs: Any) -> str:
            validate_identifier(left, "comparison left column")
            validate_identifier(right, "comparison right column")
            return func(left=left, right=right, **kwargs)

        with _lock:
            if name in COMPARISON_FUNCTIONS:
                logger.warning(
                    "Comparison function '%s' registered by %s is being "
                    "overwritten by %s",
                    name,
                    getattr(COMPARISON_FUNCTIONS[name], "__module__", "?"),
                    getattr(func, "__module__", "?"),
                )
            COMPARISON_FUNCTIONS[name] = _validated_wrapper
        return _validated_wrapper

    return decorator


def load_comparison_plugins() -> None:
    """Discover and load comparison function plugins from entry_points.

    Called automatically on first registry miss during config validation.
    Safe to call multiple times — only loads once. Thread-safe.
    """
    global _plugins_loaded
    with _lock:
        if _plugins_loaded:
            return
        _plugins_loaded = True

    try:
        from importlib.metadata import entry_points
    except ImportError:
        return

    try:
        eps = entry_points(group="bq_er.comparisons")
    except TypeError:
        all_eps = entry_points()
        eps = all_eps.get("bq_er.comparisons", [])  # type: ignore[arg-type]

    for ep in eps:
        try:
            ep.load()
            logger.debug("Loaded comparison plugin '%s'", ep.name)
        except Exception as exc:
            logger.warning("Failed to load comparison plugin '%s': %s", ep.name, exc)


# Comparison methods that require BigQuery JavaScript UDFs.
# Used by config validation to reject these methods when allow_udfs=False.
UDF_COMPARISON_METHODS: frozenset[str] = frozenset({
    "jaro_winkler",
    "jaro_winkler_score",
    "metaphone_match",
    "double_metaphone_match",
})

# UDF dataset placeholder — replaced at SQL generation time by the matching engine
# when it resolves the {udf_dataset} variable from config
_UDF_DATASET_PLACEHOLDER = "{udf_dataset}"


def _validated_call(fn: Callable[..., str], left: str, right: str, **kwargs: Any) -> str:
    """Validate comparison inputs are safe SQL identifiers."""
    from bq_entity_resolution.sql.utils import validate_identifier

    validate_identifier(left, "comparison left column")
    validate_identifier(right, "comparison right column")
    return fn(left=left, right=right, **kwargs)


def get_comparison_safe(name: str) -> Callable[..., str]:
    """Get a comparison function with input validation.

    Returns a wrapped version of the comparison function that validates
    ``left`` and ``right`` are safe SQL identifiers before invoking the
    underlying function.  Raises ``KeyError`` if the comparison name is
    not registered.

    Example::

        fn = get_comparison_safe("levenshtein")
        sql = fn(left="first_name_clean", right="first_name_clean", max_distance=2)
    """
    fn = COMPARISON_FUNCTIONS[name]

    def safe_fn(left: str, right: str, **kwargs: Any) -> str:
        return _validated_call(fn, left, right, **kwargs)

    safe_fn.__name__ = fn.__name__
    safe_fn.__doc__ = fn.__doc__
    return safe_fn


__all__ = [
    "COMPARISON_COSTS",
    "COMPARISON_FUNCTIONS",
    "ComparisonFunction",
    "UDF_COMPARISON_METHODS",
    "_validated_call",
    "get_comparison_safe",
    "load_comparison_plugins",
    "register",
]

# Import sub-modules to trigger @register decorators
import bq_entity_resolution.matching.comparisons.composite_comparisons  # noqa: E402, F401
import bq_entity_resolution.matching.comparisons.date_comparisons  # noqa: E402, F401
import bq_entity_resolution.matching.comparisons.geo_comparisons  # noqa: E402, F401
import bq_entity_resolution.matching.comparisons.null_comparisons  # noqa: E402, F401
import bq_entity_resolution.matching.comparisons.numeric_comparisons  # noqa: E402, F401
import bq_entity_resolution.matching.comparisons.string_comparisons  # noqa: E402, F401
import bq_entity_resolution.matching.comparisons.token_comparisons  # noqa: E402, F401

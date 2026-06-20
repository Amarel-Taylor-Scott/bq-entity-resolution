"""
String comparison functions.

Includes exact matching, edit distance, Jaro-Winkler, phonetic,
token-based, and string containment comparisons.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import (
    _UDF_DATASET_PLACEHOLDER,
    register,
)

# ---------------------------------------------------------------------------
# Exact matching
# ---------------------------------------------------------------------------
# PERF: "exact" is the cheapest comparison. Its real-world cost depends
# entirely on the column type:
#   INT64 columns (fp_ fingerprints, entity_uid): ~1 CPU instruction
#   DATE columns: ~1 instruction (stored as INT32 internally)
#   STRING columns: O(n) byte-by-byte, plus NULL check overhead
#
# Strategy: For columns that will be exact-matched, pre-compute
# FARM_FINGERPRINT in the feature pass. Then "exact" on the fp_ column
# runs at INT64 speed regardless of the original string length.
#
# Example: Instead of exact-matching on 'address_standardized' (STRING),
# add a feature: FARM_FINGERPRINT(address_standardized) as fp_address,
# then exact-match on fp_address (INT64). Same semantics, 3-5x faster.


@register("exact")
def exact(left: str, right: str, **_: Any) -> str:
    """Exact equality (both non-null).

    COST: 1 (INT64 columns) to 5 (long STRING columns).
    For STRING columns, consider comparing their FARM_FINGERPRINT instead.
    """
    return f"(l.{left} = r.{right} AND l.{left} IS NOT NULL)"


@register("exact_case_insensitive")
def exact_ci(left: str, right: str, **_: Any) -> str:
    """Case-insensitive exact equality."""
    return f"(UPPER(l.{left}) = UPPER(r.{right}) AND l.{left} IS NOT NULL)"


@register("exact_or_null")
def exact_or_null(left: str, right: str, **_: Any) -> str:
    """Match if equal or if either is null (permissive)."""
    return f"(l.{left} = r.{right} OR l.{left} IS NULL OR r.{right} IS NULL)"


@register("exact_diacritics_insensitive")
def exact_diacritics_insensitive(left: str, right: str, **_: Any) -> str:
    """Exact match after stripping diacritics (accented characters).

    Handles international names: "Muller" = "Muller", "Jose" = "Jose".
    Uses NORMALIZE + REGEXP_REPLACE to strip combining marks (NFD form).

    COST: 5 -- Unicode normalization + regex per pair.
    Pre-compute remove_diacritics() as a feature for better performance.
    """
    def _strip(col: str) -> str:
        return (
            f"REGEXP_REPLACE(NORMALIZE({col}, NFD), "
            f"r'\\\\p{{M}}', '')"
        )
    return (
        f"(UPPER({_strip(f'l.{left}')}) = UPPER({_strip(f'r.{right}')}) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


# ---------------------------------------------------------------------------
# Edit distance
# ---------------------------------------------------------------------------
# PERF: EDIT_DISTANCE is O(n*m) where n,m are string lengths. For a
# 20-char name, that's ~400 operations per pair. At 10M candidate pairs,
# this becomes significant. Two optimization strategies:
#   1. Place exact/soundex comparisons BEFORE levenshtein in the
#      comparison list so BQ can short-circuit pairs that already match.
#   2. Pre-filter with cheap comparisons (length_mismatch, first_letter)
#      as hard negatives to disqualify pairs before edit distance runs.


@register("levenshtein")
def levenshtein(left: str, right: str, max_distance: int = 2, **_: Any) -> str:
    """Edit distance within threshold (BigQuery EDIT_DISTANCE).

    COST: 10 -- O(n*m) per pair. Pre-filter with length_mismatch to skip
    pairs where |len(l) - len(r)| > max_distance (guaranteed no match).
    """
    return (
        f"(EDIT_DISTANCE(l.{left}, r.{right}) <= {max_distance} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("levenshtein_normalized")
def levenshtein_normalized(
    left: str, right: str, threshold: float = 0.8, **_: Any
) -> str:
    """Normalized edit distance similarity >= threshold."""
    return (
        f"(1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE(l.{left}, r.{right}) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right}))"
        f") >= {threshold} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("levenshtein_score")
def levenshtein_score(left: str, right: str, **_: Any) -> str:
    """Returns normalized edit distance similarity as a score (not boolean)."""
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"THEN 1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE(l.{left}, r.{right}) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right}))) "
        f"ELSE 0.0 END"
    )


@register("levenshtein_length_aware")
def levenshtein_length_aware(
    left: str, right: str, threshold: float = 0.8, **_: Any
) -> str:
    """Length-aware normalized edit distance similarity >= threshold.

    Unlike ``levenshtein_normalized`` which divides by GREATEST(len_l, len_r),
    this divides by the LEAST (shorter string). This is stricter: a 2-char
    edit on a 4-char string (50%) is penalized more than on a 20-char string (10%).

    Use this when short strings should require near-exact matches but long
    strings can tolerate more edits. Particularly important for names where
    "Jo" vs "Joe" (1 edit / 2 chars = 50% error) is much less reliable than
    "Christopher" vs "Christophor" (1 edit / 11 chars = 9% error).

    COST: 12 -- same as levenshtein_normalized.
    """
    return (
        f"(1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE(l.{left}, r.{right}) AS FLOAT64), "
        f"LEAST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right}))"
        f") >= {threshold} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND CHAR_LENGTH(l.{left}) > 0 AND CHAR_LENGTH(r.{right}) > 0)"
    )


@register("levenshtein_length_aware_score")
def levenshtein_length_aware_score(left: str, right: str, **_: Any) -> str:
    """Length-aware normalized edit distance as a score.

    Divides by LEAST(len_l, len_r) — stricter than levenshtein_score
    which divides by GREATEST. A 2-char edit on a 3-char string scores
    much lower (0.33) than on a 20-char string (0.90).

    COST: 12.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"AND CHAR_LENGTH(l.{left}) > 0 AND CHAR_LENGTH(r.{right}) > 0 "
        f"THEN 1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE(l.{left}, r.{right}) AS FLOAT64), "
        f"LEAST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right}))) "
        f"ELSE 0.0 END"
    )


@register("length_ratio")
def length_ratio(left: str, right: str, threshold: float = 0.6, **_: Any) -> str:
    """String length ratio check: LEAST(len) / GREATEST(len) >= threshold.

    A fast pre-filter to eliminate pairs with very different string lengths
    before running expensive edit distance or Jaro-Winkler. Names of very
    different lengths (e.g., "Al" vs "Alexander") rarely refer to the same
    entity.

    COST: 2 -- only CHAR_LENGTH + division, no character comparison.
    """
    return (
        f"(SAFE_DIVIDE("
        f"CAST(LEAST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right})) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right}))"
        f") >= {threshold} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("length_ratio_score")
def length_ratio_score(left: str, right: str, **_: Any) -> str:
    """String length ratio as a score: LEAST(len) / GREATEST(len).

    Returns 1.0 for equal lengths, decreasing as lengths diverge.

    COST: 2.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"THEN SAFE_DIVIDE("
        f"CAST(LEAST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right})) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH(l.{left}), CHAR_LENGTH(r.{right}))) "
        f"ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Jaro-Winkler
# ---------------------------------------------------------------------------
# PERF WARNING: Jaro-Winkler requires a BigQuery JS UDF, which is the
# slowest execution mode in BQ. Each call serializes the two strings to
# a V8 JS sandbox, computes the similarity, and serializes back. This is
# ~20-50x slower than native BQ functions like EDIT_DISTANCE.
#
# Optimization strategies:
#   1. Use jaro_winkler ONLY in later tiers (fuzzy matching), not tier 1.
#   2. Place cheap comparisons (exact, soundex) before jaro_winkler.
#   3. Use tight blocking to minimize candidate pairs reaching this stage.
#   4. Consider levenshtein_normalized as a native alternative (cost: 12).


@register("jaro_winkler")
def jaro_winkler(
    left: str, right: str, threshold: float = 0.85, udf_dataset: str = "", **_: Any
) -> str:
    """Jaro-Winkler similarity >= threshold (BigQuery JS UDF).

    COST: 20 -- JS UDF overhead. Use only when edit distance is insufficient.
    """
    ds = udf_dataset or _UDF_DATASET_PLACEHOLDER
    return (
        f"(`{ds}.jaro_winkler`(l.{left}, r.{right}) >= {threshold} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("jaro_winkler_score")
def jaro_winkler_score(
    left: str, right: str, udf_dataset: str = "", **_: Any
) -> str:
    """Jaro-Winkler similarity score (BigQuery JS UDF)."""
    ds = udf_dataset or _UDF_DATASET_PLACEHOLDER
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"THEN `{ds}.jaro_winkler`(l.{left}, r.{right}) "
        f"ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Phonetic matching
# ---------------------------------------------------------------------------


@register("soundex_match")
def soundex_match(left: str, right: str, **_: Any) -> str:
    """Soundex codes match.

    COST: 3 -- SOUNDEX is a native BQ function, fast per row.
    PERF NOTE: SOUNDEX is computed INLINE per pair here. If soundex is also
    used as a blocking key, the value is already stored as a feature column.
    In that case, using "exact" on the pre-computed soundex column is faster
    than re-computing SOUNDEX per pair. Even better: pre-compute
    FARM_FINGERPRINT(SOUNDEX(col)) for INT64 exact match (cost: 1).
    """
    return (
        f"(SOUNDEX(l.{left}) = SOUNDEX(r.{right}) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


# ---------------------------------------------------------------------------
# Phonetic comparisons (UDF-based)
# ---------------------------------------------------------------------------
# PERF WARNING: These call JS UDFs per pair (2 calls for metaphone_match,
# 4 calls for double_metaphone_match). At 10M pairs, that's 20-40M UDF
# invocations. Optimization: pre-compute metaphone as a feature column
# in the feature pass, then use "exact" on the stored metaphone column
# (STRING comparison, cost: 3) instead of re-computing the UDF per pair.
# Even better: FARM_FINGERPRINT(metaphone(col)) -> INT64 exact match (cost: 1).


@register("metaphone_match")
def metaphone_match(
    left: str, right: str, udf_dataset: str = "", **_: Any
) -> str:
    """Metaphone codes match (BigQuery JS UDF).

    Requires a ``metaphone(STRING) -> STRING`` UDF in udf_dataset.

    COST: 15 -- two JS UDF calls per pair. Pre-compute as feature for
    massive cost reduction.
    """
    ds = udf_dataset or _UDF_DATASET_PLACEHOLDER
    return (
        f"(`{ds}.metaphone`(l.{left}) = `{ds}.metaphone`(r.{right}) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("double_metaphone_match")
def double_metaphone_match(
    left: str, right: str, udf_dataset: str = "", **_: Any
) -> str:
    """Double Metaphone match: primary or alternate codes overlap.

    Requires ``double_metaphone_primary(STRING) -> STRING`` and
    ``double_metaphone_alternate(STRING) -> STRING`` UDFs in udf_dataset.
    """
    ds = udf_dataset or _UDF_DATASET_PLACEHOLDER
    return (
        f"((`{ds}.double_metaphone_primary`(l.{left}) = "
        f"`{ds}.double_metaphone_primary`(r.{right}) "
        f"OR `{ds}.double_metaphone_primary`(l.{left}) = "
        f"`{ds}.double_metaphone_alternate`(r.{right}) "
        f"OR `{ds}.double_metaphone_alternate`(l.{left}) = "
        f"`{ds}.double_metaphone_primary`(r.{right})) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


# ---------------------------------------------------------------------------
# String containment
# ---------------------------------------------------------------------------


@register("contains")
def contains(left: str, right: str, **_: Any) -> str:
    """Left value contains right value (or vice versa)."""
    return (
        f"((STRPOS(l.{left}, r.{right}) > 0 OR STRPOS(r.{right}, l.{left}) > 0) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("starts_with")
def starts_with(left: str, right: str, **_: Any) -> str:
    """Left value starts with right value."""
    return (
        f"(STARTS_WITH(l.{left}, r.{right}) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("abbreviation_match")
def abbreviation_match(left: str, right: str, **_: Any) -> str:
    """Match where one value is an abbreviation of another.

    E.g., 'J' matches 'JAMES', 'ROBT' matches 'ROBERT'.
    """
    return (
        f"((STARTS_WITH(UPPER(l.{left}), UPPER(r.{right})) "
        f"  OR STARTS_WITH(UPPER(r.{right}), UPPER(l.{left}))) "
        f"AND CHAR_LENGTH(LEAST(l.{left}, r.{right})) >= 1 "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


# ---------------------------------------------------------------------------
# Token-based matching (handles transpositions at the word level)
# ---------------------------------------------------------------------------
# PERF: token_set_match uses correlated subqueries with UNNEST + IN per pair.
# This is expensive at scale (~30 cost units). For name transpositions,
# consider the cheaper alternative: pre-compute sorted_name_fingerprint
# (INT64) in the feature pass, then use "exact" on the fingerprint (cost: 1).
# sorted_name_fingerprint('Smith John') == sorted_name_fingerprint('John Smith')
# because both sort to 'JOHN SMITH' before FARM_FINGERPRINT hashing.


@register("token_set_match")
def token_set_match(left: str, right: str, min_overlap: float = 0.5, **_: Any) -> str:
    """Token overlap ratio >= threshold. Handles name word transpositions.

    Computes |intersection| / |union| of word tokens (Jaccard similarity).
    Uses inclusion-exclusion (|A| + |B| - |A^B|) to avoid redundant SPLIT calls.

    COST: 30 -- correlated subqueries per pair. For simple transpositions,
    prefer sorted_name_fingerprint + exact match (cost: 1) instead.
    """
    return (
        f"(SAFE_DIVIDE("
        f"  (SELECT COUNTIF(w IN UNNEST(SPLIT(UPPER(r.{right}), ' '))) "
        f"   FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) AS w),"
        f"  ARRAY_LENGTH(SPLIT(UPPER(l.{left}), ' ')) + "
        f"  ARRAY_LENGTH(SPLIT(UPPER(r.{right}), ' ')) - "
        f"  (SELECT COUNTIF(w IN UNNEST(SPLIT(UPPER(r.{right}), ' '))) "
        f"   FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) AS w)"
        f") >= {min_overlap} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("token_set_score")
def token_set_score(left: str, right: str, **_: Any) -> str:
    """Token overlap ratio as a score (Jaccard similarity of word tokens).

    Uses inclusion-exclusion (|A| + |B| - |A^B|) to avoid redundant SPLIT calls.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL THEN "
        f"SAFE_DIVIDE("
        f"  (SELECT COUNTIF(w IN UNNEST(SPLIT(UPPER(r.{right}), ' '))) "
        f"   FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) AS w),"
        f"  ARRAY_LENGTH(SPLIT(UPPER(l.{left}), ' ')) + "
        f"  ARRAY_LENGTH(SPLIT(UPPER(r.{right}), ' ')) - "
        f"  (SELECT COUNTIF(w IN UNNEST(SPLIT(UPPER(r.{right}), ' '))) "
        f"   FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) AS w)"
        f") ELSE 0.0 END"
    )


@register("initials_match")
def initials_match(left: str, right: str, **_: Any) -> str:
    """Check if initials of two names match (e.g., 'J.S.' matches 'John Smith')."""
    return (
        f"((SELECT STRING_AGG(LEFT(w, 1), '' ORDER BY pos) "
        f"  FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) w WITH OFFSET pos) = "
        f" (SELECT STRING_AGG(LEFT(w, 1), '' ORDER BY pos) "
        f"  FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) w WITH OFFSET pos) "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )

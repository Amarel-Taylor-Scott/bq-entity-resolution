"""
Token-based comparison functions.

Includes Dice coefficient, overlap coefficient, Monge-Elkan,
and token sort ratio comparisons. These operate on whitespace-delimited
tokens (words) within string values, providing robust matching for
multi-word fields like names, addresses, and descriptions.

BigQuery Token Comparison Performance Notes
============================================
All token-based comparisons use SPLIT + UNNEST patterns which create
correlated subqueries per candidate pair. At 10M candidate pairs, each
UNNEST subquery runs 10M times. Optimization strategies:

    1. Pre-compute sorted token fingerprints as INT64 features in the
       feature pass (FARM_FINGERPRINT of sorted tokens). Then use "exact"
       on the fingerprint column (cost: 1) instead of token_sort_ratio.
    2. Place cheap comparisons (exact, soundex) BEFORE token comparisons
       in the comparison list so BQ can short-circuit early matches.
    3. Use tight blocking to minimize candidate pairs reaching token
       comparisons.
    4. For simple word transpositions, token_sort_ratio (cost: 25) is
       cheaper than dice/overlap (cost: 30) because it avoids set
       intersection subqueries.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import register

# ---------------------------------------------------------------------------
# Dice coefficient (token-level)
# ---------------------------------------------------------------------------
# PERF: Dice coefficient uses SPLIT + UNNEST + COUNTIF(IN UNNEST(...))
# per pair. The intersection subquery is correlated, meaning it runs once
# per candidate pair. At scale, pre-compute sorted token fingerprints
# and use exact match instead.
#
# Dice = 2 * |intersection| / (|A| + |B|)
# Unlike Jaccard, Dice weights intersection double, making it more
# lenient for partial matches. Good for names where one side may have
# a middle name and the other does not.


@register("dice_coefficient")
def dice_coefficient(
    left: str, right: str, min_similarity: float = 0.5, **_: Any
) -> str:
    """Token Dice coefficient >= threshold.

    Dice = 2 * |intersection| / (|left_tokens| + |right_tokens|).
    More lenient than Jaccard for partial token overlap.

    COST: 30 -- correlated UNNEST subquery per pair.

    When to use: Multi-word fields (names, addresses) where partial
    token overlap is acceptable. Prefer over Jaccard when one side
    may have extra tokens (e.g., middle names).
    """
    return (
        f"(SAFE_DIVIDE("
        f"2 * (SELECT COUNTIF(w IN ("
        f"SELECT DISTINCT t FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)) "
        f"FROM ("
        f"SELECT DISTINCT t AS w FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t"
        f")), "
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t) + "
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)"
        f") >= {min_similarity} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("dice_coefficient_score")
def dice_coefficient_score(left: str, right: str, **_: Any) -> str:
    """Token Dice coefficient as a continuous score (0.0-1.0).

    Dice = 2 * |intersection| / (|left_tokens| + |right_tokens|).
    Uses set semantics (DISTINCT tokens) to avoid values > 1.0.

    COST: 30 -- correlated UNNEST subquery per pair.

    When to use: Scoring stage where you need a continuous similarity
    measure for multi-word fields. Returns 0.0 when either value is NULL.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL THEN "
        f"SAFE_DIVIDE("
        f"2 * (SELECT COUNTIF(w IN ("
        f"SELECT DISTINCT t FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)) "
        f"FROM ("
        f"SELECT DISTINCT t AS w FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t"
        f")), "
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t) + "
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)"
        f") ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Overlap coefficient (token-level)
# ---------------------------------------------------------------------------
# PERF: Same correlated subquery cost as Dice. Overlap coefficient uses
# MIN(|A|, |B|) in the denominator instead of |A| + |B|, making it
# robust to one side having many more tokens than the other.
#
# Overlap = |intersection| / MIN(|A|, |B|)
# This means if all tokens in the shorter string appear in the longer
# string, the overlap coefficient is 1.0 regardless of extra tokens.


@register("overlap_coefficient")
def overlap_coefficient(
    left: str, right: str, min_similarity: float = 0.5, **_: Any
) -> str:
    """Token overlap coefficient >= threshold.

    Overlap = |intersection| / MIN(|left_tokens|, |right_tokens|).
    Robust when one side has significantly more tokens than the other.

    COST: 30 -- correlated UNNEST subquery per pair.

    When to use: Matching where one field may be a subset of the other
    (e.g., 'John Smith' vs 'John Michael Smith Jr'). All tokens of the
    shorter string must appear in the longer for a score of 1.0.
    """
    return (
        f"(SAFE_DIVIDE("
        f"(SELECT COUNTIF(w IN ("
        f"SELECT DISTINCT t FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)) "
        f"FROM ("
        f"SELECT DISTINCT t AS w FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t"
        f")), "
        f"LEAST("
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t), "
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)"
        f")"
        f") >= {min_similarity} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("overlap_coefficient_score")
def overlap_coefficient_score(left: str, right: str, **_: Any) -> str:
    """Token overlap coefficient as a continuous score (0.0-1.0).

    Overlap = |intersection| / MIN(|left_tokens|, |right_tokens|).
    Uses set semantics (DISTINCT tokens) to avoid values > 1.0.

    COST: 30 -- correlated UNNEST subquery per pair.

    When to use: Scoring stage where subset matching is desired. Returns
    0.0 when either value is NULL.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL THEN "
        f"SAFE_DIVIDE("
        f"(SELECT COUNTIF(w IN ("
        f"SELECT DISTINCT t FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)) "
        f"FROM ("
        f"SELECT DISTINCT t AS w FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t"
        f")), "
        f"LEAST("
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t), "
        f"(SELECT COUNT(DISTINCT t) FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t)"
        f")"
        f") ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Monge-Elkan similarity (token-level best-match average)
# ---------------------------------------------------------------------------
# PERF: Monge-Elkan is the most expensive token comparison because it
# computes EDIT_DISTANCE between EVERY pair of tokens (O(n*m) tokens,
# each costing O(p*q) characters). For 3-token names, that is 9 edit
# distance calculations per candidate pair.
#
# Monge-Elkan = AVG over left tokens of MAX similarity to any right token
# where similarity(a, b) = 1 - EDIT_DISTANCE(a, b) / GREATEST(LENGTH(a), LENGTH(b))
#
# This handles partial matches well: if left='JOHN SMITH' and right=
# 'JONATHAN SMITH', each left token finds its best match independently.


@register("monge_elkan")
def monge_elkan(
    left: str, right: str, min_similarity: float = 0.7, **_: Any
) -> str:
    """Monge-Elkan similarity >= threshold.

    For each token in the left value, finds the best-matching token in the
    right value (using normalized edit distance), then averages the best
    matches. Handles partial token matches and misspellings.

    COST: 35 -- nested correlated subqueries with EDIT_DISTANCE per token pair.

    When to use: Fuzzy matching on multi-word fields where individual tokens
    may be misspelled (e.g., 'JONH SMITHE' vs 'JOHN SMITH'). More accurate
    than Dice/overlap when typos are common, but significantly more expensive.
    """
    return (
        f"((SELECT AVG(best_sim) FROM ("
        f"SELECT MAX(1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE(l_tok, r_tok) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH(l_tok), CHAR_LENGTH(r_tok))"
        f")) AS best_sim "
        f"FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) AS l_tok "
        f"CROSS JOIN UNNEST(SPLIT(UPPER(r.{right}), ' ')) AS r_tok "
        f"GROUP BY l_tok"
        f")) >= {min_similarity} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("monge_elkan_score")
def monge_elkan_score(left: str, right: str, **_: Any) -> str:
    """Monge-Elkan similarity as a continuous score (0.0-1.0).

    For each token in the left value, finds the best-matching token in the
    right value (using normalized edit distance), then averages the best
    matches.

    COST: 35 -- nested correlated subqueries with EDIT_DISTANCE per token pair.

    When to use: Scoring stage for fuzzy multi-word matching. Returns 0.0
    when either value is NULL.
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL THEN "
        f"(SELECT AVG(best_sim) FROM ("
        f"SELECT MAX(1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE(l_tok, r_tok) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH(l_tok), CHAR_LENGTH(r_tok))"
        f")) AS best_sim "
        f"FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) AS l_tok "
        f"CROSS JOIN UNNEST(SPLIT(UPPER(r.{right}), ' ')) AS r_tok "
        f"GROUP BY l_tok"
        f")) ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Token sort ratio (sort tokens then compare)
# ---------------------------------------------------------------------------
# PERF: Token sort ratio is cheaper than Dice/overlap because it avoids
# set intersection subqueries. Instead, it sorts tokens alphabetically
# and compares the resulting strings with EDIT_DISTANCE. This means
# 'Smith John' and 'John Smith' both become 'JOHN SMITH' and get a
# perfect score.
#
# The sorting step uses ARRAY_TO_STRING(ARRAY(SELECT ... ORDER BY ...), ' ')
# which is a single subquery per side (not correlated across pairs in the
# same way as COUNTIF(IN UNNEST(...))).
#
# For exact transposition detection (no typos), pre-compute sorted token
# fingerprint as FARM_FINGERPRINT in the feature pass and use "exact" match
# (cost: 1) instead.


@register("token_sort_ratio")
def token_sort_ratio(
    left: str, right: str, min_similarity: float = 0.8, **_: Any
) -> str:
    """Token sort ratio >= threshold.

    Sorts tokens alphabetically, then computes normalized edit distance
    similarity on the sorted strings. Handles word transpositions perfectly.

    COST: 25 -- ARRAY sort + EDIT_DISTANCE on sorted strings.

    When to use: Multi-word fields where word order varies but spelling is
    mostly correct (e.g., 'Smith John' vs 'John Smith'). Cheaper than
    Dice/overlap for transposition detection. For exact transpositions,
    use sorted_name_fingerprint + exact match instead.
    """
    sorted_l = (
        f"ARRAY_TO_STRING(ARRAY("
        f"SELECT t FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t ORDER BY t"
        f"), ' ')"
    )
    sorted_r = (
        f"ARRAY_TO_STRING(ARRAY("
        f"SELECT t FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t ORDER BY t"
        f"), ' ')"
    )
    return (
        f"(1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE({sorted_l}, {sorted_r}) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH({sorted_l}), CHAR_LENGTH({sorted_r}))"
        f") >= {min_similarity} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("token_sort_ratio_score")
def token_sort_ratio_score(left: str, right: str, **_: Any) -> str:
    """Token sort ratio as a continuous score (0.0-1.0).

    Sorts tokens alphabetically, then computes normalized edit distance
    similarity on the sorted strings.

    COST: 25 -- ARRAY sort + EDIT_DISTANCE on sorted strings.

    When to use: Scoring stage for transposition-invariant string comparison.
    Returns 0.0 when either value is NULL.
    """
    sorted_l = (
        f"ARRAY_TO_STRING(ARRAY("
        f"SELECT t FROM UNNEST(SPLIT(UPPER(l.{left}), ' ')) t ORDER BY t"
        f"), ' ')"
    )
    sorted_r = (
        f"ARRAY_TO_STRING(ARRAY("
        f"SELECT t FROM UNNEST(SPLIT(UPPER(r.{right}), ' ')) t ORDER BY t"
        f"), ' ')"
    )
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL THEN "
        f"1.0 - SAFE_DIVIDE("
        f"CAST(EDIT_DISTANCE({sorted_l}, {sorted_r}) AS FLOAT64), "
        f"GREATEST(CHAR_LENGTH({sorted_l}), CHAR_LENGTH({sorted_r}))"
        f") ELSE 0.0 END"
    )

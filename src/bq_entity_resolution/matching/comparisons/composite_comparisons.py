"""
Composite and embedding comparison functions.

Vector/embedding similarity (cosine, euclidean, manhattan, dot product)
and multi-field composite comparisons.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.matching.comparisons import register

# ---------------------------------------------------------------------------
# Embedding / vector similarity
# ---------------------------------------------------------------------------
# PERF: ML.DISTANCE is the most expensive comparison. It performs dot product
# and norm calculations on FLOAT64 arrays (typically 768-1536 dimensions).
# Use ONLY when embedding-based matching is required, and ONLY after blocking
# has reduced candidates to a manageable count (< 1M pairs recommended).
# For large-scale embedding matching, prefer LSH bucket blocking (INT64
# bucket keys via FARM_FINGERPRINT) to avoid computing distance on all pairs.
#
# BigQuery ML.DISTANCE supports: COSINE, EUCLIDEAN, MANHATTAN
# Each has different semantic meaning:
#   COSINE: Direction similarity (ignores magnitude). Best for text embeddings.
#   EUCLIDEAN: L2 norm distance. Good for spatial/coordinate embeddings.
#   MANHATTAN: L1 norm distance. Robust to outliers in individual dimensions.


@register("cosine_similarity")
def cosine_similarity(
    left: str, right: str, min_similarity: float = 0.85, **_: Any
) -> str:
    """Cosine similarity >= threshold using ML.DISTANCE.

    COST: 50 -- most expensive comparison. Use LSH blocking to pre-filter.

    When to use: Text embeddings, semantic similarity. Best when you care about
    direction (meaning) not magnitude (length). Standard for NLP embeddings.
    """
    max_distance = 1.0 - min_similarity
    return (
        f"(ML.DISTANCE(l.{left}, r.{right}, 'COSINE') <= {max_distance} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("cosine_similarity_score")
def cosine_similarity_score(left: str, right: str, **_: Any) -> str:
    """Cosine similarity score (1 - distance). Returns 0.0-1.0."""
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"THEN 1.0 - ML.DISTANCE(l.{left}, r.{right}, 'COSINE') "
        f"ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Euclidean distance (L2 norm)
# ---------------------------------------------------------------------------


@register("euclidean_distance")
def euclidean_distance(
    left: str, right: str, max_distance: float = 1.0, **_: Any
) -> str:
    """Euclidean (L2) distance <= threshold using ML.DISTANCE.

    COST: 50 -- vector math on FLOAT64 arrays.

    When to use: Spatial embeddings, coordinate-based similarity where
    magnitude matters. Sensitive to scale — normalize inputs first.
    """
    return (
        f"(ML.DISTANCE(l.{left}, r.{right}, 'EUCLIDEAN') <= {max_distance} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("euclidean_distance_score")
def euclidean_distance_score(
    left: str, right: str, max_distance: float = 10.0, **_: Any
) -> str:
    """Euclidean distance as similarity score (0.0-1.0).

    Returns 1 - (distance / max_distance), clamped to [0, 1].
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"THEN GREATEST(0.0, 1.0 - ML.DISTANCE(l.{left}, r.{right}, 'EUCLIDEAN') "
        f"/ {max_distance}) ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Manhattan distance (L1 norm)
# ---------------------------------------------------------------------------


@register("manhattan_distance")
def manhattan_distance(
    left: str, right: str, max_distance: float = 1.0, **_: Any
) -> str:
    """Manhattan (L1) distance <= threshold using ML.DISTANCE.

    COST: 45 -- slightly cheaper than cosine (no norm computation).

    When to use: Embeddings where outlier dimensions should not dominate.
    More robust than Euclidean when individual features have different scales.
    """
    return (
        f"(ML.DISTANCE(l.{left}, r.{right}, 'MANHATTAN') <= {max_distance} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("manhattan_distance_score")
def manhattan_distance_score(
    left: str, right: str, max_distance: float = 10.0, **_: Any
) -> str:
    """Manhattan distance as similarity score (0.0-1.0).

    Returns 1 - (distance / max_distance), clamped to [0, 1].
    """
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL "
        f"THEN GREATEST(0.0, 1.0 - ML.DISTANCE(l.{left}, r.{right}, 'MANHATTAN') "
        f"/ {max_distance}) ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Jaccard similarity (character n-gram based)
# ---------------------------------------------------------------------------


@register("jaccard_ngram")
def jaccard_ngram(
    left: str, right: str, n: int = 2, min_similarity: float = 0.5, **_: Any
) -> str:
    """Character n-gram Jaccard similarity >= threshold.

    Splits strings into character n-grams, computes |intersection|/|union|.
    Better than edit distance for misspellings that preserve character patterns.

    COST: 15 -- UNNEST + correlated subquery per pair.

    When to use: Typo-tolerant string matching where character patterns matter
    more than character positions. Good for addresses, company names.
    Params:
        n: N-gram size (2=bigrams, 3=trigrams). Default 2.
        min_similarity: Minimum Jaccard threshold. Default 0.5.
    """
    ngram_expr = (
        "(SELECT ARRAY_AGG(DISTINCT SUBSTR(s, pos, {n})) "
        "FROM UNNEST([{col}]) s, "
        "UNNEST(GENERATE_ARRAY(1, GREATEST(CHAR_LENGTH(s) - {nm1}, 0))) pos)"
    )
    l_ngrams = ngram_expr.format(col=f"UPPER(l.{left})", n=n, nm1=n - 1)
    r_ngrams = ngram_expr.format(col=f"UPPER(r.{right})", n=n, nm1=n - 1)
    return (
        f"(SAFE_DIVIDE("
        f"(SELECT COUNTIF(ng IN UNNEST({r_ngrams})) FROM UNNEST({l_ngrams}) ng),"
        f"ARRAY_LENGTH({l_ngrams}) + ARRAY_LENGTH({r_ngrams}) - "
        f"(SELECT COUNTIF(ng IN UNNEST({r_ngrams})) FROM UNNEST({l_ngrams}) ng)"
        f") >= {min_similarity} "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )


@register("jaccard_ngram_score")
def jaccard_ngram_score(left: str, right: str, n: int = 2, **_: Any) -> str:
    """Character n-gram Jaccard similarity as continuous score (0.0-1.0)."""
    ngram_expr = (
        "(SELECT ARRAY_AGG(DISTINCT SUBSTR(s, pos, {n})) "
        "FROM UNNEST([{col}]) s, "
        "UNNEST(GENERATE_ARRAY(1, GREATEST(CHAR_LENGTH(s) - {nm1}, 0))) pos)"
    )
    l_ngrams = ngram_expr.format(col=f"UPPER(l.{left})", n=n, nm1=n - 1)
    r_ngrams = ngram_expr.format(col=f"UPPER(r.{right})", n=n, nm1=n - 1)
    return (
        f"CASE WHEN l.{left} IS NOT NULL AND r.{right} IS NOT NULL THEN "
        f"SAFE_DIVIDE("
        f"(SELECT COUNTIF(ng IN UNNEST({r_ngrams})) FROM UNNEST({l_ngrams}) ng),"
        f"ARRAY_LENGTH({l_ngrams}) + ARRAY_LENGTH({r_ngrams}) - "
        f"(SELECT COUNTIF(ng IN UNNEST({r_ngrams})) FROM UNNEST({l_ngrams}) ng))"
        f" ELSE 0.0 END"
    )


# ---------------------------------------------------------------------------
# Regex matching
# ---------------------------------------------------------------------------


@register("regex_match")
def regex_match(left: str, right: str, pattern: str = ".*", **_: Any) -> str:
    """Both values match a regex pattern.

    COST: 5 -- REGEXP_CONTAINS per value.

    When to use: Pattern-based matching for structured identifiers
    (policy numbers, account IDs, VINs) where valid format is known.
    """
    if "'" in pattern:
        raise ValueError(
            f"regex_match pattern must not contain single quotes: {pattern!r}"
        )
    return (
        f"(REGEXP_CONTAINS(l.{left}, r'{pattern}') "
        f"AND REGEXP_CONTAINS(r.{right}, r'{pattern}') "
        f"AND l.{left} IS NOT NULL AND r.{right} IS NOT NULL)"
    )

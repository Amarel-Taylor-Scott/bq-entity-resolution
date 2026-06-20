"""
LSH (Locality-Sensitive Hashing) blocking for embedding-based matching.

Implements random hyperplane LSH for cosine similarity. Records with
similar embeddings are hashed to the same buckets with high probability,
enabling O(n*k) blocking instead of O(n^2) comparisons.
"""

from __future__ import annotations

from bq_entity_resolution.config.schema import LSHConfig


def lsh_bucket_columns(lsh_config: LSHConfig) -> list[str]:
    """Return the list of LSH bucket column names."""
    return [
        f"{lsh_config.bucket_column_prefix}_{i}"
        for i in range(lsh_config.num_hash_tables)
    ]


def lsh_blocking_condition(
    lsh_config: LSHConfig,
    left_alias: str = "l",
    right_alias: str = "r",
    min_matching_bands: int = 1,
) -> str:
    """
    Generate SQL condition for LSH blocking.

    Returns a SQL expression that is TRUE when at least `min_matching_bands`
    LSH buckets match between left and right records.
    """
    bucket_cols = lsh_bucket_columns(lsh_config)
    if not bucket_cols:
        return "FALSE"

    match_exprs = [
        f"CASE WHEN {left_alias}.{col} = {right_alias}.{col} THEN 1 ELSE 0 END"
        for col in bucket_cols
    ]
    sum_expr = " + ".join(match_exprs)
    return f"({sum_expr}) >= {min_matching_bands}"


def estimate_collision_probability(
    similarity: float,
    num_tables: int,
    num_functions: int,
) -> float:
    """
    Estimate the probability that two items with given cosine similarity
    will be hashed to the same bucket in at least one hash table.

    For random hyperplane LSH:
      P(same bucket in one table) = (1 - arccos(sim)/pi)^num_functions
      P(same bucket in any table) = 1 - (1 - p_one)^num_tables
    """
    import math

    theta = math.acos(max(-1.0, min(1.0, similarity)))
    p_one_func = 1.0 - theta / math.pi
    p_one_table = p_one_func ** num_functions
    p_any_table = 1.0 - (1.0 - p_one_table) ** num_tables
    return p_any_table

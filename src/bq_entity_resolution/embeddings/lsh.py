"""
LSH utilities for embeddings.

Re-exports from blocking.lsh for convenience and provides
embedding-specific LSH helpers.
"""

from __future__ import annotations

from bq_entity_resolution.blocking.lsh import (
    estimate_collision_probability,
    lsh_blocking_condition,
    lsh_bucket_columns,
)

__all__ = [
    "lsh_bucket_columns",
    "lsh_blocking_condition",
    "estimate_collision_probability",
]

"""Blocking strategies: equi-join and LSH-based candidate generation."""

from bq_entity_resolution.blocking.lsh import lsh_blocking_condition, lsh_bucket_columns
from bq_entity_resolution.blocking.standard import validate_blocking_path

__all__ = [
    "lsh_blocking_condition",
    "lsh_bucket_columns",
    "validate_blocking_path",
]

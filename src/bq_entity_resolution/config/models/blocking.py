"""
Blocking configuration models.

Defines blocking path and tier-level blocking configuration used
for candidate pair generation within matching tiers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from bq_entity_resolution.sql.utils import validate_identifier

__all__ = [
    "BlockingPathDef",
    "TierBlockingConfig",
]


class BlockingPathDef(BaseModel):
    """A single blocking path within a tier.

    A blocking path defines how candidate pairs are generated for
    comparison. Each path specifies one or more blocking keys that
    records must share to become a candidate pair.

    For LSH-based blocking, specify ``lsh_keys`` with the bucket
    column names produced by the embedding pipeline.
    """

    keys: list[str]
    lsh_keys: list[str] = Field(default_factory=list)

    @field_validator("keys", "lsh_keys")
    @classmethod
    def _validate_key_identifiers(cls, v: list[str]) -> list[str]:
        for key in v:
            validate_identifier(key, context="blocking key")
        return v
    candidate_limit: int = 200
    bucket_size_limit: int = 10_000  # max entities per bucket; set 0 to disable
    lsh_min_bands: int = 1  # for LSH blocking: min matching bands

    @field_validator("candidate_limit")
    @classmethod
    def _positive_candidate_limit(cls, v: int) -> int:
        if v < 1:
            raise ValueError("candidate_limit must be >= 1")
        return v

    @field_validator("bucket_size_limit")
    @classmethod
    def _non_negative_bucket_limit(cls, v: int) -> int:
        if v < 0:
            raise ValueError("bucket_size_limit must be >= 0 (0 = disabled)")
        return v

    @field_validator("lsh_min_bands")
    @classmethod
    def _positive_lsh_bands(cls, v: int) -> int:
        if v < 1:
            raise ValueError("lsh_min_bands must be >= 1")
        return v


class TierBlockingConfig(BaseModel):
    """Blocking configuration for a matching tier."""

    paths: list[BlockingPathDef]
    cross_batch: bool = True  # also compare against gold canonicals

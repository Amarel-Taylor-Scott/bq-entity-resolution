"""Blocking stage: generates candidate pairs for a matching tier.

Extracted from PipelineOrchestrator._execute_tiers() blocking portion.
Uses the blocking SQL builder for SQL generation.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
)
from bq_entity_resolution.naming import (
    candidates_table,
    featured_table,
)
from bq_entity_resolution.sql.builders.blocking import (
    BlockingParams,
    BlockingPath,
    build_blocking_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class BlockingStage(Stage):
    """Generate candidate pairs for a single matching tier.

    Supports multiple blocking paths, LSH keys, cross-batch
    matching, and prior-tier exclusion.
    """

    def __init__(
        self,
        tier: MatchingTierConfig,
        tier_index: int,
        config: PipelineConfig,
    ):
        self._tier = tier
        self._tier_index = tier_index
        self._config = config

    @property
    def name(self) -> str:
        return f"blocking_{self._tier.name}"

    @property
    def inputs(self) -> dict[str, TableRef]:
        refs = {
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
        }
        return refs

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = candidates_table(self._config, self._tier.name)
        return {
            "candidates": TableRef(
                name=f"candidates_{self._tier.name}",
                fq_name=target,
                description=f"Candidate pairs for tier {self._tier.name}",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate blocking SQL.

        kwargs:
            excluded_pairs_table: str | None — table of already-matched pairs
        """
        logger.debug("Planning %s stage", self.__class__.__name__)
        excluded = kwargs.get("excluded_pairs_table")
        tier = self._tier
        blocking = tier.blocking

        # Build blocking paths
        paths: list[BlockingPath] = []
        for i, path in enumerate(blocking.paths):
            paths.append(
                BlockingPath(
                    index=i,
                    keys=list(path.keys),
                    lsh_keys=list(path.lsh_keys),
                    candidate_limit=path.candidate_limit,
                    bucket_size_limit=path.bucket_size_limit,
                )
            )

        # Determine LSH table
        lsh_table = None
        if any(p.lsh_keys for p in paths):
            from bq_entity_resolution.naming import lsh_buckets_table
            lsh_table = lsh_buckets_table(self._config)

        # Determine canonical table for cross-batch
        canonical_table = None
        if blocking.cross_batch:
            from bq_entity_resolution.naming import canonical_index_table
            canonical_table = canonical_index_table(self._config)

        params = BlockingParams(
            target_table=self.outputs["candidates"].fq_name,
            source_table=featured_table(self._config),
            blocking_paths=paths,
            tier_name=tier.name,
            cross_batch=blocking.cross_batch,
            canonical_table=canonical_table,
            excluded_pairs_table=excluded,
            lsh_table=lsh_table,
            link_type=self._config.link_type,
        )

        # Log blocking effectiveness summary
        path_details = []
        for p in paths:
            keys_desc = ", ".join(p.keys)
            lsh_desc = f" + {len(p.lsh_keys)} LSH keys" if p.lsh_keys else ""
            limit_desc = f" (limit={p.candidate_limit})" if p.candidate_limit else ""
            path_details.append(f"path[{p.index}]: [{keys_desc}]{lsh_desc}{limit_desc}")
        logger.info(
            "Blocking summary for tier '%s': %d path(s), cross_batch=%s, "
            "excluded_pairs=%s. %s",
            tier.name,
            len(paths),
            blocking.cross_batch,
            excluded is not None,
            "; ".join(path_details),
        )

        return [build_blocking_sql(params)]

    def validate(self) -> list[str]:
        errors = []
        if not self._tier.blocking.paths:
            errors.append(
                f"Tier '{self._tier.name}' has no blocking paths defined"
            )
        return errors

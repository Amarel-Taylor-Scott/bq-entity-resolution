"""Match accumulation stage: accumulates per-tier matches into all_matches_table.

After each matching tier completes, this stage either initializes the
all_matches_table (first tier) or inserts new matches from the current tier.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
)
from bq_entity_resolution.naming import all_matches_table, matches_table
from bq_entity_resolution.sql.builders.comparison import (
    build_accumulate_matches_sql,
    build_init_matches_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef


class MatchAccumulationStage(Stage):
    """Accumulate per-tier matches into the all_matches table.

    The first tier creates the table; subsequent tiers INSERT INTO it.
    This ensures the all_matches_table exists for clustering.
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
        return f"accumulate_{self._tier.name}"

    @property
    def inputs(self) -> dict[str, TableRef]:
        src = matches_table(self._config, self._tier.name)
        return {
            "matches": TableRef(
                name=f"matches_{self._tier.name}",
                fq_name=src,
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = all_matches_table(self._config)
        return {
            "all_matches": TableRef(
                name="all_matches",
                fq_name=target,
                description="Accumulated matches across all tiers",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        target = all_matches_table(self._config)
        source = matches_table(self._config, self._tier.name)

        if self._tier_index == 0:
            return [build_init_matches_sql(target, source)]
        else:
            return [build_accumulate_matches_sql(target, source)]

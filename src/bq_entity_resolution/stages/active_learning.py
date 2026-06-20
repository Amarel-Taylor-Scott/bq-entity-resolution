"""Active learning stage: generates review queues for human labeling.

Extracted from PipelineOrchestrator._generate_review_queues().
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
)
from bq_entity_resolution.naming import (
    matches_table,
    review_queue_table,
)
from bq_entity_resolution.sql.builders.active_learning import (
    ActiveLearningParams,
    build_active_learning_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class ActiveLearningStage(Stage):
    """Generate active learning review queue for a single tier."""

    def __init__(
        self,
        tier: MatchingTierConfig,
        config: PipelineConfig,
    ):
        self._tier = tier
        self._config = config

    @property
    def name(self) -> str:
        return f"active_learning_{self._tier.name}"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "matches": TableRef(
                name=f"matches_{self._tier.name}",
                fq_name=matches_table(self._config, self._tier.name),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = review_queue_table(self._config, self._tier.name)
        return {
            "review_queue": TableRef(
                name=f"review_{self._tier.name}",
                fq_name=target,
                description=f"Review queue for tier {self._tier.name}",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate active learning review queue SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        al_config = self._tier.active_learning
        is_fs = self._tier.threshold.method == "fellegi_sunter"

        params = ActiveLearningParams(
            review_table=self.outputs["review_queue"].fq_name,
            matches_table=self.inputs["matches"].fq_name,
            queue_size=getattr(al_config, "queue_size", 100),
            uncertainty_window=getattr(al_config, "uncertainty_window", 0.3),
            is_fellegi_sunter=is_fs,
            min_score=self._tier.threshold.min_score,
        )

        return [build_active_learning_sql(params)]

"""Label ingestion stage: ingests human labels from review queues.

Closes the active learning feedback loop:
    review queue -> human labels -> labels table -> retrain m/u

Uses the existing ``build_ingest_labels_sql`` builder to MERGE
labeled pairs from the review queue into the persistent labels table.
"""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
)
from bq_entity_resolution.naming import (
    labels_table,
    review_queue_table,
)
from bq_entity_resolution.sql.builders.active_learning import (
    IngestLabelsParams,
    build_ingest_labels_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef


class LabelIngestionStage(Stage):
    """Ingest human labels from a tier's review queue into the labels table.

    Reads from the review queue (populated by ActiveLearningStage) and
    MERGEs labeled pairs into the shared labels table.  When enough
    labels accumulate and ``auto_retrain`` is enabled, the next pipeline
    run will use ``effective_training_config()`` to automatically
    retrain m/u probabilities from these labels.
    """

    def __init__(
        self,
        tier: MatchingTierConfig,
        config: PipelineConfig,
    ):
        self._tier = tier
        self._config = config

    @property
    def name(self) -> str:
        return f"label_ingestion_{self._tier.name}"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "review_queue": TableRef(
                name=f"review_{self._tier.name}",
                fq_name=review_queue_table(self._config, self._tier.name),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = labels_table(self._config)
        return {
            "labels": TableRef(
                name="al_labels",
                fq_name=target,
                description=f"Labels ingested from tier {self._tier.name}",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate SQL to ingest labels from the review queue."""
        params = IngestLabelsParams(
            labels_table=self.outputs["labels"].fq_name,
            review_queue_table=self.inputs["review_queue"].fq_name,
            tier_name=self._tier.name,
        )
        return [build_ingest_labels_sql(params)]

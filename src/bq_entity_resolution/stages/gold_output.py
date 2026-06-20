"""Gold output stage: generate resolved entities with canonical election."""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.naming import (
    all_matches_table,
    featured_table,
    resolved_table,
)
from bq_entity_resolution.naming import (
    cluster_table as _cluster_table,
)
from bq_entity_resolution.sql.builders.gold_output import (
    GoldOutputParams,
    build_gold_output_sql,
)
from bq_entity_resolution.sql.builders.golden_record import FieldStrategy
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class GoldOutputStage(Stage):
    """Generate resolved entities with canonical record election."""

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "gold_output"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
            "clusters": TableRef(
                name="clusters",
                fq_name=_cluster_table(self._config),
            ),
            "all_matches": TableRef(
                name="all_matches",
                fq_name=all_matches_table(self._config),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = resolved_table(self._config)
        return {
            "gold": TableRef(
                name="gold",
                fq_name=target,
                description="Final resolved entities",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate gold output SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        recon = self._config.reconciliation
        output = recon.output
        canonical = recon.canonical_selection

        # Collect source columns and passthrough columns
        scoring_cols: list[str] = []
        source_cols: list[str] = []
        passthrough_cols: list[str] = []
        for source in self._config.sources:
            for col in source.columns:
                if col.name not in source_cols:
                    source_cols.append(col.name)
                    scoring_cols.append(col.name)
            for pt in source.passthrough_columns:
                if pt not in passthrough_cols:
                    passthrough_cols.append(pt)

        # Field-level merge strategies
        field_strategies = [
            FieldStrategy(
                column=fs.column,
                strategy=fs.strategy,
                source_priority=fs.source_priority,
            )
            for fs in canonical.field_strategies
        ]

        params = GoldOutputParams(
            target_table=self.outputs["gold"].fq_name,
            source_table=self.inputs["featured"].fq_name,
            cluster_table=self.inputs["clusters"].fq_name,
            matches_table=self.inputs["all_matches"].fq_name,
            canonical_method=canonical.method,
            scoring_columns=scoring_cols,
            source_columns=source_cols,
            passthrough_columns=passthrough_cols,
            include_match_metadata=output.include_match_metadata,
            entity_id_prefix=output.entity_id_prefix,
            partition_column=output.partition_column,
            cluster_columns=output.cluster_columns,
            source_priority=canonical.source_priority,
            field_strategies=field_strategies,
            default_field_strategy=canonical.default_field_strategy,
            reconciliation_strategy=recon.strategy,
        )

        return [build_gold_output_sql(params)]

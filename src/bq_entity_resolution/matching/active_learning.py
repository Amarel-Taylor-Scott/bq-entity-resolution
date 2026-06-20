"""
Active learning: surface uncertain pairs for human review.

Generates a review queue of pairs closest to the decision boundary,
allowing human reviewers to label the most informative pairs first.
Labels can be fed back into the training pipeline to improve m/u estimates.
"""

from __future__ import annotations

import logging

from bq_entity_resolution.config.schema import (
    MatchingTierConfig,
    PipelineConfig,
)
from bq_entity_resolution.naming import (
    labels_table as default_labels_table,
)
from bq_entity_resolution.naming import (
    matches_table,
)
from bq_entity_resolution.naming import (
    review_queue_table as default_review_queue_table,
)
from bq_entity_resolution.sql.builders.active_learning import (
    ActiveLearningParams,
    IngestLabelsParams,
    build_active_learning_sql,
    build_ingest_labels_sql,
)

logger = logging.getLogger(__name__)


class ActiveLearningEngine:
    """Generates SQL for active learning review queue and label ingestion."""

    def __init__(self, config: PipelineConfig):
        self.config = config

    def generate_review_queue_sql(
        self, tier: MatchingTierConfig
    ) -> str:
        """Generate SQL to populate the review queue with uncertain pairs.

        For Fellegi-Sunter tiers: selects pairs closest to 0.5 match probability.
        For sum-based tiers: selects pairs closest to the threshold score.
        """
        al = tier.active_learning
        review_table = al.review_queue_table or default_review_queue_table(
            self.config, tier.name
        )

        params = ActiveLearningParams(
            review_table=review_table,
            matches_table=matches_table(self.config, tier.name),
            queue_size=al.queue_size,
            uncertainty_window=al.uncertainty_window,
            is_fellegi_sunter=tier.threshold.method == "fellegi_sunter",
            min_score=tier.threshold.min_score,
        )
        return build_active_learning_sql(params).render()

    def generate_label_ingestion_sql(self, tier: MatchingTierConfig) -> str:
        """Generate SQL to ingest human labels from the review queue into the labels table."""
        al = tier.active_learning
        review_table = al.review_queue_table or default_review_queue_table(
            self.config, tier.name
        )
        labels_tbl = (
            al.label_feedback.feedback_table
            or default_labels_table(self.config)
        )

        params = IngestLabelsParams(
            labels_table=labels_tbl,
            review_queue_table=review_table,
            tier_name=tier.name,
        )
        return build_ingest_labels_sql(params).render()

    def generate_label_count_sql(self, tier: MatchingTierConfig) -> str:
        """Generate SQL to count available labels for a tier."""
        al = tier.active_learning
        labels_tbl = (
            al.label_feedback.feedback_table
            or default_labels_table(self.config)
        )
        from bq_entity_resolution.sql.utils import sql_escape

        return (
            f"SELECT COUNT(*) AS label_count "
            f"FROM `{labels_tbl}` "
            f"WHERE tier_name = '{sql_escape(tier.name)}'"
        )

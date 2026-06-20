"""SQL builder for active learning (replaces active_learning_queue.sql.j2).

Generates SQL for review queue creation based on uncertainty sampling:
- Fellegi-Sunter: pairs nearest to 0.5 match probability
- Sum scoring: pairs nearest to threshold score
"""

from __future__ import annotations

from dataclasses import dataclass

from bq_entity_resolution.columns import (
    HUMAN_LABEL,
    INGESTED_AT,
    IS_MATCH,
    LABEL_SOURCE,
    LEFT_ENTITY_UID,
    MATCH_CONFIDENCE,
    MATCH_TIER_NAME,
    MATCH_TOTAL_SCORE,
    MATCH_UNCERTAINTY,
    QUEUED_AT,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref


@dataclass(frozen=True)
class ActiveLearningParams:
    """Parameters for active learning queue SQL generation."""
    review_table: str
    matches_table: str
    queue_size: int = 100
    uncertainty_window: float = 0.3
    is_fellegi_sunter: bool = False
    min_score: float = 0.0

    def __post_init__(self) -> None:
        validate_table_ref(self.review_table)
        validate_table_ref(self.matches_table)


def build_active_learning_sql(params: ActiveLearningParams) -> SQLExpression:
    """Build active learning review queue SQL.

    Selects pairs nearest to the decision boundary for human review.
    """
    lines: list[str] = []

    lines.append(f"CREATE OR REPLACE TABLE `{params.review_table}` AS")
    lines.append("")

    if params.is_fellegi_sunter:
        lines.append("SELECT")
        lines.append(f"  {LEFT_ENTITY_UID},")
        lines.append(f"  {RIGHT_ENTITY_UID},")
        lines.append(f"  {MATCH_TOTAL_SCORE},")
        lines.append(f"  {MATCH_CONFIDENCE},")
        lines.append(f"  ABS({MATCH_CONFIDENCE} - 0.5) AS {MATCH_UNCERTAINTY},")
        lines.append(f"  CAST(NULL AS BOOL) AS {HUMAN_LABEL},")
        lines.append(f"  CURRENT_TIMESTAMP() AS {QUEUED_AT}")
        lines.append(f"FROM `{params.matches_table}`")
        lines.append(
            f"WHERE ABS({MATCH_CONFIDENCE} - 0.5) <= {params.uncertainty_window}"
        )
        lines.append(f"ORDER BY ABS({MATCH_CONFIDENCE} - 0.5) ASC")
        lines.append(f"LIMIT {params.queue_size}")
    else:
        lines.append("SELECT")
        lines.append(f"  {LEFT_ENTITY_UID},")
        lines.append(f"  {RIGHT_ENTITY_UID},")
        lines.append(f"  {MATCH_TOTAL_SCORE},")
        lines.append(f"  {MATCH_CONFIDENCE},")

        if params.min_score > 0:
            lines.append(
                f"  ABS({MATCH_TOTAL_SCORE} - {params.min_score}) AS {MATCH_UNCERTAINTY},"
            )
        else:
            lines.append(
                f"  ABS({MATCH_CONFIDENCE} - 0.5) AS {MATCH_UNCERTAINTY},"
            )

        lines.append(f"  CAST(NULL AS BOOL) AS {HUMAN_LABEL},")
        lines.append(f"  CURRENT_TIMESTAMP() AS {QUEUED_AT}")
        lines.append(f"FROM `{params.matches_table}`")

        if params.min_score > 0:
            lines.append(
                f"ORDER BY ABS({MATCH_TOTAL_SCORE} - {params.min_score}) ASC"
            )
        else:
            lines.append(f"ORDER BY ABS({MATCH_CONFIDENCE} - 0.5) ASC")

        lines.append(f"LIMIT {params.queue_size}")

    return SQLExpression.from_raw("\n".join(lines))


# ---------------------------------------------------------------------------
# Label ingestion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestLabelsParams:
    """Parameters for label ingestion SQL."""
    labels_table: str
    review_queue_table: str
    tier_name: str

    def __post_init__(self) -> None:
        validate_table_ref(self.labels_table)
        validate_table_ref(self.review_queue_table)


def build_ingest_labels_sql(params: IngestLabelsParams) -> SQLExpression:
    """Build SQL to ingest human labels from the review queue.

    Creates the labels table if it doesn't exist, then MERGEs
    labeled pairs from the review queue.
    """
    lines: list[str] = []

    # Ensure labels table exists
    lines.append(f"CREATE TABLE IF NOT EXISTS `{params.labels_table}` (")
    lines.append(f"  {LEFT_ENTITY_UID} INT64 NOT NULL,")
    lines.append(f"  {RIGHT_ENTITY_UID} INT64 NOT NULL,")
    lines.append(f"  {IS_MATCH} BOOL NOT NULL,")
    lines.append(f"  {MATCH_TIER_NAME} STRING,")
    lines.append(f"  {LABEL_SOURCE} STRING DEFAULT 'active_learning',")
    lines.append(f"  {INGESTED_AT} TIMESTAMP DEFAULT CURRENT_TIMESTAMP()")
    lines.append(");")
    lines.append("")

    # Merge new labels from review queue
    lines.append(f"MERGE INTO `{params.labels_table}` AS target")
    lines.append("USING (")
    lines.append("  SELECT")
    lines.append(f"    {LEFT_ENTITY_UID},")
    lines.append(f"    {RIGHT_ENTITY_UID},")
    lines.append(
        f"    CASE WHEN {HUMAN_LABEL} = 'match' THEN TRUE ELSE FALSE END AS {IS_MATCH},"
    )
    lines.append(f"    '{sql_escape(params.tier_name)}' AS {MATCH_TIER_NAME},")
    lines.append(f"    'active_learning' AS {LABEL_SOURCE},")
    lines.append(f"    CURRENT_TIMESTAMP() AS {INGESTED_AT}")
    lines.append(f"  FROM `{params.review_queue_table}`")
    lines.append(f"  WHERE {HUMAN_LABEL} IS NOT NULL")
    lines.append(") AS source")
    lines.append(f"ON target.{LEFT_ENTITY_UID} = source.{LEFT_ENTITY_UID}")
    lines.append(f"  AND target.{RIGHT_ENTITY_UID} = source.{RIGHT_ENTITY_UID}")
    lines.append(f"  AND target.{MATCH_TIER_NAME} = source.{MATCH_TIER_NAME}")
    lines.append("WHEN MATCHED THEN")
    lines.append("  UPDATE SET")
    lines.append(f"    {IS_MATCH} = source.{IS_MATCH},")
    lines.append(f"    {INGESTED_AT} = source.{INGESTED_AT}")
    lines.append("WHEN NOT MATCHED THEN")
    lines.append(
        f"  INSERT ({LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}, {IS_MATCH}, "
        f"{MATCH_TIER_NAME}, {LABEL_SOURCE}, {INGESTED_AT})"
    )
    lines.append(
        f"  VALUES (source.{LEFT_ENTITY_UID}, source.{RIGHT_ENTITY_UID}, source.{IS_MATCH},"
    )
    lines.append(
        f"          source.{MATCH_TIER_NAME}, source.{LABEL_SOURCE}, source.{INGESTED_AT})"
    )

    return SQLExpression.from_raw("\n".join(lines))

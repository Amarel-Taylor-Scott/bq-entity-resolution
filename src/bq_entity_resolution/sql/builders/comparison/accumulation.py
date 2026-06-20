"""Match accumulation SQL builders.

Builds SQL for initializing and accumulating matches across tiers."""

from __future__ import annotations

from bq_entity_resolution.sql.expression import SQLExpression


def build_init_matches_sql(target_table: str, source_table: str) -> SQLExpression:
    """Build SQL to initialize the all_matches table from the first tier's matches.

    Creates the accumulated matches table with the same schema as the
    per-tier matches table.
    """
    sql = (
        f"CREATE OR REPLACE TABLE `{target_table}` AS\n"
        f"SELECT * FROM `{source_table}`"
    )
    return SQLExpression.from_raw(sql)


def build_accumulate_matches_sql(target_table: str, source_table: str) -> SQLExpression:
    """Build SQL to accumulate matches from a subsequent tier.

    Inserts new matches from the current tier into the accumulated
    matches table, avoiding duplicates.
    """
    sql = (
        f"INSERT INTO `{target_table}`\n"
        f"SELECT s.* FROM `{source_table}` s\n"
        f"LEFT JOIN `{target_table}` t\n"
        f"  ON s.left_entity_uid = t.left_entity_uid\n"
        f"  AND s.right_entity_uid = t.right_entity_uid\n"
        f"WHERE t.left_entity_uid IS NULL"
    )
    return SQLExpression.from_raw(sql)

__all__ = [
    "build_init_matches_sql",
    "build_accumulate_matches_sql",
]

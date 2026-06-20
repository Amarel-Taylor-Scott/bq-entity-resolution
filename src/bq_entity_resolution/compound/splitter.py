"""CompoundSplitter: generates SQL to split compound records into individual rows.

When a compound record like "Jane and Joe Smith" is detected, this generates
a SQL CTE that UNNESTs the record into two rows:
  Row 0: first_name = "JANE", last_name = "SMITH"
  Row 1: first_name = "JOE",  last_name = "SMITH"

The original entity_uid is preserved as _original_entity_uid, and each split
row gets a new entity_uid with a _split_index suffix.
"""

from __future__ import annotations


class CompoundSplitter:
    """Generates SQL to split compound records into individual rows."""

    def __init__(
        self,
        name_col: str = "first_name",
        last_name_col: str = "last_name",
        uid_col: str = "entity_uid",
        flag_col: str = "is_compound_name",
    ):
        self.name_col = name_col
        self.last_name_col = last_name_col
        self.uid_col = uid_col
        self.flag_col = flag_col

    def build_split_cte(self, source_ref: str) -> str:
        """Generate a CTE that splits compound records into individual rows.

        Non-compound records pass through unchanged (split_index = 0).
        Compound records produce 2 rows (split_index = 0 and 1) using
        the extract_compound_first / extract_compound_second logic.

        Args:
            source_ref: Fully-qualified source table or CTE name.

        Returns:
            A complete CTE SQL string (without the WITH keyword).
        """
        name = self.name_col
        uid = self.uid_col

        return f"""compound_split AS (
  -- Non-compound records: pass through as-is
  SELECT
    *,
    {uid} AS _original_entity_uid,
    0 AS _split_index
  FROM {source_ref}
  WHERE {self.flag_col} = 0 OR {self.flag_col} IS NULL

  UNION ALL

  -- Compound records: first individual
  SELECT
    * EXCEPT({name}),
    CASE
      WHEN REGEXP_CONTAINS(UPPER({name}), r'^\\w+\\s+(AND|&|\\+)\\s+\\w+')
        THEN UPPER(REGEXP_EXTRACT({name}, r'^(\\w+)\\s+(?:AND|&|\\+)\\s+'))
      WHEN REGEXP_CONTAINS({name}, r'^\\w+\\s*/\\s*\\w+')
        THEN UPPER(REGEXP_EXTRACT({name}, r'^(\\w+)\\s*/'))
      ELSE UPPER({name})
    END AS {name},
    {uid} AS _original_entity_uid,
    0 AS _split_index
  FROM {source_ref}
  WHERE {self.flag_col} = 1

  UNION ALL

  -- Compound records: second individual
  SELECT
    * EXCEPT({name}),
    CASE
      WHEN REGEXP_CONTAINS(UPPER({name}), r'^\\w+\\s+(AND|&|\\+)\\s+\\w+')
        THEN UPPER(REGEXP_EXTRACT({name}, r'(?:AND|&|\\+)\\s+(\\w+)'))
      WHEN REGEXP_CONTAINS({name}, r'^\\w+\\s*/\\s*\\w+')
        THEN UPPER(REGEXP_EXTRACT({name}, r'/\\s*(\\w+)'))
      ELSE NULL
    END AS {name},
    {uid} AS _original_entity_uid,
    1 AS _split_index
  FROM {source_ref}
  WHERE {self.flag_col} = 1
)"""

    def build_uid_expression(self) -> str:
        """Generate a new entity_uid expression that includes the split index.

        Returns:
            SQL expression like "CONCAT(_original_entity_uid, '_', CAST(_split_index AS STRING))".
        """
        return "CONCAT(_original_entity_uid, '_', CAST(_split_index AS STRING))"

"""SQL builder for embeddings and LSH buckets.

Replaces:
- features/embeddings.sql.j2
- blocking/lsh_block.sql.j2
"""

from __future__ import annotations

from dataclasses import dataclass

from bq_entity_resolution.columns import BQML_PREDICTED_EMBEDDING, EMBEDDING_INPUT_TEXT, ENTITY_UID
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref


@dataclass(frozen=True)
class EmbeddingsParams:
    """Parameters for embedding generation SQL."""
    target_table: str
    source_table: str
    concat_expression: str
    model_name: str
    dimensions: int

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        validate_table_ref(self.source_table)
        validate_table_ref(self.model_name)


@dataclass(frozen=True)
class LSHParams:
    """Parameters for LSH bucket computation SQL."""
    target_table: str
    embedding_table: str
    num_tables: int
    num_functions: int
    dimensions: int
    seed: int
    bucket_prefix: str = "lsh_bucket"

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        validate_table_ref(self.embedding_table)
        validate_identifier(self.bucket_prefix, "LSH bucket prefix")


def build_embeddings_sql(params: EmbeddingsParams) -> SQLExpression:
    """Build SQL to compute text embeddings using BigQuery ML."""
    sql = (
        f"CREATE OR REPLACE TABLE `{params.target_table}` AS\n"
        f"\n"
        f"WITH texts AS (\n"
        f"  SELECT\n"
        f"    {ENTITY_UID},\n"
        f"    {params.concat_expression} AS {EMBEDDING_INPUT_TEXT}\n"
        f"  FROM `{params.source_table}`\n"
        f"  WHERE {params.concat_expression} IS NOT NULL\n"
        f"    AND CHAR_LENGTH(TRIM({params.concat_expression})) > 0\n"
        f")\n"
        f"\n"
        f"SELECT\n"
        f"  t.{ENTITY_UID},\n"
        f"  t.{EMBEDDING_INPUT_TEXT},\n"
        f"  result.text_embedding AS {BQML_PREDICTED_EMBEDDING}\n"
        f"FROM\n"
        f"  ML.GENERATE_TEXT_EMBEDDING(\n"
        f"    MODEL `{params.model_name}`,\n"
        f"    (SELECT * FROM texts),\n"
        f"    STRUCT(TRUE AS flatten_json_output, "
        f"{params.dimensions} AS output_dimensionality)\n"
        f"  ) AS result\n"
        f"JOIN texts t ON t.{ENTITY_UID} = result.{ENTITY_UID}"
    )
    return SQLExpression.from_raw(sql)


def build_lsh_buckets_sql(params: LSHParams) -> SQLExpression:
    """Build SQL to compute LSH bucket assignments from embeddings.

    Uses random hyperplane LSH with deterministic projections
    seeded by FARM_FINGERPRINT.
    """
    lines: list[str] = []

    lines.append(f"DECLARE dim INT64 DEFAULT {params.dimensions};")
    lines.append("")
    lines.append(f"CREATE OR REPLACE TABLE `{params.target_table}` AS")
    lines.append("")
    lines.append("WITH embeddings AS (")
    lines.append("  SELECT")
    lines.append(f"    {ENTITY_UID},")
    lines.append(f"    {BQML_PREDICTED_EMBEDDING}")
    lines.append(f"  FROM `{params.embedding_table}`")
    lines.append(f"  WHERE {BQML_PREDICTED_EMBEDDING} IS NOT NULL")
    lines.append(f"    AND ARRAY_LENGTH({BQML_PREDICTED_EMBEDDING}) = dim")
    lines.append("),")
    lines.append("")

    # Random projection vectors
    lines.append("projections AS (")
    lines.append("  SELECT")
    lines.append("    table_id,")
    lines.append("    func_id,")
    lines.append("    dim_idx,")
    lines.append("    (FARM_FINGERPRINT(")
    lines.append("      CONCAT(")
    lines.append(f"        CAST({params.seed} AS STRING), '|',")
    lines.append("        CAST(table_id AS STRING), '|',")
    lines.append("        CAST(func_id AS STRING), '|',")
    lines.append("        CAST(dim_idx AS STRING)")
    lines.append("      )")
    lines.append("    ) / 9223372036854775807.0) AS projection_value")
    lines.append("  FROM")
    lines.append(
        f"    UNNEST(GENERATE_ARRAY(0, {params.num_tables - 1})) AS table_id,"
    )
    lines.append(
        f"    UNNEST(GENERATE_ARRAY(0, {params.num_functions - 1})) AS func_id,"
    )
    lines.append("    UNNEST(GENERATE_ARRAY(0, dim - 1)) AS dim_idx")
    lines.append("),")
    lines.append("")

    # Dot products
    lines.append("dot_products AS (")
    lines.append("  SELECT")
    lines.append(f"    e.{ENTITY_UID},")
    lines.append("    p.table_id,")
    lines.append("    p.func_id,")
    lines.append(
        f"    SUM(e.{BQML_PREDICTED_EMBEDDING}"
        f"[OFFSET(p.dim_idx)] * p.projection_value)"
        f" AS dot_product"
    )
    lines.append("  FROM embeddings e")
    lines.append("  CROSS JOIN projections p")
    lines.append(f"  GROUP BY e.{ENTITY_UID}, p.table_id, p.func_id")
    lines.append("),")
    lines.append("")

    # Hash signatures
    lines.append("signatures AS (")
    lines.append("  SELECT")
    lines.append(f"    {ENTITY_UID},")
    lines.append("    table_id,")
    lines.append("    FARM_FINGERPRINT(")
    lines.append("      STRING_AGG(")
    lines.append("        CAST(IF(dot_product >= 0, 1, 0) AS STRING),")
    lines.append("        ''")
    lines.append("        ORDER BY func_id")
    lines.append("      )")
    lines.append("    ) AS bucket_hash")
    lines.append("  FROM dot_products")
    lines.append(f"  GROUP BY {ENTITY_UID}, table_id")
    lines.append(")")
    lines.append("")

    # Pivot to one column per hash table
    lines.append("SELECT")
    lines.append(f"  {ENTITY_UID},")
    pivot_cols: list[str] = []
    for i in range(params.num_tables):
        pivot_cols.append(
            f"  MAX(IF(table_id = {i}, bucket_hash, NULL)) "
            f"AS {params.bucket_prefix}_{i}"
        )
    lines.append(",\n".join(pivot_cols))
    lines.append("FROM signatures")
    lines.append(f"GROUP BY {ENTITY_UID}")

    return SQLExpression.from_raw("\n".join(lines))

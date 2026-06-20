"""Phonetic feature functions (UDF-based)."""

from __future__ import annotations

from typing import Any

from bq_entity_resolution.features.registry import register

_UDF_DATASET_PLACEHOLDER = "{udf_dataset}"


@register("metaphone")
def metaphone(inputs: list[str], udf_dataset: str = "", **_: Any) -> str:
    """Compute Metaphone code via a BigQuery JS UDF.

    The UDF must be deployed to the udf_dataset as ``metaphone(STRING) -> STRING``.
    """
    col = inputs[0]
    ds = udf_dataset or _UDF_DATASET_PLACEHOLDER
    return (
        f"CASE WHEN {col} IS NOT NULL "
        f"THEN `{ds}.metaphone`({col}) "
        f"ELSE NULL END"
    )

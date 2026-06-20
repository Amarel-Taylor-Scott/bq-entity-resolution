"""
Standard equi-join blocking helpers.

These are utility functions for building blocking key expressions and
validating blocking key configurations.
"""

from __future__ import annotations

from bq_entity_resolution.config.schema import BlockingKeyDef, BlockingPathDef


def validate_blocking_path(path: BlockingPathDef) -> list[str]:
    """
    Validate a blocking path and return any warnings.

    Checks for:
    - Empty key lists
    - Suspiciously high candidate limits
    - Single low-cardinality keys (e.g. just 'state')
    """
    warnings: list[str] = []

    if not path.keys:
        warnings.append("Blocking path has no keys — will produce cartesian join")

    if path.candidate_limit > 10000:
        warnings.append(
            f"Candidate limit {path.candidate_limit} is very high. "
            "Consider reducing to avoid excessive comparisons."
        )

    if path.candidate_limit <= 0:
        warnings.append(
            "Candidate limit is 0 or negative — no pairs will be generated."
        )

    return warnings


def estimate_selectivity(key: BlockingKeyDef, estimated_cardinality: int) -> float:
    """
    Estimate blocking key selectivity.

    Selectivity = 1 / cardinality (lower is more selective = better blocking).
    """
    if estimated_cardinality <= 0:
        return 1.0
    return 1.0 / estimated_cardinality

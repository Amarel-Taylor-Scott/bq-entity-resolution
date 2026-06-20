"""Matching: comparison functions, parameter estimation, active learning."""

from bq_entity_resolution.matching.comparisons import (
    COMPARISON_COSTS,
    COMPARISON_FUNCTIONS,
    load_comparison_plugins,
    register,
)
from bq_entity_resolution.matching.parameters import ParameterEstimator

__all__ = [
    "ParameterEstimator",
    "COMPARISON_FUNCTIONS",
    "COMPARISON_COSTS",
    "register",
    "load_comparison_plugins",
]

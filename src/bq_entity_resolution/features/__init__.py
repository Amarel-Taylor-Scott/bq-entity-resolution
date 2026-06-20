"""Feature engineering: registry of 60+ feature functions."""

from bq_entity_resolution.features.registry import (
    FEATURE_FUNCTIONS,
    load_feature_plugins,
    register,
)

__all__ = [
    "FEATURE_FUNCTIONS",
    "register",
    "load_feature_plugins",
]

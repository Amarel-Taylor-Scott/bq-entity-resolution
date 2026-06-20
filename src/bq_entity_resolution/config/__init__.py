"""Configuration system: YAML schema, loader, presets, and validators."""

from bq_entity_resolution.config.loader import load_config
from bq_entity_resolution.config.schema import PipelineConfig

__all__ = [
    "PipelineConfig",
    "load_config",
]

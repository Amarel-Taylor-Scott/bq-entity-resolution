"""Shared test fixtures."""

from pathlib import Path

import pytest

from bq_entity_resolution.config.loader import load_config
from bq_entity_resolution.config.schema import PipelineConfig

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_config_path() -> Path:
    return FIXTURES_DIR / "sample_config.yml"


@pytest.fixture
def sample_config(sample_config_path: Path) -> PipelineConfig:
    return load_config(sample_config_path, skip_env_interpolation=True)

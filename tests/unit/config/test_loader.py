"""Tests for configuration loader."""

import os
from pathlib import Path

import pytest

from bq_entity_resolution.config.loader import load_config
from bq_entity_resolution.exceptions import ConfigurationError

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def test_load_sample_config():
    cfg = load_config(
        FIXTURES_DIR / "sample_config.yml",
        skip_env_interpolation=True,
    )
    assert cfg.project.name == "test_pipeline"
    assert cfg.project.bq_project == "test-project"
    assert len(cfg.sources) == 1
    assert len(cfg.matching_tiers) == 2


def test_load_nonexistent_file():
    with pytest.raises(ConfigurationError, match="not found"):
        load_config("/nonexistent/path.yml")


def test_env_var_interpolation(tmp_path):
    config_content = """
project:
  name: test
  bq_project: "${TEST_BQ_PROJECT}"
sources:
  - name: src
    table: t
    unique_key: id
    updated_at: ts
    columns:
      - name: c
matching_tiers: []
"""
    config_file = tmp_path / "config.yml"
    config_file.write_text(config_content)

    os.environ["TEST_BQ_PROJECT"] = "my-project-123"
    try:
        cfg = load_config(str(config_file), validate=False)
        assert cfg.project.bq_project == "my-project-123"
    finally:
        del os.environ["TEST_BQ_PROJECT"]


def test_env_var_with_default(tmp_path):
    config_content = """
project:
  name: test
  bq_project: "${MISSING_VAR:-fallback-project}"
sources:
  - name: src
    table: t
    unique_key: id
    updated_at: ts
    columns:
      - name: c
matching_tiers: []
"""
    config_file = tmp_path / "config.yml"
    config_file.write_text(config_content)

    cfg = load_config(str(config_file), validate=False)
    assert cfg.project.bq_project == "fallback-project"


def test_missing_env_var_raises(tmp_path):
    config_content = """
project:
  name: test
  bq_project: "${DEFINITELY_NOT_SET_VAR}"
sources:
  - name: src
    table: t
    unique_key: id
    updated_at: ts
    columns:
      - name: c
matching_tiers: []
"""
    config_file = tmp_path / "config.yml"
    config_file.write_text(config_content)

    with pytest.raises(ConfigurationError, match="not set"):
        load_config(str(config_file))


def test_overrides(tmp_path):
    config_content = """
project:
  name: original
  bq_project: proj
sources:
  - name: src
    table: t
    unique_key: id
    updated_at: ts
    columns:
      - name: c
matching_tiers: []
"""
    config_file = tmp_path / "config.yml"
    config_file.write_text(config_content)

    cfg = load_config(
        str(config_file),
        overrides={"project": {"name": "overridden"}},
        skip_env_interpolation=True,
        validate=False,
    )
    assert cfg.project.name == "overridden"
    assert cfg.project.bq_project == "proj"

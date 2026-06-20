"""Tests for config includes/composition support."""

from __future__ import annotations

from pathlib import Path

import pytest

from bq_entity_resolution.config.loader import load_config
from bq_entity_resolution.exceptions import ConfigurationError


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Create a temp directory for config files."""
    return tmp_path


def _write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


class TestConfigIncludes:
    """Tests for the includes: config composition feature."""

    def test_single_include(self, config_dir: Path):
        """User config includes a base config."""
        _write_yaml(
            config_dir / "base.yml",
            """
project:
  name: base_project
  bq_project: my-project
  bq_dataset_bronze: bronze
  bq_dataset_silver: silver
  bq_dataset_gold: gold

feature_engineering:
  blocking_keys:
    - name: bk_test
      function: farm_fingerprint
      inputs: [col_a]
""",
        )

        _write_yaml(
            config_dir / "main.yml",
            """
includes:
  - base.yml

sources:
  - name: test_source
    table: my-project.ds.table
    unique_key: id
    updated_at: updated_at
    columns:
      - name: col_a
        type: STRING

matching_tiers:
  - name: exact
    blocking:
      paths:
        - keys: [bk_test]
    comparisons:
      - left: col_a
        right: col_a
        method: exact
        weight: 5.0
    threshold:
      method: sum
      min_score: 5.0
""",
        )

        cfg = load_config(
            config_dir / "main.yml", skip_env_interpolation=True
        )
        assert cfg.project.name == "base_project"
        assert cfg.project.bq_project == "my-project"
        assert len(cfg.sources) == 1

    def test_user_overrides_included(self, config_dir: Path):
        """User config values take precedence over included values."""
        _write_yaml(
            config_dir / "base.yml",
            """
project:
  name: base_name
  bq_project: my-project
""",
        )

        _write_yaml(
            config_dir / "main.yml",
            """
includes:
  - base.yml

project:
  name: overridden_name
  bq_project: my-project

sources:
  - name: s
    table: p.d.t
    unique_key: id
    updated_at: u
    columns:
      - name: c
        type: STRING

feature_engineering:
  blocking_keys:
    - name: bk
      function: farm_fingerprint
      inputs: [c]

matching_tiers:
  - name: t
    blocking:
      paths:
        - keys: [bk]
    comparisons:
      - left: c
        right: c
        method: exact
        weight: 5.0
    threshold:
      method: sum
      min_score: 5.0
""",
        )

        cfg = load_config(
            config_dir / "main.yml", skip_env_interpolation=True
        )
        assert cfg.project.name == "overridden_name"

    def test_multiple_includes(self, config_dir: Path):
        """Multiple includes are merged in order."""
        _write_yaml(
            config_dir / "project_base.yml",
            """
project:
  name: from_base
  bq_project: my-project
""",
        )

        _write_yaml(
            config_dir / "features_base.yml",
            """
feature_engineering:
  blocking_keys:
    - name: bk_base
      function: farm_fingerprint
      inputs: [col_a]
""",
        )

        _write_yaml(
            config_dir / "main.yml",
            """
includes:
  - project_base.yml
  - features_base.yml

sources:
  - name: s
    table: p.d.t
    unique_key: id
    updated_at: u
    columns:
      - name: col_a

matching_tiers:
  - name: t
    blocking:
      paths:
        - keys: [bk_base]
    comparisons:
      - left: col_a
        right: col_a
        method: exact
        weight: 5.0
    threshold:
      method: sum
      min_score: 5.0
""",
        )

        cfg = load_config(
            config_dir / "main.yml", skip_env_interpolation=True
        )
        assert cfg.project.name == "from_base"
        assert len(cfg.feature_engineering.blocking_keys) >= 1

    def test_nested_includes(self, config_dir: Path):
        """An included file can include other files."""
        _write_yaml(
            config_dir / "project.yml",
            """
project:
  name: from_nested
  bq_project: my-project
""",
        )

        _write_yaml(
            config_dir / "features.yml",
            """
includes:
  - project.yml

feature_engineering:
  blocking_keys:
    - name: bk_nested
      function: farm_fingerprint
      inputs: [col_a]
""",
        )

        _write_yaml(
            config_dir / "main.yml",
            """
includes:
  - features.yml

sources:
  - name: s
    table: p.d.t
    unique_key: id
    updated_at: u
    columns:
      - name: col_a

matching_tiers:
  - name: t
    blocking:
      paths:
        - keys: [bk_nested]
    comparisons:
      - left: col_a
        right: col_a
        method: exact
    threshold:
      method: sum
      min_score: 1.0
""",
        )

        cfg = load_config(
            config_dir / "main.yml", skip_env_interpolation=True
        )
        assert cfg.project.name == "from_nested"

    def test_circular_include_detected(self, config_dir: Path):
        """Circular includes are detected and rejected."""
        _write_yaml(
            config_dir / "a.yml",
            """
includes:
  - b.yml
project:
  name: a
  bq_project: p
""",
        )

        _write_yaml(
            config_dir / "b.yml",
            """
includes:
  - a.yml
project:
  name: b
  bq_project: p
""",
        )

        with pytest.raises(ConfigurationError, match="Circular include"):
            load_config(config_dir / "a.yml", skip_env_interpolation=True)

    def test_missing_include_raises(self, config_dir: Path):
        """Missing included file raises error."""
        _write_yaml(
            config_dir / "main.yml",
            """
includes:
  - nonexistent.yml
project:
  name: test
  bq_project: p
sources:
  - name: s
    table: p.d.t
    unique_key: id
    updated_at: u
    columns:
      - name: c
matching_tiers: []
""",
        )

        with pytest.raises(ConfigurationError, match="not found"):
            load_config(config_dir / "main.yml", skip_env_interpolation=True)

    def test_string_include_converted_to_list(self, config_dir: Path):
        """A single string include is treated as a one-element list."""
        _write_yaml(
            config_dir / "base.yml",
            """
project:
  name: from_base
  bq_project: my-project
""",
        )

        _write_yaml(
            config_dir / "main.yml",
            """
includes: base.yml

sources:
  - name: s
    table: p.d.t
    unique_key: id
    updated_at: u
    columns:
      - name: c

feature_engineering:
  blocking_keys:
    - name: bk
      function: farm_fingerprint
      inputs: [c]

matching_tiers:
  - name: t
    blocking:
      paths:
        - keys: [bk]
    comparisons:
      - left: c
        right: c
        method: exact
    threshold:
      method: sum
      min_score: 1.0
""",
        )

        cfg = load_config(
            config_dir / "main.yml", skip_env_interpolation=True
        )
        assert cfg.project.name == "from_base"

    def test_no_includes_works_as_before(self, config_dir: Path):
        """Configs without includes: still work unchanged."""
        _write_yaml(
            config_dir / "main.yml",
            """
project:
  name: no_includes
  bq_project: my-project

sources:
  - name: s
    table: p.d.t
    unique_key: id
    updated_at: u
    columns:
      - name: c

feature_engineering:
  blocking_keys:
    - name: bk
      function: farm_fingerprint
      inputs: [c]

matching_tiers:
  - name: t
    blocking:
      paths:
        - keys: [bk]
    comparisons:
      - left: c
        right: c
        method: exact
    threshold:
      method: sum
      min_score: 1.0
""",
        )

        cfg = load_config(
            config_dir / "main.yml", skip_env_interpolation=True
        )
        assert cfg.project.name == "no_includes"

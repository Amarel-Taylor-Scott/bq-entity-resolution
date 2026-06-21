"""CLI tests for leaf-based resolution flags (run --repair/--leaf, preview-sql --leaf)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from bq_entity_resolution.cli.main import cli
from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def leaves_config(tmp_path):
    """A valid config with explicit leaves, written to a temp YAML file."""
    cfg = quick_config(
        bq_project="test-proj",
        source_table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        column_roles={
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
        },
        project_name="cli_leaf_test",
    )
    cfg.leaves = [
        LeafDef(name="new_x_new", left="new", right="new"),
        LeafDef(name="new_x_old", left="new", right="old"),
        LeafDef(
            name="old_x_old", left="old", right="old",
            schedule="cron", cron="0 3 * * 0",
        ),
    ]
    path = tmp_path / "leaves_config.yml"
    path.write_text(cfg.to_yaml())
    return str(path)


class TestPreviewSqlLeaf:
    def test_preview_leaf_emits_sql(self, runner, leaves_config):
        result = runner.invoke(
            cli, ["preview-sql", "--config", leaves_config, "--leaf", "new_x_old"]
        )
        assert result.exit_code == 0, result.output
        assert "LEAF SQL (new_x_old)" in result.output
        assert "CREATE OR REPLACE TABLE" in result.output

    def test_preview_scheduled_leaf_regardless_of_schedule(self, runner, leaves_config):
        result = runner.invoke(
            cli, ["preview-sql", "--config", leaves_config, "--leaf", "old_x_old"]
        )
        assert result.exit_code == 0, result.output
        assert "LEAF SQL (old_x_old)" in result.output

    def test_preview_unknown_leaf(self, runner, leaves_config):
        result = runner.invoke(
            cli, ["preview-sql", "--config", leaves_config, "--leaf", "nope"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_preview_requires_tier_or_leaf(self, runner, leaves_config):
        result = runner.invoke(cli, ["preview-sql", "--config", leaves_config])
        assert result.exit_code == 1
        assert "one of --tier / --leaf" in result.output

    def test_preview_rejects_both_tier_and_leaf(self, runner, leaves_config):
        result = runner.invoke(
            cli,
            ["preview-sql", "--config", leaves_config,
             "--tier", "exact", "--leaf", "new_x_new"],
        )
        assert result.exit_code == 1
        assert "only one" in result.output


class TestRunLeafFlags:
    def test_run_leaf_only_dry_run(self, runner, leaves_config):
        result = runner.invoke(
            cli,
            ["run", "--config", leaves_config, "--leaf", "old_x_old", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "Running only leaf(s)" in result.output

    def test_run_repair_dry_run(self, runner, leaves_config):
        result = runner.invoke(
            cli, ["run", "--config", leaves_config, "--repair", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "Repair run" in result.output

    def test_run_unknown_leaf_errors(self, runner, leaves_config):
        result = runner.invoke(
            cli, ["run", "--config", leaves_config, "--leaf", "ghost", "--dry-run"]
        )
        assert result.exit_code == 1
        assert "Unknown leaf" in result.output

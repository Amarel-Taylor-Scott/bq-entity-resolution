"""Tests for CLI entry points.

Uses Click's CliRunner to test all CLI commands without
actually connecting to BigQuery. Tests verify:
- Correct argument parsing
- Stage constructor argument order
- Proper error handling for missing tiers
- Dry-run output
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from bq_entity_resolution.cli.main import cli

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_CONFIG = str(FIXTURES_DIR / "sample_config.yml")


@pytest.fixture
def runner():
    return CliRunner()


class TestValidateCommand:
    """Tests for the 'validate' CLI command."""

    def test_validate_success(self, runner):
        """Valid config prints 'Configuration valid!'."""
        result = runner.invoke(cli, ["validate", "--config", SAMPLE_CONFIG])
        assert result.exit_code == 0
        assert "Configuration valid!" in result.output

    def test_validate_shows_sources(self, runner):
        """Validate output includes source information."""
        result = runner.invoke(cli, ["validate", "--config", SAMPLE_CONFIG])
        assert "test_source" in result.output
        assert "Sources:" in result.output

    def test_validate_shows_tiers(self, runner):
        """Validate output includes tier information."""
        result = runner.invoke(cli, ["validate", "--config", SAMPLE_CONFIG])
        assert "exact" in result.output
        assert "fuzzy" in result.output
        assert "Matching tiers:" in result.output

    def test_validate_missing_config(self, runner):
        """Missing config file shows error."""
        result = runner.invoke(cli, ["validate", "--config", "/nonexistent.yml"])
        assert result.exit_code != 0


class TestPreviewSQLCommand:
    """Tests for the 'preview-sql' CLI command.

    These test the argument ordering for BlockingStage and MatchingStage
    constructors, which was previously a bug.
    """

    def test_preview_blocking(self, runner):
        """preview-sql --stage blocking produces SQL output."""
        result = runner.invoke(cli, [
            "preview-sql", "--config", SAMPLE_CONFIG,
            "--tier", "exact", "--stage", "blocking",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "BLOCKING SQL" in result.output

    def test_preview_matching(self, runner):
        """preview-sql --stage matching produces SQL output."""
        result = runner.invoke(cli, [
            "preview-sql", "--config", SAMPLE_CONFIG,
            "--tier", "exact", "--stage", "matching",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "MATCHING SQL" in result.output

    def test_preview_all_stages(self, runner):
        """preview-sql --stage all produces both blocking and matching."""
        result = runner.invoke(cli, [
            "preview-sql", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--stage", "all",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "BLOCKING SQL" in result.output
        assert "MATCHING SQL" in result.output

    def test_preview_unknown_tier(self, runner):
        """preview-sql with unknown tier shows error."""
        result = runner.invoke(cli, [
            "preview-sql", "--config", SAMPLE_CONFIG,
            "--tier", "nonexistent", "--stage", "all",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_preview_sql_generates_valid_content(self, runner):
        """preview-sql produces SQL with expected keywords."""
        result = runner.invoke(cli, [
            "preview-sql", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--stage", "blocking",
        ])
        assert result.exit_code == 0
        # Blocking SQL should reference candidate generation
        output_upper = result.output.upper()
        assert "SELECT" in output_upper or "CREATE" in output_upper


class TestEstimateParamsCommand:
    """Tests for the 'estimate-params' CLI command."""

    def test_estimate_params_no_training(self, runner):
        """estimate-params with no training config shows appropriate message."""
        result = runner.invoke(cli, [
            "estimate-params", "--config", SAMPLE_CONFIG,
            "--tier", "exact",
        ])
        # Should indicate no training configured
        assert result.exit_code != 0
        assert "No training configured" in result.output or "training" in result.output.lower()

    def test_estimate_params_unknown_tier(self, runner):
        """estimate-params with unknown tier shows error."""
        result = runner.invoke(cli, [
            "estimate-params", "--config", SAMPLE_CONFIG,
            "--tier", "nonexistent",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestReviewQueueCommand:
    """Tests for the 'review-queue' CLI command."""

    def test_review_queue_generates_sql(self, runner):
        """review-queue generates active learning SQL."""
        result = runner.invoke(cli, [
            "review-queue", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "REVIEW QUEUE SQL" in result.output

    def test_review_queue_unknown_tier(self, runner):
        """review-queue with unknown tier shows error."""
        result = runner.invoke(cli, [
            "review-queue", "--config", SAMPLE_CONFIG,
            "--tier", "nonexistent",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestProfileCommand:
    """Tests for the 'profile' CLI command."""

    def test_profile_default_source(self, runner):
        """profile uses first source by default."""
        result = runner.invoke(cli, [
            "profile", "--config", SAMPLE_CONFIG,
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "PROFILING SQL" in result.output
        assert "test_source" in result.output

    def test_profile_specific_columns(self, runner):
        """profile with --columns limits to those columns."""
        result = runner.invoke(cli, [
            "profile", "--config", SAMPLE_CONFIG,
            "--columns", "email,phone",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "email" in result.output
        assert "phone" in result.output

    def test_profile_unknown_source(self, runner):
        """profile with unknown source shows error."""
        result = runner.invoke(cli, [
            "profile", "--config", SAMPLE_CONFIG,
            "--source", "nonexistent",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestAnalyzeCommand:
    """Tests for the 'analyze' CLI command."""

    def test_analyze_contribution(self, runner):
        """analyze --analysis contribution generates SQL."""
        result = runner.invoke(cli, [
            "analyze", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--analysis", "contribution",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "WEIGHT CONTRIBUTION" in result.output

    def test_analyze_threshold(self, runner):
        """analyze --analysis threshold generates SQL."""
        result = runner.invoke(cli, [
            "analyze", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--analysis", "threshold",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "THRESHOLD SWEEP" in result.output

    def test_analyze_impact(self, runner):
        """analyze --analysis impact generates SQL."""
        result = runner.invoke(cli, [
            "analyze", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--analysis", "impact",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "WEIGHT IMPACT" in result.output

    def test_analyze_unknown_tier(self, runner):
        """analyze with unknown tier shows error."""
        result = runner.invoke(cli, [
            "analyze", "--config", SAMPLE_CONFIG,
            "--tier", "nonexistent",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestIngestLabelsCommand:
    """Tests for the 'ingest-labels' CLI command."""

    def test_ingest_labels_dry_run(self, runner):
        """ingest-labels --dry-run generates SQL without executing."""
        result = runner.invoke(cli, [
            "ingest-labels", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--dry-run",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "LABEL INGESTION SQL" in result.output

    def test_ingest_labels_dry_run_with_retrain(self, runner):
        """ingest-labels --dry-run --retrain shows both ingestion and reestimation SQL."""
        result = runner.invoke(cli, [
            "ingest-labels", "--config", SAMPLE_CONFIG,
            "--tier", "fuzzy", "--dry-run", "--retrain",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "LABEL INGESTION SQL" in result.output
        assert "REESTIMATION SQL" in result.output

    def test_ingest_labels_unknown_tier(self, runner):
        """ingest-labels with unknown tier shows error."""
        result = runner.invoke(cli, [
            "ingest-labels", "--config", SAMPLE_CONFIG,
            "--tier", "nonexistent", "--dry-run",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestRunCommand:
    """Tests for the 'run' CLI command (dry-run mode only)."""

    def test_run_dry_run(self, runner):
        """run --dry-run generates SQL preview without connecting to BQ."""
        result = runner.invoke(cli, [
            "run", "--config", SAMPLE_CONFIG, "--dry-run",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "DRY RUN" in result.output

    def test_run_dry_run_with_tier_filter(self, runner):
        """run --dry-run --tier exact filters to specific tier."""
        result = runner.invoke(cli, [
            "run", "--config", SAMPLE_CONFIG,
            "--dry-run", "--tier", "exact",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "Running 1/2 tier(s)" in result.output
        assert "DRY RUN" in result.output

    def test_run_dry_run_unknown_tier(self, runner):
        """run --dry-run with unknown tier shows error."""
        result = runner.invoke(cli, [
            "run", "--config", SAMPLE_CONFIG,
            "--dry-run", "--tier", "nonexistent",
        ])
        assert result.exit_code != 0
        assert "No matching tiers found" in result.output

    def test_run_full_refresh_dry_run(self, runner):
        """run --full-refresh --dry-run works."""
        result = runner.invoke(cli, [
            "run", "--config", SAMPLE_CONFIG,
            "--full-refresh", "--dry-run",
        ])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "DRY RUN" in result.output


class TestVersionAndHelp:
    """Tests for --version and --help flags."""

    def test_version(self, runner):
        """--version prints version string."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output.lower() or "." in result.output

    def test_help(self, runner):
        """--help shows available commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "validate" in result.output
        assert "preview-sql" in result.output

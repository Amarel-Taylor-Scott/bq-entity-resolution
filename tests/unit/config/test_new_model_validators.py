"""Tests for config model validators (TrainingConfig, CanonicalSelectionConfig, etc.)."""

from __future__ import annotations

import warnings

import pytest

from bq_entity_resolution.config.models.infrastructure import (
    JobTrackingConfig,
    MonitoringConfig,
    ScaleConfig,
)
from bq_entity_resolution.config.models.matching import (
    ComparisonDef,
    ThresholdConfig,
    TrainingConfig,
)
from bq_entity_resolution.config.models.reconciliation import (
    CanonicalSelectionConfig,
    FieldMergeStrategy,
)
from bq_entity_resolution.config.models.source import ColumnMapping, SourceConfig


class TestTrainingConfigValidators:
    """Test TrainingConfig model validators."""

    def test_labeled_without_table_raises(self):
        """TrainingConfig(method='labeled') without labeled_pairs_table raises."""
        with pytest.raises(ValueError, match="requires labeled_pairs_table"):
            TrainingConfig(method="labeled")

    def test_labeled_with_table_passes(self):
        """TrainingConfig(method='labeled', labeled_pairs_table='t') passes."""
        config = TrainingConfig(method="labeled", labeled_pairs_table="proj.ds.labels")
        assert config.method == "labeled"
        assert config.labeled_pairs_table == "proj.ds.labels"

    def test_em_method_no_table_required(self):
        """method='em' does not require labeled_pairs_table."""
        config = TrainingConfig(method="em")
        assert config.method == "em"
        assert config.labeled_pairs_table is None

    def test_none_method_no_table_required(self):
        """method='none' does not require labeled_pairs_table."""
        config = TrainingConfig(method="none")
        assert config.method == "none"

    def test_labeled_with_none_table_raises(self):
        """method='labeled' with None table raises."""
        with pytest.raises(ValueError, match="requires labeled_pairs_table"):
            TrainingConfig(method="labeled", labeled_pairs_table=None)

    def test_labeled_with_empty_string_table_raises(self):
        """method='labeled' with empty string table raises."""
        with pytest.raises(ValueError, match="requires labeled_pairs_table"):
            TrainingConfig(method="labeled", labeled_pairs_table="")


class TestCanonicalSelectionConfigValidators:
    """Test CanonicalSelectionConfig model validators."""

    def test_field_merge_without_strategies_raises(self):
        """method='field_merge' without field_strategies raises."""
        with pytest.raises(ValueError, match="requires at least one field_strategy"):
            CanonicalSelectionConfig(method="field_merge")

    def test_field_merge_with_strategies_passes(self):
        """method='field_merge' with field_strategies passes."""
        config = CanonicalSelectionConfig(
            method="field_merge",
            field_strategies=[
                FieldMergeStrategy(column="name", strategy="most_recent"),
            ],
        )
        assert config.method == "field_merge"
        assert len(config.field_strategies) == 1

    def test_field_merge_empty_list_raises(self):
        """method='field_merge' with empty list raises."""
        with pytest.raises(ValueError, match="requires at least one field_strategy"):
            CanonicalSelectionConfig(method="field_merge", field_strategies=[])

    def test_completeness_no_strategies_required(self):
        """method='completeness' does not require field_strategies."""
        config = CanonicalSelectionConfig(method="completeness")
        assert config.method == "completeness"
        assert config.field_strategies == []

    def test_recency_no_strategies_required(self):
        """method='recency' does not require field_strategies."""
        config = CanonicalSelectionConfig(method="recency")
        assert config.method == "recency"

    def test_source_priority_no_strategies_required(self):
        """method='source_priority' does not require field_strategies."""
        config = CanonicalSelectionConfig(method="source_priority")
        assert config.method == "source_priority"


class TestSourceTableValidation:
    """Test source table format validation."""

    def test_three_part_table_accepted(self):
        """project.dataset.table format is accepted."""
        source = SourceConfig(
            name="src",
            table="my_project.my_dataset.my_table",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
        )
        assert source.table == "my_project.my_dataset.my_table"

    def test_two_part_table_accepted(self):
        """dataset.table format is accepted."""
        source = SourceConfig(
            name="src",
            table="my_dataset.my_table",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
        )
        assert source.table == "my_dataset.my_table"

    def test_four_part_table_rejected(self):
        """a.b.c.d format (too many parts) is rejected."""
        with pytest.raises(ValueError, match="project.dataset.table"):
            SourceConfig(
                name="src",
                table="a.b.c.d",
                unique_key="id",
                updated_at="updated_at",
                columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
            )

    def test_env_var_table_accepted(self):
        """Table with ${VAR} placeholder skips validation."""
        source = SourceConfig(
            name="src",
            table="${BQ_PROJECT}.dataset.table",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
        )
        assert "${BQ_PROJECT}" in source.table

    def test_empty_table_rejected(self):
        """Empty table string is rejected."""
        with pytest.raises(ValueError, match="non-empty"):
            SourceConfig(
                name="src",
                table="",
                unique_key="id",
                updated_at="updated_at",
                columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
            )

    def test_single_part_table_accepted(self):
        """Single-part table name is technically accepted (< 4 parts)."""
        source = SourceConfig(
            name="src",
            table="my_table",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
        )
        assert source.table == "my_table"


class TestWeightedSumDeprecation:
    """Test weighted_sum deprecation warning."""

    def test_weighted_sum_fires_deprecation(self):
        """method='weighted_sum' triggers DeprecationWarning and maps to 'sum'."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = ThresholdConfig(method="weighted_sum", min_score=1.0)
            assert config.method == "sum"
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            assert "weighted_sum" in str(deprecation_warnings[0].message)

    def test_sum_does_not_fire_deprecation(self):
        """method='sum' does not trigger deprecation."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = ThresholdConfig(method="sum", min_score=1.0)
            assert config.method == "sum"
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0


class TestZeroWeightComparison:
    """Test zero-weight comparison is accepted (valid but potentially a warning)."""

    def test_zero_weight_accepted(self):
        """weight=0 is accepted by ComparisonDef (non-negative)."""
        comp = ComparisonDef(left="name", right="name", method="exact", weight=0.0)
        assert comp.weight == 0.0

    def test_negative_weight_rejected(self):
        """Negative weight is rejected by ComparisonDef."""
        with pytest.raises(ValueError, match="weight must be >= 0"):
            ComparisonDef(left="name", right="name", method="exact", weight=-1.0)

    def test_positive_weight_accepted(self):
        """Positive weight works normally."""
        comp = ComparisonDef(left="name", right="name", method="exact", weight=5.0)
        assert comp.weight == 5.0


class TestScaleConfigExpiration:
    """Test ScaleConfig table_expiration_days validation."""

    def test_none_expiration_accepted(self):
        """None is the default and is accepted."""
        config = ScaleConfig()
        assert config.table_expiration_days is None

    def test_positive_expiration_accepted(self):
        """Positive integer is accepted."""
        config = ScaleConfig(table_expiration_days=30)
        assert config.table_expiration_days == 30

    def test_zero_expiration_rejected(self):
        """table_expiration_days=0 is rejected."""
        with pytest.raises(ValueError, match="table_expiration_days must be >= 1"):
            ScaleConfig(table_expiration_days=0)

    def test_negative_expiration_rejected(self):
        """Negative value is rejected."""
        with pytest.raises(ValueError, match="table_expiration_days must be >= 1"):
            ScaleConfig(table_expiration_days=-5)


class TestJobTrackingConfigValidators:
    """Tests for JobTrackingConfig cost threshold validators."""

    def test_none_thresholds_accepted(self):
        """None is the default for cost thresholds."""
        config = JobTrackingConfig()
        assert config.cost_alert_threshold_bytes is None
        assert config.cost_abort_threshold_bytes is None

    def test_positive_thresholds_accepted(self):
        """Positive values are accepted."""
        config = JobTrackingConfig(
            cost_alert_threshold_bytes=1000,
            cost_abort_threshold_bytes=5000,
        )
        assert config.cost_alert_threshold_bytes == 1000
        assert config.cost_abort_threshold_bytes == 5000

    def test_zero_alert_threshold_rejected(self):
        """Zero cost threshold is rejected."""
        with pytest.raises(ValueError, match="cost threshold must be >= 1"):
            JobTrackingConfig(cost_alert_threshold_bytes=0)

    def test_negative_abort_threshold_rejected(self):
        """Negative cost threshold is rejected."""
        with pytest.raises(ValueError, match="cost threshold must be >= 1"):
            JobTrackingConfig(cost_abort_threshold_bytes=-1)


class TestMonitoringConfigValidators:
    """Tests for MonitoringConfig min_data_quality_score validator."""

    def test_default_zero(self):
        """Default value is 0 (disabled)."""
        config = MonitoringConfig()
        assert config.min_data_quality_score == 0

    def test_valid_score(self):
        """Score within range accepted."""
        config = MonitoringConfig(min_data_quality_score=50)
        assert config.min_data_quality_score == 50

    def test_max_score(self):
        """Score of 100 accepted."""
        config = MonitoringConfig(min_data_quality_score=100)
        assert config.min_data_quality_score == 100

    def test_negative_score_rejected(self):
        """Negative score rejected."""
        with pytest.raises(ValueError, match="min_data_quality_score must be"):
            MonitoringConfig(min_data_quality_score=-1)

    def test_over_100_rejected(self):
        """Score over 100 rejected."""
        with pytest.raises(ValueError, match="min_data_quality_score must be"):
            MonitoringConfig(min_data_quality_score=101)

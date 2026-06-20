"""Tests for configuration schema validation."""

import pytest
from pydantic import ValidationError

from bq_entity_resolution.config.schema import (
    BlockingPathDef,
    ColumnMapping,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)


def test_project_config_minimal():
    cfg = ProjectConfig(name="test", bq_project="proj")
    assert cfg.bq_dataset_bronze == "er_bronze"
    assert cfg.bq_location == "US"


def test_source_config_duplicate_columns():
    with pytest.raises(ValidationError, match="Duplicate column"):
        SourceConfig(
            name="src",
            table="t",
            unique_key="id",
            updated_at="ts",
            columns=[
                ColumnMapping(name="a"),
                ColumnMapping(name="a"),
            ],
        )


def test_tier_name_validation():
    with pytest.raises(ValidationError, match="alphanumeric"):
        MatchingTierConfig(
            name="bad name!",
            blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["k"])]),
            comparisons=[],
            threshold=ThresholdConfig(),
        )


def test_tier_name_with_underscores():
    tier = MatchingTierConfig(
        name="fuzzy_name_match",
        blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["k"])]),
        comparisons=[],
        threshold=ThresholdConfig(),
    )
    assert tier.name == "fuzzy_name_match"


def test_pipeline_config_duplicate_tier_names():
    with pytest.raises(ValidationError, match="Duplicate tier"):
        PipelineConfig(
            project=ProjectConfig(name="t", bq_project="p"),
            sources=[
                SourceConfig(
                    name="s", table="t", unique_key="id",
                    updated_at="ts", columns=[ColumnMapping(name="c")],
                )
            ],
            matching_tiers=[
                MatchingTierConfig(
                    name="tier1",
                    blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["k"])]),
                    comparisons=[],
                    threshold=ThresholdConfig(),
                ),
                MatchingTierConfig(
                    name="tier1",
                    blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["k"])]),
                    comparisons=[],
                    threshold=ThresholdConfig(),
                ),
            ],
        )


def test_pipeline_config_no_sources():
    with pytest.raises(ValidationError, match="At least one source"):
        PipelineConfig(
            project=ProjectConfig(name="t", bq_project="p"),
            sources=[],
            matching_tiers=[],
        )


def test_enabled_tiers(sample_config):
    enabled = sample_config.enabled_tiers()
    assert len(enabled) == 2
    assert enabled[0].name == "exact"
    assert enabled[1].name == "fuzzy"


def test_fq_table(sample_config):
    table = sample_config.fq_table("bq_dataset_silver", "featured")
    assert table == "test-project.test_silver.featured"

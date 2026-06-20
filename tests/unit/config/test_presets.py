"""Tests for configuration presets."""

import pytest

from bq_entity_resolution.config.presets import (
    business_dedup_preset,
    person_dedup_preset,
    person_linkage_preset,
    quick_config,
)
from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.exceptions import ConfigurationError


class TestQuickConfig:
    def test_basic_creation(self):
        """quick_config generates a valid PipelineConfig."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.customers",
            columns=["first_name", "last_name", "email"],
        )
        assert isinstance(config, PipelineConfig)
        assert config.project.bq_project == "test-proj"

    def test_auto_detects_roles(self):
        """Column names are auto-detected to semantic roles."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.customers",
            columns=["first_name", "last_name", "dob", "email"],
        )
        # Should generate features for all detected roles
        feature_names = config.feature_engineering.all_feature_names()
        assert len(feature_names) > 0

    def test_explicit_roles_override(self):
        """Explicit column_roles override auto-detection."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        assert isinstance(config, PipelineConfig)
        cols = [c.name for c in config.sources[0].columns]
        assert "fn" in cols
        assert "ln" in cols

    def test_generates_tiers(self):
        """quick_config creates matching tiers."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        assert len(config.matching_tiers) == 2
        tier_names = [t.name for t in config.matching_tiers]
        assert "exact" in tier_names
        assert "fuzzy" in tier_names

    def test_generates_blocking_keys(self):
        """quick_config creates blocking keys from roles."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        bk_names = [
            bk.name
            for bk in config.feature_engineering.blocking_keys
        ]
        assert len(bk_names) > 0

    def test_no_recognized_columns_raises(self):
        """Columns with no recognized roles raise an error."""
        with pytest.raises(ConfigurationError, match="No columns"):
            quick_config(
                bq_project="test-proj",
                source_table="test-proj.raw.data",
                columns=["foobar", "baz"],
            )

    def test_project_name_derived(self):
        """Project name is derived from table name."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.customers",
            columns=["first_name", "last_name"],
        )
        assert config.project.name == "customers"

    def test_custom_project_name(self):
        """Custom project name is used when provided."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            columns=["first_name"],
            project_name="my_pipeline",
        )
        assert config.project.name == "my_pipeline"


class TestPersonDedupPreset:
    def test_basic_creation(self):
        config = person_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.people",
            columns={
                "first_name": "first_name",
                "last_name": "last_name",
                "dob": "date_of_birth",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.link_type == "dedupe_only"

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            person_dedup_preset(
                bq_project="test-proj",
                source_table="test-proj.raw.people",
            )

    def test_generates_features(self):
        config = person_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.people",
            columns={
                "first_name": "first_name",
                "last_name": "last_name",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 4  # At least clean + soundex per name

    def test_matching_tiers(self):
        config = person_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.people",
            columns={"first_name": "first_name", "ln": "last_name"},
        )
        assert len(config.matching_tiers) == 2


class TestPersonLinkagePreset:
    def test_basic_creation(self):
        config = person_linkage_preset(
            bq_project="test-proj",
            source_tables=[
                {"name": "crm", "table": "test-proj.raw.crm"},
                {"name": "erp", "table": "test-proj.raw.erp"},
            ],
            columns={
                "first_name": "first_name",
                "last_name": "last_name",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.link_type == "link_only"
        assert len(config.sources) == 2

    def test_requires_two_sources(self):
        with pytest.raises(ConfigurationError, match="At least 2"):
            person_linkage_preset(
                bq_project="test-proj",
                source_tables=[
                    {"name": "crm", "table": "test-proj.raw.crm"},
                ],
                columns={"first_name": "first_name"},
            )

    def test_source_names(self):
        config = person_linkage_preset(
            bq_project="test-proj",
            source_tables=[
                {"name": "crm", "table": "test-proj.raw.crm"},
                {"name": "erp", "table": "test-proj.raw.erp"},
            ],
            columns={"first_name": "first_name", "ln": "last_name"},
        )
        source_names = [s.name for s in config.sources]
        assert "crm" in source_names
        assert "erp" in source_names


class TestBusinessDedupPreset:
    def test_basic_creation(self):
        config = business_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.companies",
            columns={
                "company": "company_name",
                "tax_id": "ein",
            },
        )
        assert isinstance(config, PipelineConfig)
        assert config.link_type == "dedupe_only"

    def test_requires_columns(self):
        with pytest.raises(ConfigurationError, match="columns dict required"):
            business_dedup_preset(
                bq_project="test-proj",
                source_table="test-proj.raw.companies",
            )

    def test_generates_business_features(self):
        config = business_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.companies",
            columns={
                "company": "company_name",
                "tax_id": "ein",
            },
        )
        features = config.feature_engineering.all_feature_names()
        assert len(features) >= 2


class TestPresetValidation:
    """Verify presets produce valid PipelineConfig objects."""

    def test_quick_config_validates(self):
        """quick_config output passes Pydantic validation."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        # If we got here, Pydantic validation passed
        assert config.version == "1.0"
        assert len(config.sources) == 1
        assert len(config.matching_tiers) >= 1

    def test_person_dedup_validates(self):
        config = person_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.people",
            columns={
                "first_name": "first_name",
                "last_name": "last_name",
                "email": "email",
            },
        )
        assert config.version == "1.0"
        assert len(config.enabled_tiers()) >= 1

    def test_business_dedup_validates(self):
        config = business_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.companies",
            columns={"name": "company_name"},
        )
        assert config.version == "1.0"

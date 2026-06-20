"""Tests for custom entity type registration via YAML config."""
from __future__ import annotations

from bq_entity_resolution.config.entity_types import (
    ENTITY_TYPE_TEMPLATES,
    _resolved_cache,
    get_entity_type,
)
from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)


def _minimal_config(**overrides) -> PipelineConfig:
    """Build a minimal PipelineConfig with optional overrides."""
    defaults = dict(
        project=ProjectConfig(name="test", bq_project="test-proj"),
        sources=[
            SourceConfig(
                name="src",
                table="test-proj.ds.tbl",
                unique_key="id",
                updated_at="updated_at",
                columns=[ColumnMapping(name="first_name", role="first_name")],
            ),
        ],
        feature_engineering=FeatureEngineeringConfig(
            name_features=FeatureGroupConfig(),
            blocking_keys=[
                BlockingKeyDef(name="bk_test", function="soundex", inputs=["first_name"]),
            ],
        ),
        matching_tiers=[
            MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_test"])],
                ),
                comparisons=[
                    ComparisonDef(left="first_name", right="first_name", method="exact"),
                ],
                threshold=ThresholdConfig(min_score=1.0),
            ),
        ],
    )
    defaults.update(overrides)
    return PipelineConfig(**defaults)


class TestCustomEntityTypes:
    def test_custom_type_registered_on_load(self):
        config = _minimal_config(
            custom_entity_types={
                "Spacecraft": {
                    "valid_roles": ["vin", "make", "model"],
                    "required_roles": ["vin"],
                    "description": "Spacecraft type",
                },
            },
        )
        t = get_entity_type("Spacecraft")
        assert t.name == "Spacecraft"
        assert "vin" in t.valid_roles
        assert "vin" in t.required_roles
        assert t.description == "Spacecraft type"
        # Cleanup
        ENTITY_TYPE_TEMPLATES.pop("Spacecraft", None)
        _resolved_cache.clear()
        # Verify config has the field
        assert "Spacecraft" in config.custom_entity_types

    def test_custom_type_with_parent(self):
        _minimal_config(
            custom_entity_types={
                "RealEstate": {
                    "parent": "Thing",
                    "valid_roles": ["parcel_id", "owner_name"],
                },
            },
        )
        t = get_entity_type("RealEstate")
        assert t.parent == "Thing"
        assert "parcel_id" in t.valid_roles
        ENTITY_TYPE_TEMPLATES.pop("RealEstate", None)
        _resolved_cache.clear()

    def test_custom_type_with_schema_org(self):
        _minimal_config(
            custom_entity_types={
                "Product": {
                    "schema_org_type": "https://schema.org/Product",
                    "schema_org_aliases": {"sku": "product_id"},
                    "valid_roles": ["product_id"],
                },
            },
        )
        t = get_entity_type("Product")
        assert t.schema_org_type == "https://schema.org/Product"
        assert t.schema_org_aliases["sku"] == "product_id"
        ENTITY_TYPE_TEMPLATES.pop("Product", None)
        _resolved_cache.clear()

    def test_empty_custom_types_is_noop(self):
        """Config with no custom_entity_types works normally."""
        config = _minimal_config()
        assert config.custom_entity_types == {}

    def test_custom_type_with_default_signals(self):
        _minimal_config(
            custom_entity_types={
                "TestType": {
                    "valid_roles": ["test_col"],
                    "default_signals": [
                        {
                            "kind": "hard_negative",
                            "left": "test_col",
                            "method": "different",
                            "action": "disqualify",
                            "severity": "hn2_structural",
                            "value": 0.0,
                            "category": "test_identity",
                        },
                    ],
                },
            },
        )
        t = get_entity_type("TestType")
        assert len(t.default_signals) == 1
        assert t.default_signals[0].kind == "hard_negative"
        assert t.default_signals[0].left == "test_col"
        ENTITY_TYPE_TEMPLATES.pop("TestType", None)
        _resolved_cache.clear()


class TestSourceEntityType:
    def test_source_entity_type_field(self):
        config = _minimal_config(
            sources=[
                SourceConfig(
                    name="src",
                    table="test-proj.ds.tbl",
                    unique_key="id",
                    updated_at="updated_at",
                    entity_type="Person",
                    columns=[ColumnMapping(name="first_name", role="first_name")],
                ),
            ],
        )
        assert config.sources[0].entity_type == "Person"

    def test_source_entity_type_defaults_to_none(self):
        config = _minimal_config()
        assert config.sources[0].entity_type is None

    def test_source_entity_type_any_string(self):
        """entity_type is a free-form string; validation is separate."""
        config = _minimal_config(
            sources=[
                SourceConfig(
                    name="src",
                    table="test-proj.ds.tbl",
                    unique_key="id",
                    updated_at="updated_at",
                    entity_type="CustomThing",
                    columns=[ColumnMapping(name="first_name", role="first_name")],
                ),
            ],
        )
        assert config.sources[0].entity_type == "CustomThing"

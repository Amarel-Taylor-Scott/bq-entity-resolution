"""Tests for entity type validation in validators.py and matching.py."""
from __future__ import annotations

import logging

import pytest

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    FeatureGroupConfig,
    HardNegativeDef,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SoftSignalDef,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.config.validators import (
    validate_entity_type_conditions,
    validate_entity_type_roles,
)
from bq_entity_resolution.exceptions import ConfigurationError
from bq_entity_resolution.stages.matching import (
    _ENTITY_TYPE_MAP,
    _resolve_entity_type_sql_value,
)


def _minimal_config(**overrides) -> PipelineConfig:
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


# -- validate_entity_type_conditions tests -----------------------------------


class TestValidateEntityTypeConditions:
    def test_valid_legacy_conditions_pass(self):
        config = _minimal_config(
            global_hard_negatives=[
                HardNegativeDef(
                    left="first_name", method="different",
                    entity_type_condition="personal",
                ),
            ],
        )
        validate_entity_type_conditions(config)  # Should not raise

    def test_valid_registered_type_passes(self):
        config = _minimal_config(
            global_hard_negatives=[
                HardNegativeDef(
                    left="first_name", method="different",
                    entity_type_condition="Person",
                ),
            ],
        )
        validate_entity_type_conditions(config)  # Should not raise

    def test_unknown_condition_raises(self):
        config = _minimal_config(
            global_hard_negatives=[
                HardNegativeDef(
                    left="first_name", method="different",
                    entity_type_condition="alien",
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="entity_type_condition"):
            validate_entity_type_conditions(config)

    def test_no_conditions_passes(self):
        config = _minimal_config()
        validate_entity_type_conditions(config)  # Should not raise

    def test_tier_level_conditions_checked(self):
        config = _minimal_config(
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
                    soft_signals=[
                        SoftSignalDef(
                            left="first_name", method="exact",
                            entity_type_condition="martian",
                        ),
                    ],
                ),
            ],
        )
        with pytest.raises(ConfigurationError, match="entity_type_condition"):
            validate_entity_type_conditions(config)

    def test_case_insensitive_matching(self):
        """Entity type conditions are case-insensitive."""
        config = _minimal_config(
            global_hard_negatives=[
                HardNegativeDef(
                    left="first_name", method="different",
                    entity_type_condition="PERSON",
                ),
            ],
        )
        validate_entity_type_conditions(config)  # Should not raise


# -- validate_entity_type_roles tests ----------------------------------------


class TestValidateEntityTypeRoles:
    def test_no_entity_type_is_noop(self):
        config = _minimal_config()
        validate_entity_type_roles(config)  # Should not raise or warn

    def test_valid_entity_type_with_roles(self, caplog):
        config = _minimal_config(
            sources=[
                SourceConfig(
                    name="src",
                    table="test-proj.ds.tbl",
                    unique_key="id",
                    updated_at="updated_at",
                    entity_type="Person",
                    columns=[
                        ColumnMapping(name="first_name", role="first_name"),
                        ColumnMapping(name="last_name", role="last_name"),
                    ],
                ),
            ],
        )
        with caplog.at_level(logging.WARNING):
            validate_entity_type_roles(config)
        # No warnings — required roles present
        assert "missing required roles" not in caplog.text

    def test_missing_required_roles_warns(self, caplog):
        config = _minimal_config(
            sources=[
                SourceConfig(
                    name="src",
                    table="test-proj.ds.tbl",
                    unique_key="id",
                    updated_at="updated_at",
                    entity_type="Person",
                    columns=[
                        ColumnMapping(name="email", role="email"),
                    ],
                ),
            ],
        )
        with caplog.at_level(logging.WARNING):
            validate_entity_type_roles(config)
        assert "missing required roles" in caplog.text

    def test_unknown_entity_type_warns(self, caplog):
        config = _minimal_config(
            sources=[
                SourceConfig(
                    name="src",
                    table="test-proj.ds.tbl",
                    unique_key="id",
                    updated_at="updated_at",
                    entity_type="NonExistent",
                    columns=[ColumnMapping(name="first_name", role="first_name")],
                ),
            ],
        )
        with caplog.at_level(logging.WARNING):
            validate_entity_type_roles(config)
        assert "unknown entity_type" in caplog.text


# -- _resolve_entity_type_sql_value tests ------------------------------------


class TestResolveEntityTypeSqlValue:
    def test_legacy_personal_maps_to_person(self):
        assert _resolve_entity_type_sql_value("personal") == "PERSON"

    def test_legacy_business(self):
        assert _resolve_entity_type_sql_value("business") == "BUSINESS"

    def test_legacy_org(self):
        assert _resolve_entity_type_sql_value("org") == "ORGANIZATION"

    def test_registered_type_person(self):
        assert _resolve_entity_type_sql_value("Person") == "PERSON"

    def test_registered_type_patient(self):
        assert _resolve_entity_type_sql_value("Patient") == "PATIENT"

    def test_registered_type_case_insensitive(self):
        assert _resolve_entity_type_sql_value("organization") == "ORGANIZATION"

    def test_unknown_type_uppercased(self):
        assert _resolve_entity_type_sql_value("custom_thing") == "CUSTOM_THING"

    def test_backward_compat_map_still_exists(self):
        """The legacy _ENTITY_TYPE_MAP is still importable."""
        assert _ENTITY_TYPE_MAP["personal"] == "PERSON"
        assert _ENTITY_TYPE_MAP["business"] == "BUSINESS"

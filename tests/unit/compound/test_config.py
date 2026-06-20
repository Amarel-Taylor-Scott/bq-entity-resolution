"""Tests for CompoundDetectionConfig model."""

from __future__ import annotations

from bq_entity_resolution.config.schema import (
    CompoundDetectionConfig,
    FeatureEngineeringConfig,
)


class TestCompoundDetectionConfig:
    def test_defaults(self):
        cfg = CompoundDetectionConfig()
        assert cfg.enabled is False
        assert cfg.name_column == "first_name"
        assert cfg.last_name_column == "last_name"
        assert cfg.action == "flag"
        assert cfg.flag_column == "is_compound_name"
        assert cfg.custom_patterns == []

    def test_enabled_flag(self):
        cfg = CompoundDetectionConfig(enabled=True)
        assert cfg.enabled is True

    def test_action_flag(self):
        cfg = CompoundDetectionConfig(action="flag")
        assert cfg.action == "flag"

    def test_action_split(self):
        cfg = CompoundDetectionConfig(action="split")
        assert cfg.action == "split"

    def test_action_both(self):
        cfg = CompoundDetectionConfig(action="both")
        assert cfg.action == "both"

    def test_custom_name_column(self):
        cfg = CompoundDetectionConfig(name_column="full_name")
        assert cfg.name_column == "full_name"

    def test_custom_flag_column(self):
        cfg = CompoundDetectionConfig(flag_column="compound_flag")
        assert cfg.flag_column == "compound_flag"

    def test_custom_patterns(self):
        cfg = CompoundDetectionConfig(custom_patterns=[r"\bET\b", r"\bY\b"])
        assert len(cfg.custom_patterns) == 2


class TestFeatureEngineeringConfigCompound:
    def test_has_compound_detection_field(self):
        cfg = FeatureEngineeringConfig()
        assert hasattr(cfg, "compound_detection")
        assert isinstance(cfg.compound_detection, CompoundDetectionConfig)

    def test_compound_disabled_by_default(self):
        cfg = FeatureEngineeringConfig()
        assert cfg.compound_detection.enabled is False

    def test_compound_from_dict(self):
        cfg = FeatureEngineeringConfig(
            compound_detection={"enabled": True, "action": "split"}
        )
        assert cfg.compound_detection.enabled is True
        assert cfg.compound_detection.action == "split"

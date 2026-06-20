"""Tests for config model validators on individual Pydantic models.

Tests right-column normalization, field constraints, and
model_validator behavior on HardNegativeDef, HardPositiveDef,
SoftSignalDef, ScaleConfig, IncrementalConfig, and SourceConfig.
"""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.schema import (
    ColumnMapping,
    HardNegativeDef,
    HardPositiveDef,
    IncrementalConfig,
    ScaleConfig,
    SoftSignalDef,
    SourceConfig,
)

# ---------------------------------------------------------------------------
# HardNegativeDef right-column normalization
# ---------------------------------------------------------------------------

class TestHardNegativeDefNormalization:
    """HardNegativeDef._normalize_right: right=None -> right=left."""

    def test_right_defaults_to_left(self):
        hn = HardNegativeDef(left="dob", method="different")
        assert hn.right == "dob"

    def test_explicit_right_preserved(self):
        hn = HardNegativeDef(left="dob_l", right="dob_r", method="different")
        assert hn.right == "dob_r"

    def test_right_none_normalizes_to_left(self):
        hn = HardNegativeDef(left="gender", right=None, method="different")
        assert hn.right == "gender"

    def test_right_preserves_different_column(self):
        hn = HardNegativeDef(left="first_name", right="last_name", method="different")
        assert hn.left == "first_name"
        assert hn.right == "last_name"

    def test_severity_default(self):
        hn = HardNegativeDef(left="col", method="different")
        assert hn.severity == "hn2_structural"

    def test_all_severity_levels(self):
        for sev in ["hn1_critical", "hn2_structural", "hn3_identity", "hn4_contextual"]:
            hn = HardNegativeDef(left="col", method="different", severity=sev)
            assert hn.severity == sev


# ---------------------------------------------------------------------------
# HardPositiveDef right-column normalization
# ---------------------------------------------------------------------------

class TestHardPositiveDefNormalization:
    """HardPositiveDef._normalize_right: right=None -> right=left."""

    def test_right_defaults_to_left(self):
        hp = HardPositiveDef(left="ssn", method="exact")
        assert hp.right == "ssn"

    def test_explicit_right_preserved(self):
        hp = HardPositiveDef(left="ssn_left", right="ssn_right", method="exact")
        assert hp.right == "ssn_right"

    def test_right_none_normalizes_to_left(self):
        hp = HardPositiveDef(left="email", right=None, method="exact")
        assert hp.right == "email"

    def test_action_default(self):
        hp = HardPositiveDef(left="col", method="exact")
        assert hp.action == "boost"

    def test_all_action_types(self):
        for action in ["boost", "auto_match", "elevate_band"]:
            hp = HardPositiveDef(left="col", method="exact", action=action)
            assert hp.action == action

    def test_default_boost_value(self):
        hp = HardPositiveDef(left="col", method="exact")
        assert hp.boost == 5.0


# ---------------------------------------------------------------------------
# SoftSignalDef right-column normalization
# ---------------------------------------------------------------------------

class TestSoftSignalDefNormalization:
    """SoftSignalDef._normalize_right: right=None -> right=left."""

    def test_right_defaults_to_left(self):
        ss = SoftSignalDef(left="city", method="exact")
        assert ss.right == "city"

    def test_explicit_right_preserved(self):
        ss = SoftSignalDef(left="city_l", right="city_r", method="exact")
        assert ss.right == "city_r"

    def test_right_none_normalizes_to_left(self):
        ss = SoftSignalDef(left="phone", right=None, method="exact")
        assert ss.right == "phone"

    def test_default_bonus(self):
        ss = SoftSignalDef(left="col", method="exact")
        assert ss.bonus == 1.0

    def test_custom_bonus(self):
        ss = SoftSignalDef(left="col", method="exact", bonus=2.5)
        assert ss.bonus == 2.5

    def test_entity_type_condition(self):
        ss = SoftSignalDef(
            left="col", method="exact", entity_type_condition="personal"
        )
        assert ss.entity_type_condition == "personal"


# ---------------------------------------------------------------------------
# ScaleConfig clustering column limit
# ---------------------------------------------------------------------------

class TestScaleConfigValidation:
    """ScaleConfig rejects >4 clustering columns per BigQuery limit."""

    def test_four_columns_accepted(self):
        sc = ScaleConfig(staging_clustering=["a", "b", "c", "d"])
        assert len(sc.staging_clustering) == 4

    def test_five_columns_rejected(self):
        with pytest.raises(ValueError, match="max 4 clustering columns"):
            ScaleConfig(staging_clustering=["a", "b", "c", "d", "e"])

    def test_empty_clustering_accepted(self):
        sc = ScaleConfig(staging_clustering=[])
        assert sc.staging_clustering == []

    def test_one_column_accepted(self):
        sc = ScaleConfig(staging_clustering=["entity_uid"])
        assert len(sc.staging_clustering) == 1

    def test_candidates_clustering_over_limit(self):
        with pytest.raises(ValueError, match="max 4"):
            ScaleConfig(candidates_clustering=["a", "b", "c", "d", "e"])

    def test_matches_clustering_over_limit(self):
        with pytest.raises(ValueError, match="max 4"):
            ScaleConfig(matches_clustering=["a", "b", "c", "d", "e"])

    def test_featured_table_clustering_over_limit(self):
        with pytest.raises(ValueError, match="max 4"):
            ScaleConfig(featured_table_clustering=["a", "b", "c", "d", "e"])

    def test_canonical_index_clustering_over_limit(self):
        with pytest.raises(ValueError, match="max 4"):
            ScaleConfig(canonical_index_clustering=["a", "b", "c", "d", "e"])


# ---------------------------------------------------------------------------
# IncrementalConfig cursor_columns
# ---------------------------------------------------------------------------

class TestIncrementalConfigValidation:
    """IncrementalConfig rejects empty cursor_columns."""

    def test_empty_cursor_columns_rejected(self):
        with pytest.raises(ValueError, match="cursor_columns"):
            IncrementalConfig(enabled=True, cursor_columns=[])

    def test_single_cursor_column_accepted(self):
        ic = IncrementalConfig(enabled=True, cursor_columns=["updated_at"])
        assert ic.cursor_columns == ["updated_at"]

    def test_multiple_cursor_columns_accepted(self):
        ic = IncrementalConfig(
            enabled=True,
            cursor_columns=["updated_at", "policy_id"],
        )
        assert len(ic.cursor_columns) == 2

    def test_batch_size_must_be_positive(self):
        with pytest.raises(ValueError, match="batch_size"):
            IncrementalConfig(enabled=True, batch_size=0)

    def test_batch_size_negative_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            IncrementalConfig(enabled=True, batch_size=-1)

    def test_grace_period_negative_rejected(self):
        with pytest.raises(ValueError, match="grace_period_hours"):
            IncrementalConfig(enabled=True, grace_period_hours=-1)

    def test_drain_max_iterations_must_be_positive(self):
        with pytest.raises(ValueError, match="drain_max_iterations"):
            IncrementalConfig(enabled=True, drain_max_iterations=0)


# ---------------------------------------------------------------------------
# SourceConfig batch_size
# ---------------------------------------------------------------------------

class TestSourceConfigBatchSize:
    """SourceConfig rejects batch_size < 1."""

    def test_batch_size_zero_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            SourceConfig(
                name="test",
                table="proj.ds.test",
                unique_key="id",
                updated_at="updated_at",
                columns=[ColumnMapping(name="a")],
                batch_size=0,
            )

    def test_batch_size_negative_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            SourceConfig(
                name="test",
                table="proj.ds.test",
                unique_key="id",
                updated_at="updated_at",
                columns=[ColumnMapping(name="a")],
                batch_size=-100,
            )

    def test_batch_size_one_accepted(self):
        sc = SourceConfig(
            name="test",
            table="proj.ds.test",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="a")],
            batch_size=1,
        )
        assert sc.batch_size == 1

    def test_default_batch_size(self):
        sc = SourceConfig(
            name="test",
            table="proj.ds.test",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="a")],
        )
        assert sc.batch_size == 2_000_000

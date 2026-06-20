"""Tests for IncrementalConfig and HashCursorConfig schema models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bq_entity_resolution.config.schema import HashCursorConfig, IncrementalConfig


class TestIncrementalConfigDefaults:
    """Verify default values for IncrementalConfig."""

    def test_cursor_mode_defaults_to_ordered(self):
        cfg = IncrementalConfig()
        assert cfg.cursor_mode == "ordered"

    def test_hash_cursor_defaults_to_none(self):
        cfg = IncrementalConfig()
        assert cfg.hash_cursor is None

    def test_drain_mode_defaults_to_false(self):
        cfg = IncrementalConfig()
        assert cfg.drain_mode is False

    def test_drain_max_iterations_defaults_to_100(self):
        cfg = IncrementalConfig()
        assert cfg.drain_max_iterations == 100

    def test_enabled_defaults_to_true(self):
        cfg = IncrementalConfig()
        assert cfg.enabled is True

    def test_grace_period_hours_defaults_to_48(self):
        cfg = IncrementalConfig()
        assert cfg.grace_period_hours == 48

    def test_batch_size_defaults_to_2_million(self):
        cfg = IncrementalConfig()
        assert cfg.batch_size == 2_000_000

    def test_cursor_columns_defaults_to_updated_at(self):
        cfg = IncrementalConfig()
        assert cfg.cursor_columns == ["updated_at"]


class TestIncrementalConfigCursorMode:
    """Verify cursor_mode accepts valid values and rejects invalid ones."""

    def test_cursor_mode_accepts_independent(self):
        cfg = IncrementalConfig(cursor_mode="independent")
        assert cfg.cursor_mode == "independent"

    def test_cursor_mode_accepts_ordered(self):
        cfg = IncrementalConfig(cursor_mode="ordered")
        assert cfg.cursor_mode == "ordered"

    def test_cursor_mode_rejects_invalid_value(self):
        with pytest.raises(ValidationError):
            IncrementalConfig(cursor_mode="invalid_mode")


class TestIncrementalConfigHashCursor:
    """Verify hash_cursor integration in IncrementalConfig."""

    def test_hash_cursor_accepts_hash_cursor_config(self):
        hc = HashCursorConfig(column="policy_id", modulus=500, alias="_hp")
        cfg = IncrementalConfig(hash_cursor=hc)
        assert cfg.hash_cursor is not None
        assert cfg.hash_cursor.column == "policy_id"
        assert cfg.hash_cursor.modulus == 500
        assert cfg.hash_cursor.alias == "_hp"

    def test_hash_cursor_from_dict(self):
        cfg = IncrementalConfig(hash_cursor={"column": "uid", "modulus": 200})
        assert cfg.hash_cursor is not None
        assert cfg.hash_cursor.column == "uid"
        assert cfg.hash_cursor.modulus == 200


class TestIncrementalConfigDrainMode:
    """Verify drain mode configuration."""

    def test_drain_mode_enabled(self):
        cfg = IncrementalConfig(drain_mode=True)
        assert cfg.drain_mode is True

    def test_drain_max_iterations_custom(self):
        cfg = IncrementalConfig(drain_max_iterations=50)
        assert cfg.drain_max_iterations == 50

    def test_drain_mode_with_max_iterations(self):
        cfg = IncrementalConfig(drain_mode=True, drain_max_iterations=10)
        assert cfg.drain_mode is True
        assert cfg.drain_max_iterations == 10


class TestHashCursorConfigDefaults:
    """Verify default values for HashCursorConfig."""

    def test_column_defaults_to_entity_uid(self):
        cfg = HashCursorConfig()
        assert cfg.column == "entity_uid"

    def test_modulus_defaults_to_1000(self):
        cfg = HashCursorConfig()
        assert cfg.modulus == 1000

    def test_alias_defaults_to_hash_partition(self):
        cfg = HashCursorConfig()
        assert cfg.alias == "_hash_partition"


class TestHashCursorConfigCustom:
    """Verify custom values are accepted."""

    def test_custom_column(self):
        cfg = HashCursorConfig(column="policy_id")
        assert cfg.column == "policy_id"

    def test_custom_modulus(self):
        cfg = HashCursorConfig(modulus=500)
        assert cfg.modulus == 500

    def test_custom_alias(self):
        cfg = HashCursorConfig(alias="_my_bucket")
        assert cfg.alias == "_my_bucket"

    def test_all_custom_values(self):
        cfg = HashCursorConfig(
            column="customer_id",
            modulus=2000,
            alias="_cust_hash",
        )
        assert cfg.column == "customer_id"
        assert cfg.modulus == 2000
        assert cfg.alias == "_cust_hash"

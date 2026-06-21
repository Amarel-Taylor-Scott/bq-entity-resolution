"""Tests for the leaf repair-watermark SQL builders."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.leaf_repair import (
    build_advance_repair_watermark_sql,
    build_repair_watermark_ddl,
    repair_watermark_floor,
)

TABLE = "proj.er_meta.leaf_repair_watermarks"


def test_ddl_is_create_if_not_exists():
    sql = build_repair_watermark_ddl(TABLE).render()
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert f"`{TABLE}`" in sql
    assert "leaf_name STRING NOT NULL" in sql
    assert "last_repair_at TIMESTAMP NOT NULL" in sql


def test_floor_is_scalar_subquery_with_epoch_default():
    floor = repair_watermark_floor(TABLE, "old_x_old")
    assert floor.startswith("(SELECT COALESCE(MAX(last_repair_at)")
    assert "TIMESTAMP '1970-01-01 00:00:00'" in floor
    assert "WHERE leaf_name = 'old_x_old'" in floor


def test_advance_inserts_one_row_per_leaf():
    sql = build_advance_repair_watermark_sql(TABLE, ["a", "b"]).render()
    assert f"INSERT INTO `{TABLE}`" in sql
    assert sql.count("CURRENT_TIMESTAMP()") == 2
    assert "UNION ALL" in sql
    assert "'a' AS leaf_name" in sql
    assert "'b' AS leaf_name" in sql


def test_advance_empty_raises():
    with pytest.raises(ValueError):
        build_advance_repair_watermark_sql(TABLE, [])


def test_floor_escapes_leaf_name():
    floor = repair_watermark_floor(TABLE, "o'x")
    assert "''" in floor  # single quote escaped

"""Tests for ordered tuple watermark SQL generation in the staging builder."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.staging import (
    StagingParams,
    _build_order_by_columns,
    _build_ordered_watermark,
    build_staging_sql,
)


class TestBuildOrderedWatermark:
    """Tests for the _build_ordered_watermark() helper."""

    def test_two_columns_generates_correct_sql(self):
        """Two-column ordered watermark: c1 > v1 OR (c1 = v1 AND c2 > v2)."""
        watermark = {"updated_at": "2024-01-15T00:00:00", "policy_id": 500}
        result = _build_ordered_watermark(watermark)

        assert "updated_at > TIMESTAMP('2024-01-15T00:00:00')" in result
        assert (
            "updated_at = TIMESTAMP('2024-01-15T00:00:00') AND policy_id > 500"
            in result
        )
        assert "OR" in result

    def test_three_columns_generates_nested_sql(self):
        """Three-column watermark generates 3 OR clauses with nesting."""
        watermark = {
            "updated_at": "2024-01-15T00:00:00",
            "policy_id": 500,
            "seq_num": 42,
        }
        result = _build_ordered_watermark(watermark)

        # First clause: updated_at > v1
        assert "updated_at > TIMESTAMP('2024-01-15T00:00:00')" in result
        # Second clause: (updated_at = v1 AND policy_id > v2)
        assert (
            "updated_at = TIMESTAMP('2024-01-15T00:00:00') AND policy_id > 500"
            in result
        )
        # Third clause: (updated_at = v1 AND policy_id = v2 AND seq_num > v3)
        assert "policy_id = 500 AND seq_num > 42" in result

        # Count OR separators
        assert result.count("OR") == 2

    def test_grace_period_applies_to_first_column_only(self):
        """Grace period (TIMESTAMP_SUB) applies only to the first column."""
        watermark = {"updated_at": "2024-01-15T00:00:00", "policy_id": 500}
        result = _build_ordered_watermark(watermark, grace_period_hours=6)

        # First column should have TIMESTAMP_SUB
        assert "TIMESTAMP_SUB" in result
        assert "INTERVAL 6 HOUR" in result

        # The grace period should apply to the > comparison, not the = comparison
        # for the first column's standalone clause
        assert (
            "updated_at > TIMESTAMP_SUB(TIMESTAMP('2024-01-15T00:00:00'), INTERVAL 6 HOUR)"
            in result
        )

        # Second clause's policy_id comparison should NOT have TIMESTAMP_SUB
        lines = result.split("OR")
        # The second clause should have plain policy_id > 500
        second_clause = lines[1]
        assert "policy_id > 500" in second_clause
        # TIMESTAMP_SUB should not appear in the second clause's comparison
        assert "TIMESTAMP_SUB" not in second_clause.split("AND")[-1]

    def test_single_column_watermark(self):
        """Single column watermark generates simple > comparison."""
        watermark = {"updated_at": "2024-01-15T00:00:00"}
        result = _build_ordered_watermark(watermark)

        assert "updated_at > TIMESTAMP('2024-01-15T00:00:00')" in result
        # No OR needed for single column
        assert "OR" not in result

    def test_numeric_values(self):
        """Numeric watermark values are not quoted."""
        watermark = {"seq_id": 1000, "batch_num": 42}
        result = _build_ordered_watermark(watermark)

        assert "seq_id > 1000" in result
        assert "batch_num > 42" in result

    def test_zero_grace_period_ignored(self):
        """Zero grace_period_hours does not add TIMESTAMP_SUB."""
        watermark = {"updated_at": "2024-01-15T00:00:00"}
        result = _build_ordered_watermark(watermark, grace_period_hours=0)

        assert "TIMESTAMP_SUB" not in result


class TestBuildStagingSqlOrdered:
    """Tests for build_staging_sql() with cursor_mode settings."""

    def test_ordered_mode_two_column_watermark(self):
        """Ordered mode with 2-column watermark uses ordered comparison."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            watermark={
                "updated_at": "2024-01-15T00:00:00",
                "policy_id": 500,
            },
            cursor_mode="ordered",
        )
        sql = build_staging_sql(params).render()

        # Should use ordered tuple comparison
        assert "updated_at > TIMESTAMP('2024-01-15T00:00:00')" in sql
        assert "policy_id > 500" in sql
        assert "OR" in sql

    def test_independent_mode_uses_or_logic(self):
        """Independent mode with 2-column watermark uses OR logic."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            watermark={
                "updated_at": "2024-01-15T00:00:00",
                "policy_id": "2024-01-15T00:00:00",
            },
            cursor_mode="independent",
        )
        sql = build_staging_sql(params).render()

        # Should use independent (OR) comparison
        assert "updated_at >" in sql
        assert "policy_id >" in sql
        assert "OR" in sql

    def test_single_column_watermark_ignores_mode(self):
        """Single column watermark uses simple > regardless of mode."""
        for mode in ("ordered", "independent"):
            params = StagingParams(
                target_table="proj.ds.staged",
                source_name="src",
                source_table="proj.raw.data",
                unique_key="id",
                updated_at="updated_at",
                columns=["name"],
                watermark={"updated_at": "2024-01-01T00:00:00"},
                cursor_mode=mode,
            )
            sql = build_staging_sql(params).render()

            assert "updated_at >" in sql
            # Single-column should not produce the ordered tuple expansion
            # (no "= ... AND" pattern since there's only 1 column)


class TestBuildOrderByColumns:
    """Tests for the _build_order_by_columns() helper."""

    def test_ordered_mode_includes_all_watermark_columns(self):
        """Ordered mode ORDER BY includes all watermark columns."""
        params = StagingParams(
            target_table="p.d.target",
            source_name="s",
            source_table="p.d.source",
            unique_key="id",
            updated_at="updated_at",
            watermark={
                "updated_at": "2024-01-01T00:00:00",
                "policy_id": 100,
            },
            cursor_mode="ordered",
        )
        cols = _build_order_by_columns(params)

        assert "updated_at" in cols
        assert "policy_id" in cols
        assert "entity_uid" in cols

    def test_independent_mode_uses_updated_at(self):
        """Independent mode ORDER BY uses updated_at only."""
        params = StagingParams(
            target_table="p.d.target",
            source_name="s",
            source_table="p.d.source",
            unique_key="id",
            updated_at="updated_at",
            watermark={
                "updated_at": "2024-01-01T00:00:00",
                "policy_id": 100,
            },
            cursor_mode="independent",
        )
        cols = _build_order_by_columns(params)

        assert cols[0] == "updated_at"
        assert "entity_uid" in cols
        # policy_id is not in ORDER BY for independent mode
        assert "policy_id" not in cols

    def test_entity_uid_always_last(self):
        """entity_uid is always included as final tiebreaker."""
        params = StagingParams(
            target_table="p.d.target",
            source_name="s",
            source_table="p.d.source",
            unique_key="id",
            updated_at="updated_at",
            cursor_mode="ordered",
        )
        cols = _build_order_by_columns(params)
        assert cols[-1] == "entity_uid"

    def test_no_watermark_uses_updated_at(self):
        """Without watermark, ORDER BY uses updated_at."""
        params = StagingParams(
            target_table="p.d.target",
            source_name="s",
            source_table="p.d.source",
            unique_key="id",
            updated_at="updated_at",
        )
        cols = _build_order_by_columns(params)
        assert "updated_at" in cols
        assert "entity_uid" in cols

    def test_ordered_mode_with_batch_size_in_sql(self):
        """Ordered mode with batch_size produces ORDER BY with all watermark cols."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            watermark={
                "updated_at": "2024-01-15T00:00:00",
                "policy_id": 500,
            },
            cursor_mode="ordered",
            batch_size=10000,
        )
        sql = build_staging_sql(params).render()

        assert "ORDER BY" in sql
        assert "LIMIT 10000" in sql
        # Both watermark columns should be in ORDER BY
        order_section = sql[sql.index("ORDER BY"):]
        assert "updated_at" in order_section
        assert "policy_id" in order_section
        assert "entity_uid" in order_section

"""Tests for hash cursor virtual column injection in the staging builder."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.staging import (
    HashCursor,
    StagingParams,
    build_staging_sql,
)


class TestHashCursorInStaging:
    """Tests for hash cursor injection in build_staging_sql()."""

    def test_hash_cursor_adds_mod_expression(self):
        """Hash cursor adds MOD(FARM_FINGERPRINT(...)) to SELECT."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            hash_cursor=HashCursor(
                column="id",
                modulus=1000,
                alias="_hash_partition",
            ),
        )
        sql = build_staging_sql(params).render()

        assert "MOD(FARM_FINGERPRINT(CAST(id AS STRING)), 1000)" in sql
        assert "_hash_partition" in sql

    def test_no_hash_cursor_omits_hash_column(self):
        """Without hash cursor, no hash column is added."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
        )
        sql = build_staging_sql(params).render()

        assert "MOD(FARM_FINGERPRINT" not in sql
        assert "_hash_partition" not in sql

    def test_hash_cursor_alias_in_order_by(self):
        """Hash cursor alias appears in ORDER BY when batch_size is set."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            hash_cursor=HashCursor(
                column="id",
                modulus=1000,
                alias="_hash_partition",
            ),
            batch_size=50000,
        )
        sql = build_staging_sql(params).render()

        assert "ORDER BY" in sql
        order_section = sql[sql.index("ORDER BY"):]
        assert "_hash_partition" in order_section

    def test_custom_modulus(self):
        """Custom modulus value is used in MOD expression."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            hash_cursor=HashCursor(
                column="policy_number",
                modulus=500,
                alias="_policy_bucket",
            ),
        )
        sql = build_staging_sql(params).render()

        assert "MOD(FARM_FINGERPRINT(CAST(policy_number AS STRING)), 500)" in sql
        assert "_policy_bucket" in sql

    def test_custom_alias(self):
        """Custom alias is used in the AS clause."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            hash_cursor=HashCursor(
                column="id",
                modulus=2000,
                alias="_my_bucket",
            ),
        )
        sql = build_staging_sql(params).render()

        assert "AS _my_bucket" in sql

    def test_hash_cursor_combined_with_watermark(self):
        """Hash cursor works alongside watermark filtering."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            watermark={"updated_at": "2024-01-01T00:00:00"},
            hash_cursor=HashCursor(column="id", modulus=1000),
            batch_size=10000,
        )
        sql = build_staging_sql(params).render()

        # Both watermark and hash cursor should be present
        assert "updated_at >" in sql
        assert "MOD(FARM_FINGERPRINT" in sql
        assert "ORDER BY" in sql
        assert "LIMIT 10000" in sql

    def test_hash_cursor_without_batch_size_no_order_by(self):
        """Hash cursor without batch_size does not add ORDER BY."""
        params = StagingParams(
            target_table="proj.ds.staged",
            source_name="src",
            source_table="proj.raw.data",
            unique_key="id",
            updated_at="updated_at",
            columns=["name"],
            hash_cursor=HashCursor(column="id", modulus=1000),
        )
        sql = build_staging_sql(params).render()

        # Hash column should be in SELECT
        assert "MOD(FARM_FINGERPRINT" in sql
        # But no ORDER BY without batch_size
        assert "ORDER BY" not in sql

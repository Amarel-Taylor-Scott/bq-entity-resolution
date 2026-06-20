"""Tests for table_expiration_days in staging SQL builder."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.models.infrastructure import ScaleConfig
from bq_entity_resolution.sql.builders.staging import StagingParams, build_staging_sql


def _staging_params(**overrides) -> StagingParams:
    """Create minimal StagingParams."""
    defaults = dict(
        target_table="proj.ds.staged_customers",
        source_name="crm",
        source_table="proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=["first_name", "last_name", "email"],
    )
    defaults.update(overrides)
    return StagingParams(**defaults)


class TestTableExpirationInStaging:
    """Test table_expiration_days in staging SQL."""

    def test_expiration_includes_options(self):
        """Staging SQL includes OPTIONS clause when table_expiration_days is set."""
        params = _staging_params(table_expiration_days=30)
        sql = build_staging_sql(params).render()
        assert "OPTIONS(" in sql
        assert "expiration_timestamp" in sql
        assert "TIMESTAMP_ADD" in sql
        assert "INTERVAL 30 DAY" in sql

    def test_no_expiration_omits_options(self):
        """Staging SQL omits OPTIONS when table_expiration_days is None."""
        params = _staging_params(table_expiration_days=None)
        sql = build_staging_sql(params).render()
        assert "OPTIONS(" not in sql
        assert "expiration_timestamp" not in sql

    def test_expiration_with_various_days(self):
        """Different expiration day values produce correct SQL."""
        for days in [1, 7, 90, 365]:
            params = _staging_params(table_expiration_days=days)
            sql = build_staging_sql(params).render()
            assert f"INTERVAL {days} DAY" in sql

    def test_zero_expiration_not_set(self):
        """table_expiration_days=0 is not set at StagingParams level (no validation)."""
        # StagingParams is a frozen dataclass, not Pydantic.
        # Zero would produce an OPTIONS clause with INTERVAL 0 DAY
        # but the important validation is in ScaleConfig.
        params = _staging_params(table_expiration_days=0)
        sql = build_staging_sql(params).render()
        # With 0 as falsy, the if-check in build_staging_sql skips it
        assert "OPTIONS(" not in sql

    def test_expiration_appears_before_as(self):
        """OPTIONS clause appears before the AS keyword."""
        params = _staging_params(table_expiration_days=14)
        sql = build_staging_sql(params).render()
        options_pos = sql.index("OPTIONS(")
        as_pos = sql.index("\nAS\n") if "\nAS\n" in sql else sql.index("AS")
        assert options_pos < as_pos

    def test_expiration_with_partition_and_cluster(self):
        """OPTIONS clause coexists with PARTITION BY and CLUSTER BY."""
        params = _staging_params(
            table_expiration_days=7,
            partition_by="DATE(source_updated_at)",
            cluster_by=["entity_uid"],
        )
        sql = build_staging_sql(params).render()
        assert "PARTITION BY" in sql
        assert "CLUSTER BY" in sql
        assert "OPTIONS(" in sql
        assert "INTERVAL 7 DAY" in sql


class TestScaleConfigExpirationValidation:
    """Test ScaleConfig rejects invalid table_expiration_days."""

    def test_zero_rejected(self):
        """ScaleConfig rejects table_expiration_days=0."""
        with pytest.raises(ValueError, match="table_expiration_days must be >= 1"):
            ScaleConfig(table_expiration_days=0)

    def test_negative_rejected(self):
        """ScaleConfig rejects negative table_expiration_days."""
        with pytest.raises(ValueError, match="table_expiration_days must be >= 1"):
            ScaleConfig(table_expiration_days=-1)

    def test_one_accepted(self):
        """ScaleConfig accepts table_expiration_days=1."""
        config = ScaleConfig(table_expiration_days=1)
        assert config.table_expiration_days == 1

    def test_none_accepted(self):
        """ScaleConfig accepts None (default)."""
        config = ScaleConfig()
        assert config.table_expiration_days is None

    def test_large_value_accepted(self):
        """ScaleConfig accepts large values."""
        config = ScaleConfig(table_expiration_days=3650)
        assert config.table_expiration_days == 3650

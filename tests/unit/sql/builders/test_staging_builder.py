"""Tests for the staging SQL builder."""

from bq_entity_resolution.sql.builders.staging import (
    JoinDef,
    StagingParams,
    build_staging_sql,
)


def test_basic_staging():
    """Basic staging generates valid CREATE TABLE AS SELECT."""
    params = StagingParams(
        target_table="proj.ds.staged_customers",
        source_name="crm",
        source_table="proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=["first_name", "last_name", "email"],
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "proj.ds.staged_customers" in sql
    assert "FARM_FINGERPRINT" in sql
    assert "'crm'" in sql
    assert "first_name" in sql
    assert "last_name" in sql
    assert "email" in sql
    assert "source_updated_at" in sql
    assert "pipeline_loaded_at" in sql


def test_staging_with_watermark():
    """Incremental staging with watermark generates WHERE clause."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
        watermark={"updated_at": "2024-01-01T00:00:00"},
        grace_period_hours=6,
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "TIMESTAMP_SUB" in sql
    assert "INTERVAL 6 HOUR" in sql
    assert "updated_at >" in sql


def test_staging_full_refresh_ignores_watermark():
    """Full refresh skips watermark even when provided."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
        watermark={"updated_at": "2024-01-01T00:00:00"},
        full_refresh=True,
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "TIMESTAMP_SUB" not in sql


def test_staging_with_joins():
    """Staging with supplemental joins."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
        joins=[
            JoinDef(
                table="proj.ref.lookup",
                on="src.type_id = lookup.id",
                type="LEFT",
                alias="lookup",
            ),
        ],
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "LEFT JOIN" in sql
    assert "proj.ref.lookup" in sql
    assert "lookup" in sql


def test_staging_with_filter():
    """Source-level filter is included in WHERE."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
        filter="status = 'active'",
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "status = 'active'" in sql


def test_staging_with_batch_size():
    """Batch size adds ORDER BY + LIMIT clause for deterministic batching."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
        batch_size=10000,
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "LIMIT 10000" in sql
    assert "ORDER BY" in sql
    # ORDER BY must come before LIMIT
    assert sql.index("ORDER BY") < sql.index("LIMIT")


def test_staging_no_order_by_without_batch_size():
    """No ORDER BY when no batch_size is set."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "ORDER BY" not in sql
    assert "LIMIT" not in sql


def test_staging_with_partition_column():
    """Partition column exclusion filter."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="src",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=["name"],
        partition_column="_PARTITIONDATE",
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "_PARTITIONDATE < CURRENT_DATE()" in sql


def test_staging_sql_escape_source_name():
    """Source name with quotes is escaped."""
    params = StagingParams(
        target_table="proj.ds.staged",
        source_name="O'Brien's Data",
        source_table="proj.raw.data",
        unique_key="id",
        updated_at="updated_at",
        columns=[],
    )
    expr = build_staging_sql(params)
    sql = expr.render()

    assert "O''Brien''s Data" in sql


def test_staging_returns_sql_expression():
    """Builder returns SQLExpression, not raw string."""
    params = StagingParams(
        target_table="p.d.target",
        source_name="s",
        source_table="p.d.source",
        unique_key="id",
        updated_at="u",
    )
    expr = build_staging_sql(params)
    assert expr.is_raw is True
    assert isinstance(expr.render(), str)

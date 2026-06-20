"""Tests for canonical index initialization SQL builder."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.clustering import (
    CanonicalIndexInitParams,
    build_canonical_index_init_sql,
)


class TestBuildCanonicalIndexInitSql:
    """Tests for build_canonical_index_init_sql()."""

    def test_generates_create_table_if_not_exists(self):
        """SQL starts with CREATE TABLE IF NOT EXISTS."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "proj.gold.canonical_index" in sql

    def test_references_featured_table(self):
        """SQL references the featured table in FROM clause."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "proj.silver.featured" in sql

    def test_where_false_for_empty_schema_copy(self):
        """SQL uses WHERE FALSE to create an empty table with matching schema."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "WHERE FALSE" in sql

    def test_includes_entity_uid_as_cluster_id(self):
        """SQL includes entity_uid AS cluster_id in the SELECT."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "entity_uid AS cluster_id" in sql

    def test_cluster_by_included(self):
        """CLUSTER BY is included when provided."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
            cluster_by=["entity_uid", "cluster_id"],
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "CLUSTER BY entity_uid, cluster_id" in sql

    def test_cluster_by_default(self):
        """Default cluster_by is [entity_uid]."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "CLUSTER BY entity_uid" in sql

    def test_partition_by_included(self):
        """PARTITION BY is included when provided."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
            partition_by="DATE(source_updated_at)",
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "PARTITION BY DATE(source_updated_at)" in sql

    def test_partition_by_omitted_when_none(self):
        """PARTITION BY is not included when not provided."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
            partition_by=None,
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "PARTITION BY" not in sql

    def test_full_sql_structure(self):
        """Complete SQL has correct structure."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
            cluster_by=["entity_uid"],
            partition_by="DATE(source_updated_at)",
        )
        sql = build_canonical_index_init_sql(params).render()

        # Verify ordering: CREATE TABLE ... PARTITION BY ... CLUSTER BY ... AS SELECT ...
        create_pos = sql.index("CREATE TABLE IF NOT EXISTS")
        partition_pos = sql.index("PARTITION BY")
        cluster_pos = sql.index("CLUSTER BY")
        select_pos = sql.index("SELECT")
        where_pos = sql.index("WHERE FALSE")

        assert create_pos < partition_pos < cluster_pos < select_pos < where_pos

    def test_returns_sql_expression(self):
        """Builder returns an SQLExpression with is_raw True."""
        params = CanonicalIndexInitParams(
            canonical_table="p.d.target",
            source_table="p.d.source",
        )
        expr = build_canonical_index_init_sql(params)
        assert expr.is_raw is True
        assert isinstance(expr.render(), str)

    def test_empty_cluster_by_omits_clause(self):
        """Empty cluster_by list omits the CLUSTER BY clause."""
        params = CanonicalIndexInitParams(
            canonical_table="proj.gold.canonical_index",
            source_table="proj.silver.featured",
            cluster_by=[],
        )
        sql = build_canonical_index_init_sql(params).render()

        assert "CLUSTER BY" not in sql

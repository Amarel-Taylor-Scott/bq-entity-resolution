"""Tests for embeddings and LSH SQL builders."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.embeddings import (
    EmbeddingsParams,
    LSHParams,
    build_embeddings_sql,
    build_lsh_buckets_sql,
)


class TestBuildEmbeddingsSql:
    """Tests for build_embeddings_sql."""

    def test_returns_sql_expression(self):
        params = EmbeddingsParams(
            target_table="proj.silver.entity_embeddings",
            source_table="proj.silver.featured",
            concat_expression="CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, ''))",
            model_name="proj.ml.text_embed_model",
            dimensions=256,
        )
        result = build_embeddings_sql(params)
        sql = result.render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.silver.entity_embeddings" in sql
        assert "ML.GENERATE_TEXT_EMBEDDING" in sql

    def test_includes_model_reference(self):
        params = EmbeddingsParams(
            target_table="proj.silver.embeddings",
            source_table="proj.silver.featured",
            concat_expression="CONCAT(first_name, last_name)",
            model_name="proj.ml.my_model",
            dimensions=128,
        )
        sql = build_embeddings_sql(params).render()
        assert "proj.ml.my_model" in sql
        assert "128" in sql

    def test_filters_null_and_empty_text(self):
        params = EmbeddingsParams(
            target_table="p.d.target",
            source_table="p.d.source",
            concat_expression="col",
            model_name="p.ml.model",
            dimensions=64,
        )
        sql = build_embeddings_sql(params).render()
        assert "IS NOT NULL" in sql
        assert "CHAR_LENGTH" in sql

    def test_includes_entity_uid_join(self):
        params = EmbeddingsParams(
            target_table="p.d.target",
            source_table="p.d.source",
            concat_expression="col",
            model_name="p.ml.model",
            dimensions=64,
        )
        sql = build_embeddings_sql(params).render()
        assert "entity_uid" in sql
        assert "text_embedding" in sql


class TestBuildLshBucketsSql:
    """Tests for build_lsh_buckets_sql."""

    def test_returns_sql_expression(self):
        params = LSHParams(
            target_table="proj.silver.lsh_buckets",
            embedding_table="proj.silver.entity_embeddings",
            num_tables=4,
            num_functions=8,
            dimensions=256,
            seed=42,
        )
        result = build_lsh_buckets_sql(params)
        sql = result.render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.silver.lsh_buckets" in sql

    def test_generates_correct_number_of_bucket_columns(self):
        params = LSHParams(
            target_table="p.d.target",
            embedding_table="p.d.embeddings",
            num_tables=3,
            num_functions=4,
            dimensions=64,
            seed=42,
            bucket_prefix="lsh_bucket",
        )
        sql = build_lsh_buckets_sql(params).render()
        assert "lsh_bucket_0" in sql
        assert "lsh_bucket_1" in sql
        assert "lsh_bucket_2" in sql
        # Should not have bucket_3 since num_tables=3
        assert "lsh_bucket_3" not in sql

    def test_uses_farm_fingerprint_for_projections(self):
        params = LSHParams(
            target_table="p.d.target",
            embedding_table="p.d.embeddings",
            num_tables=2,
            num_functions=4,
            dimensions=64,
            seed=99,
        )
        sql = build_lsh_buckets_sql(params).render()
        assert "FARM_FINGERPRINT" in sql
        assert "99" in sql  # seed value

    def test_includes_dot_product_cte(self):
        params = LSHParams(
            target_table="p.d.target",
            embedding_table="p.d.embeddings",
            num_tables=2,
            num_functions=4,
            dimensions=64,
            seed=42,
        )
        sql = build_lsh_buckets_sql(params).render()
        assert "dot_products" in sql
        assert "dot_product" in sql

    def test_includes_signatures_cte(self):
        params = LSHParams(
            target_table="p.d.target",
            embedding_table="p.d.embeddings",
            num_tables=2,
            num_functions=4,
            dimensions=64,
            seed=42,
        )
        sql = build_lsh_buckets_sql(params).render()
        assert "signatures" in sql
        assert "bucket_hash" in sql
        assert "STRING_AGG" in sql

    def test_custom_bucket_prefix(self):
        params = LSHParams(
            target_table="p.d.target",
            embedding_table="p.d.embeddings",
            num_tables=2,
            num_functions=4,
            dimensions=64,
            seed=42,
            bucket_prefix="hash_band",
        )
        sql = build_lsh_buckets_sql(params).render()
        assert "hash_band_0" in sql
        assert "hash_band_1" in sql

    def test_dimension_variable_declared(self):
        params = LSHParams(
            target_table="p.d.target",
            embedding_table="p.d.embeddings",
            num_tables=2,
            num_functions=4,
            dimensions=128,
            seed=42,
        )
        sql = build_lsh_buckets_sql(params).render()
        assert "DECLARE dim INT64 DEFAULT 128" in sql

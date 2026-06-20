"""Tests for centralized table naming."""

from bq_entity_resolution.naming import (
    all_matches_table,
    candidates_table,
    canonical_index_table,
    checkpoint_table,
    cluster_table,
    embeddings_table,
    featured_table,
    labels_table,
    lsh_buckets_table,
    matches_table,
    parameters_table,
    resolved_table,
    review_queue_table,
    sql_audit_table,
    staged_table,
    term_frequency_table,
    udf_dataset,
)


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_config():
    project = _NS(
        bq_project="my-proj",
        bq_dataset_bronze="my-proj.bronze",
        bq_dataset_silver="my-proj.silver",
        bq_dataset_gold="my-proj.gold",
        bq_location="US",
        udf_dataset="udfs",
        watermark_dataset="meta",
    )
    config = _NS(project=project)
    config.fq_table = lambda attr, name: f"{getattr(project, attr)}.{name}"
    return config


class TestTableNaming:
    def test_staged_table(self):
        config = _make_config()
        assert staged_table(config, "crm") == "my-proj.bronze.staged_crm"

    def test_featured_table(self):
        config = _make_config()
        assert featured_table(config) == "my-proj.silver.featured"

    def test_candidates_table(self):
        config = _make_config()
        assert candidates_table(config, "exact") == "my-proj.silver.candidates_exact"

    def test_matches_table(self):
        config = _make_config()
        assert matches_table(config, "fuzzy") == "my-proj.silver.matches_fuzzy"

    def test_all_matches_table(self):
        config = _make_config()
        assert all_matches_table(config) == "my-proj.silver.all_matched_pairs"

    def test_cluster_table(self):
        config = _make_config()
        assert cluster_table(config) == "my-proj.silver.entity_clusters"

    def test_resolved_table(self):
        config = _make_config()
        assert resolved_table(config) == "my-proj.gold.resolved_entities"

    def test_canonical_index_table(self):
        config = _make_config()
        assert canonical_index_table(config) == "my-proj.gold.canonical_index"

    def test_embeddings_table(self):
        config = _make_config()
        assert embeddings_table(config) == "my-proj.silver.entity_embeddings"

    def test_lsh_buckets_table(self):
        config = _make_config()
        assert lsh_buckets_table(config) == "my-proj.silver.lsh_buckets"

    def test_udf_dataset(self):
        config = _make_config()
        assert udf_dataset(config) == "my-proj.udfs"

    def test_parameters_table(self):
        config = _make_config()
        assert parameters_table(config, "tier1") == "my-proj.silver.fs_parameters_tier1"

    def test_review_queue_table(self):
        config = _make_config()
        assert review_queue_table(config, "exact") == "my-proj.silver.al_review_queue_exact"

    def test_labels_table(self):
        config = _make_config()
        assert labels_table(config) == "my-proj.silver.al_labels"

    def test_term_frequency_table(self):
        config = _make_config()
        assert term_frequency_table(config) == "my-proj.silver.term_frequencies"

    def test_sql_audit_table(self):
        config = _make_config()
        assert sql_audit_table(config) == "my-proj.meta.pipeline_sql_audit"

    def test_checkpoint_table(self):
        config = _make_config()
        assert checkpoint_table(config) == "my-proj.meta.pipeline_checkpoints"

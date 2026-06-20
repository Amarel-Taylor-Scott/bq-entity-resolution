"""Tests for link type support in blocking."""

import pytest

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.sql.builders.blocking import (
    BlockingParams,
    BlockingPath,
    build_blocking_sql,
)


def _make_blocking_params(link_type=None, cross_batch=False):
    """Helper to create blocking params with a single path."""
    return BlockingParams(
        target_table="proj.silver.candidates_exact",
        source_table="proj.silver.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["bk_name_zip"]),
        ],
        tier_name="exact",
        link_type=link_type,
        cross_batch=cross_batch,
        canonical_table="proj.gold.canonical_index" if cross_batch else None,
    )


def test_default_link_type(sample_config):
    """Default link_type is 'link_and_dedupe'."""
    assert sample_config.link_type == "link_and_dedupe"


def test_link_and_dedupe_no_source_filter():
    """link_and_dedupe generates no source_name filter."""
    params = _make_blocking_params(link_type="link_and_dedupe")
    sql = build_blocking_sql(params).render()
    assert "l.source_name = r.source_name" not in sql
    assert "l.source_name != r.source_name" not in sql


def test_dedupe_only_same_source_filter():
    """dedupe_only adds AND l.source_name = r.source_name."""
    params = _make_blocking_params(link_type="dedupe_only")
    sql = build_blocking_sql(params).render()
    assert "l.source_name = r.source_name" in sql
    assert "l.source_name != r.source_name" not in sql


def test_link_only_different_source_filter():
    """link_only adds AND l.source_name != r.source_name."""
    params = _make_blocking_params(link_type="link_only")
    sql = build_blocking_sql(params).render()
    assert "l.source_name != r.source_name" in sql
    assert "l.source_name = r.source_name" not in sql


def test_link_type_applied_to_all_paths():
    """Link type filter applies to every blocking path."""
    params = BlockingParams(
        target_table="proj.silver.candidates_fuzzy",
        source_table="proj.silver.featured",
        blocking_paths=[
            BlockingPath(index=0, keys=["bk_name_zip"]),
            BlockingPath(index=1, keys=["bk_email"]),
        ],
        tier_name="fuzzy",
        link_type="dedupe_only",
    )
    sql = build_blocking_sql(params).render()
    # Both paths should contain the filter
    assert sql.count("l.source_name = r.source_name") >= 2


def test_link_type_applied_to_cross_batch():
    """Link type filter present in cross-batch section when enabled."""
    params = _make_blocking_params(link_type="link_only", cross_batch=True)
    sql = build_blocking_sql(params).render()
    # cross_path section should exist and contain source filter
    assert "cross_path_0" in sql
    assert "l.source_name != r.source_name" in sql


def test_link_type_invalid_value_rejected():
    """Invalid link_type values are rejected by schema validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PipelineConfig(
            version="1.0",
            project={"name": "t", "bq_project": "p", "bq_dataset_bronze": "b",
                      "bq_dataset_silver": "s", "bq_dataset_gold": "g",
                      "watermark_dataset": "w"},
            sources=[],
            matching_tiers=[],
            link_type="invalid_type",
        )


def test_link_type_passes_through_to_sql():
    """Blocking SQL reflects the link_type filter."""
    params = _make_blocking_params(link_type="dedupe_only")
    sql = build_blocking_sql(params).render()
    # Confirm intra-batch has the filter
    assert "intra_path_0" in sql
    assert "l.source_name = r.source_name" in sql

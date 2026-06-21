"""Opt-in per-pipeline table namespacing (fq_table)."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.naming import canonical_index_table, featured_table


@pytest.fixture
def cfg():
    return quick_config(
        bq_project="proj", source_table="proj.raw.c", unique_key="id",
        updated_at="u", column_roles={"first_name": "first_name"},
        project_name="Customer Dedup 2",
    )


def test_default_is_byte_identical(cfg):
    assert cfg.project.namespace_tables is False
    assert featured_table(cfg) == "proj.er_silver.featured"
    assert canonical_index_table(cfg) == "proj.er_gold.canonical_index"


def test_namespaced_prefixes_sanitized_pipeline_name(cfg):
    cfg.project.namespace_tables = True
    assert featured_table(cfg) == "proj.er_silver.customer_dedup_2_featured"
    assert canonical_index_table(cfg) == "proj.er_gold.customer_dedup_2_canonical_index"


def test_two_pipelines_no_longer_collide(cfg):
    a = quick_config(bq_project="proj", source_table="proj.raw.a", unique_key="id",
                     updated_at="u", column_roles={"first_name": "first_name"},
                     project_name="alpha")
    b = quick_config(bq_project="proj", source_table="proj.raw.b", unique_key="id",
                     updated_at="u", column_roles={"first_name": "first_name"},
                     project_name="beta")
    # Without namespacing they share tables (the collision the panel flagged).
    assert featured_table(a) == featured_table(b)
    a.project.namespace_tables = True
    b.project.namespace_tables = True
    assert featured_table(a) != featured_table(b)
    assert featured_table(a) == "proj.er_silver.alpha_featured"
    assert featured_table(b) == "proj.er_silver.beta_featured"

"""Tests for blocking effectiveness dashboard SQL builder."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.blocking_effectiveness import (
    BlockingEffectivenessParams,
    TierEffectivenessParams,
    build_blocking_effectiveness_sql,
)


class TestTierEffectivenessParams:
    """Tests for TierEffectivenessParams validation."""

    def test_valid_params(self):
        p = TierEffectivenessParams(
            tier_name="exact",
            candidates_table="proj.ds.candidates_exact",
            source_table="proj.ds.featured",
        )
        assert p.tier_name == "exact"

    def test_validates_candidates_table(self):
        with pytest.raises(ValueError):
            TierEffectivenessParams(
                tier_name="exact",
                candidates_table="invalid",
                source_table="proj.ds.featured",
            )

    def test_validates_source_table(self):
        with pytest.raises(ValueError):
            TierEffectivenessParams(
                tier_name="exact",
                candidates_table="proj.ds.candidates",
                source_table="invalid",
            )


class TestBlockingEffectivenessParams:
    """Tests for BlockingEffectivenessParams validation."""

    def test_valid_params(self):
        p = BlockingEffectivenessParams(
            tier_reports=[
                TierEffectivenessParams(
                    tier_name="exact",
                    candidates_table="proj.ds.c",
                    source_table="proj.ds.s",
                ),
            ],
        )
        assert len(p.tier_reports) == 1

    def test_rejects_empty_tiers(self):
        with pytest.raises(ValueError, match="At least one tier"):
            BlockingEffectivenessParams(tier_reports=[])


class TestBuildBlockingEffectivenessSql:
    """Tests for build_blocking_effectiveness_sql."""

    def test_single_tier(self):
        params = BlockingEffectivenessParams(
            tier_reports=[
                TierEffectivenessParams(
                    tier_name="exact",
                    candidates_table="proj.ds.candidates_exact",
                    source_table="proj.ds.featured",
                ),
            ],
        )
        sql = build_blocking_effectiveness_sql(params).render()
        assert "'exact'" in sql
        assert "cartesian_baseline" in sql
        assert "reduction_ratio" in sql
        assert "avg_candidates_per_entity" in sql
        assert "max_candidates_per_entity" in sql

    def test_multiple_tiers_union(self):
        params = BlockingEffectivenessParams(
            tier_reports=[
                TierEffectivenessParams(
                    tier_name="exact",
                    candidates_table="proj.ds.candidates_exact",
                    source_table="proj.ds.featured",
                ),
                TierEffectivenessParams(
                    tier_name="fuzzy",
                    candidates_table="proj.ds.candidates_fuzzy",
                    source_table="proj.ds.featured",
                ),
            ],
        )
        sql = build_blocking_effectiveness_sql(params).render()
        assert "UNION ALL" in sql
        assert "'exact'" in sql
        assert "'fuzzy'" in sql

    def test_references_correct_tables(self):
        params = BlockingEffectivenessParams(
            tier_reports=[
                TierEffectivenessParams(
                    tier_name="t1",
                    candidates_table="proj.ds.cand",
                    source_table="proj.ds.src",
                ),
            ],
        )
        sql = build_blocking_effectiveness_sql(params).render()
        assert "proj.ds.cand" in sql
        assert "proj.ds.src" in sql

    def test_uses_left_entity_uid(self):
        params = BlockingEffectivenessParams(
            tier_reports=[
                TierEffectivenessParams(
                    tier_name="t1",
                    candidates_table="proj.ds.c",
                    source_table="proj.ds.s",
                ),
            ],
        )
        sql = build_blocking_effectiveness_sql(params).render()
        assert "left_entity_uid" in sql

    def test_includes_timestamp(self):
        params = BlockingEffectivenessParams(
            tier_reports=[
                TierEffectivenessParams(
                    tier_name="t1",
                    candidates_table="proj.ds.c",
                    source_table="proj.ds.s",
                ),
            ],
        )
        sql = build_blocking_effectiveness_sql(params).render()
        assert "CURRENT_TIMESTAMP()" in sql

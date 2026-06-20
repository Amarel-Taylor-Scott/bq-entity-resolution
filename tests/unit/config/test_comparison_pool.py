"""Tests for comparison pool and ref-based comparison resolution."""

import pytest

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)


def _minimal_config(**overrides) -> PipelineConfig:
    """Build a minimal PipelineConfig for pool tests."""
    defaults = dict(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=[SourceConfig(
            name="src",
            table="proj.ds.src",
            unique_key="id",
            updated_at="updated_at",
            columns=[ColumnMapping(name="email"), ColumnMapping(name="name")],
        )],
        feature_engineering=FeatureEngineeringConfig(
            blocking_keys=[BlockingKeyDef(
                name="bk_email",
                function="farm_fingerprint",
                inputs=["email"],
            )],
        ),
        matching_tiers=[MatchingTierConfig(
            name="exact",
            blocking=TierBlockingConfig(
                paths=[BlockingPathDef(keys=["bk_email"])],
            ),
            comparisons=[ComparisonDef(
                left="email", right="email", method="exact", weight=5.0,
            )],
            threshold=ThresholdConfig(method="sum", min_score=3.0),
        )],
    )
    defaults.update(overrides)
    return PipelineConfig(**defaults)


class TestComparisonPoolResolution:
    """Test comparison pool ref resolution in PipelineConfig."""

    def test_pool_ref_resolves_to_full_comparison(self):
        """A ref-only comparison is resolved to the pool entry."""
        config = _minimal_config(
            comparison_pool={
                "email_exact": ComparisonDef(
                    left="email", right="email", method="exact", weight=5.0,
                ),
            },
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(ref="email_exact")],
                threshold=ThresholdConfig(method="sum", min_score=3.0),
            )],
        )
        comp = config.matching_tiers[0].comparisons[0]
        assert comp.left == "email"
        assert comp.right == "email"
        assert comp.method == "exact"
        assert comp.weight == 5.0
        assert comp.ref is None  # ref is cleared after resolution

    def test_pool_ref_with_weight_override(self):
        """Tier-level weight overrides the pool default."""
        config = _minimal_config(
            comparison_pool={
                "email_exact": ComparisonDef(
                    left="email", right="email", method="exact", weight=5.0,
                ),
            },
            matching_tiers=[MatchingTierConfig(
                name="fuzzy",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(ref="email_exact", weight=2.0)],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            )],
        )
        comp = config.matching_tiers[0].comparisons[0]
        assert comp.weight == 2.0  # overridden
        assert comp.method == "exact"  # inherited from pool

    def test_unknown_pool_ref_raises(self):
        """Referencing a non-existent pool entry raises ValueError."""
        with pytest.raises(ValueError, match="unknown.*comparison_pool ref.*ghost"):
            _minimal_config(
                comparison_pool={},
                matching_tiers=[MatchingTierConfig(
                    name="exact",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk_email"])],
                    ),
                    comparisons=[ComparisonDef(ref="ghost")],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                )],
            )

    def test_inline_comparisons_still_work(self):
        """Inline comparisons (no ref) are passed through unchanged."""
        config = _minimal_config(
            comparison_pool={
                "email_exact": ComparisonDef(
                    left="email", right="email", method="exact", weight=5.0,
                ),
            },
        )
        comp = config.matching_tiers[0].comparisons[0]
        assert comp.left == "email"
        assert comp.method == "exact"

    def test_mixed_ref_and_inline(self):
        """Tiers can mix pool refs and inline comparisons."""
        config = _minimal_config(
            comparison_pool={
                "email_exact": ComparisonDef(
                    left="email", right="email", method="exact", weight=5.0,
                ),
            },
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[
                    ComparisonDef(ref="email_exact"),
                    ComparisonDef(
                        left="name", right="name",
                        method="jaro_winkler", weight=2.0,
                    ),
                ],
                threshold=ThresholdConfig(method="sum", min_score=3.0),
            )],
        )
        comps = config.matching_tiers[0].comparisons
        assert len(comps) == 2
        assert comps[0].left == "email"
        assert comps[1].left == "name"

    def test_multiple_tiers_share_pool(self):
        """Multiple tiers can reference the same pool entries with different weights."""
        pool = {
            "email_exact": ComparisonDef(
                left="email", right="email", method="exact", weight=5.0,
            ),
        }
        config = _minimal_config(
            comparison_pool=pool,
            matching_tiers=[
                MatchingTierConfig(
                    name="exact",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk_email"])],
                    ),
                    comparisons=[ComparisonDef(ref="email_exact")],
                    threshold=ThresholdConfig(method="sum", min_score=4.0),
                ),
                MatchingTierConfig(
                    name="fuzzy",
                    blocking=TierBlockingConfig(
                        paths=[BlockingPathDef(keys=["bk_email"])],
                    ),
                    comparisons=[ComparisonDef(ref="email_exact", weight=2.5)],
                    threshold=ThresholdConfig(method="sum", min_score=1.0),
                ),
            ],
        )
        assert config.matching_tiers[0].comparisons[0].weight == 5.0  # pool default
        assert config.matching_tiers[1].comparisons[0].weight == 2.5  # overridden

    def test_empty_pool_with_no_refs_works(self):
        """Empty comparison_pool is fine when no refs are used."""
        config = _minimal_config(comparison_pool={})
        assert len(config.matching_tiers[0].comparisons) == 1

    def test_pool_entry_not_contaminated_by_override(self):
        """Pool entry is not mutated when a tier overrides a field."""
        pool_entry = ComparisonDef(
            left="email", right="email", method="exact", weight=5.0,
        )
        config = _minimal_config(
            comparison_pool={"email_exact": pool_entry},
            matching_tiers=[MatchingTierConfig(
                name="exact",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk_email"])],
                ),
                comparisons=[ComparisonDef(ref="email_exact", weight=3.0)],
                threshold=ThresholdConfig(method="sum", min_score=1.0),
            )],
        )
        # Original pool entry unchanged
        assert pool_entry.weight == 5.0
        # Resolved comparison has override
        assert config.matching_tiers[0].comparisons[0].weight == 3.0

    def test_to_yaml_includes_pool(self):
        """to_yaml() serializes comparison_pool."""
        config = _minimal_config(
            comparison_pool={
                "email_exact": ComparisonDef(
                    left="email", right="email", method="exact", weight=5.0,
                ),
            },
        )
        yaml_str = config.to_yaml()
        assert "comparison_pool" in yaml_str
        assert "email_exact" in yaml_str

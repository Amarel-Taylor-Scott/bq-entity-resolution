"""Tests for preset auto-wiring into comparison pool."""

from bq_entity_resolution.config.presets import (
    business_dedup_preset,
    person_dedup_preset,
    person_linkage_preset,
    quick_config,
)


class TestPresetComparisonPool:
    """Verify presets populate comparison_pool and use refs in tiers."""

    def test_quick_config_populates_pool(self):
        """quick_config generates a comparison_pool dict."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.customers",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        assert len(config.comparison_pool) > 0

    def test_quick_config_tiers_use_resolved_refs(self):
        """After construction, tier comparisons are fully resolved."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.customers",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        for tier in config.matching_tiers:
            for comp in tier.comparisons:
                # All refs should be resolved (ref cleared to None)
                assert comp.ref is None
                # All comparisons should have left/right/method
                assert comp.left != ""
                assert comp.right != ""
                assert comp.method != ""

    def test_pool_names_match_role_comparisons(self):
        """Pool keys follow {column}_{suffix} naming from roles."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"email": "email"},
        )
        pool_names = list(config.comparison_pool.keys())
        # Email role generates email_exact comparison
        assert any("email" in name for name in pool_names)

    def test_person_dedup_populates_pool(self):
        """person_dedup_preset generates a comparison_pool."""
        config = person_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.people",
            columns={"first_name": "first_name", "last_name": "last_name"},
        )
        assert len(config.comparison_pool) > 0
        # Comparisons should be resolved
        for tier in config.matching_tiers:
            assert all(c.method != "" for c in tier.comparisons)

    def test_person_linkage_populates_pool(self):
        """person_linkage_preset generates a comparison_pool."""
        config = person_linkage_preset(
            bq_project="test-proj",
            source_tables=[
                {"name": "crm", "table": "test-proj.raw.crm"},
                {"name": "erp", "table": "test-proj.raw.erp"},
            ],
            columns={"first_name": "first_name", "last_name": "last_name"},
        )
        assert len(config.comparison_pool) > 0

    def test_business_dedup_populates_pool(self):
        """business_dedup_preset generates a comparison_pool."""
        config = business_dedup_preset(
            bq_project="test-proj",
            source_table="test-proj.raw.companies",
            columns={"company": "company_name", "tax_id": "ein"},
        )
        assert len(config.comparison_pool) > 0

    def test_pool_entries_have_weight(self):
        """Pool entries carry weights from role-based generation."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"email": "email"},
        )
        for comp in config.comparison_pool.values():
            assert comp.weight > 0

    def test_both_tiers_share_same_pool(self):
        """Exact and fuzzy tiers reference the same comparisons."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        exact_methods = {c.method for c in config.matching_tiers[0].comparisons}
        fuzzy_methods = {c.method for c in config.matching_tiers[1].comparisons}
        assert exact_methods == fuzzy_methods  # same set of comparisons

    def test_threshold_calculated_from_pool_weights(self):
        """Tier thresholds are calculated from pool entry weights."""
        config = quick_config(
            bq_project="test-proj",
            source_table="test-proj.raw.data",
            column_roles={"fn": "first_name", "ln": "last_name"},
        )
        total_weight = sum(c.weight for c in config.comparison_pool.values())
        exact_threshold = config.matching_tiers[0].threshold.min_score
        fuzzy_threshold = config.matching_tiers[1].threshold.min_score
        # Exact = 70% of total, fuzzy = 40%
        assert abs(exact_threshold - total_weight * 0.7) < 0.01
        assert abs(fuzzy_threshold - total_weight * 0.4) < 0.01

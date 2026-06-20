"""Tests for CompoundSplitter SQL generation."""

from __future__ import annotations

from bq_entity_resolution.compound.splitter import CompoundSplitter


class TestCompoundSplitter:
    def test_default_columns(self):
        sp = CompoundSplitter()
        assert sp.name_col == "first_name"
        assert sp.last_name_col == "last_name"
        assert sp.uid_col == "entity_uid"
        assert sp.flag_col == "is_compound_name"

    def test_custom_columns(self):
        sp = CompoundSplitter(
            name_col="fname",
            last_name_col="lname",
            uid_col="id",
            flag_col="is_compound",
        )
        assert sp.name_col == "fname"
        assert sp.last_name_col == "lname"
        assert sp.uid_col == "id"
        assert sp.flag_col == "is_compound"

    def test_build_split_cte_contains_union_all(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("my_project.dataset.staged")
        assert "UNION ALL" in cte
        assert cte.count("UNION ALL") == 2  # 3 parts: non-compound + 2 splits

    def test_build_split_cte_references_source(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("proj.data.staged_customers")
        assert "proj.data.staged_customers" in cte

    def test_build_split_cte_preserves_original_uid(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("source")
        assert "_original_entity_uid" in cte

    def test_build_split_cte_has_split_index(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("source")
        assert "_split_index" in cte
        assert "0 AS _split_index" in cte
        assert "1 AS _split_index" in cte

    def test_build_split_cte_filters_on_flag(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("source")
        assert "is_compound_name = 0" in cte
        assert "is_compound_name = 1" in cte

    def test_build_split_cte_custom_flag(self):
        sp = CompoundSplitter(flag_col="my_flag")
        cte = sp.build_split_cte("source")
        assert "my_flag = 0" in cte
        assert "my_flag = 1" in cte

    def test_build_split_cte_extracts_names(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("source")
        assert "REGEXP_EXTRACT" in cte

    def test_build_split_cte_starts_with_name(self):
        sp = CompoundSplitter()
        cte = sp.build_split_cte("source")
        assert cte.strip().startswith("compound_split AS (")

    def test_uid_expression(self):
        sp = CompoundSplitter()
        expr = sp.build_uid_expression()
        assert "CONCAT" in expr
        assert "_original_entity_uid" in expr
        assert "_split_index" in expr

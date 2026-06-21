"""Unit tests for the leaf-based resolution SQL builder."""

from __future__ import annotations

import pytest

from bq_entity_resolution.sql.builders.leaf import (
    LeafBlockingPath,
    LeafScoreTerm,
    LeafSQLParams,
    build_leaf_sql,
)


def _params(**overrides) -> LeafSQLParams:
    base = dict(
        target_table="p.d.leaf_pairs_new_x_new",
        leaf_name="new_x_new",
        left_table="p.d.featured",
        right_table="p.d.featured",
        blocking_paths=[LeafBlockingPath(keys=["bk_email"])],
        score_terms=[
            LeafScoreTerm(
                name="email_exact",
                sql_expr="l.email = r.email AND l.email IS NOT NULL",
                weight=1.0,
            )
        ],
        is_self_join=True,
    )
    base.update(overrides)
    return LeafSQLParams(**base)


class TestLeafBuilderValidation:
    def test_requires_blocking_path(self) -> None:
        with pytest.raises(ValueError, match="at least one blocking path"):
            _params(blocking_paths=[])

    def test_requires_score_term(self) -> None:
        with pytest.raises(ValueError, match="at least one score term"):
            _params(score_terms=[])

    def test_blocking_path_requires_key(self) -> None:
        with pytest.raises(ValueError, match="at least one key"):
            LeafBlockingPath(keys=[])

    def test_rejects_bad_table_ref(self) -> None:
        with pytest.raises(ValueError):
            _params(target_table="not a table")

    def test_rejects_bad_leaf_name(self) -> None:
        with pytest.raises(ValueError):
            _params(leaf_name="bad name!")

    def test_rejects_bad_short_circuit_key(self) -> None:
        with pytest.raises(ValueError):
            _params(exact_key_short_circuit=["bad key"])

    def test_max_pairs_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_pairs"):
            _params(max_pairs=0)

    def test_score_term_rejects_empty_expr(self) -> None:
        with pytest.raises(ValueError, match="empty sql_expr"):
            LeafScoreTerm(name="x", sql_expr="   ")


class TestLeafBuilderSQL:
    def test_contains_create_and_target(self) -> None:
        sql = build_leaf_sql(_params()).render("bigquery")
        assert "CREATE OR REPLACE TABLE `p.d.leaf_pairs_new_x_new`" in sql

    def test_contains_blocking_join(self) -> None:
        sql = build_leaf_sql(_params()).render("bigquery")
        # The blocking join condition appears in the ON clause.
        assert "l.bk_email = r.bk_email" in sql
        assert "l.bk_email IS NOT NULL" in sql
        assert "JOIN leaf_r r" in sql

    def test_self_join_uses_lt_guard(self) -> None:
        sql = build_leaf_sql(_params(is_self_join=True, symmetric=True)).render("bigquery")
        assert "l.entity_uid < r.entity_uid" in sql

    def test_cross_partition_uses_ne_guard(self) -> None:
        sql = build_leaf_sql(
            _params(
                leaf_name="new_x_old",
                right_table="p.d.canonical_index",
                is_self_join=False,
            )
        ).render("bigquery")
        assert "l.entity_uid != r.entity_uid" in sql
        assert "l.entity_uid < r.entity_uid" not in sql

    def test_asymmetric_self_join_uses_ne_guard(self) -> None:
        sql = build_leaf_sql(
            _params(is_self_join=True, symmetric=False)
        ).render("bigquery")
        assert "l.entity_uid != r.entity_uid" in sql

    def test_threshold_filter_present(self) -> None:
        sql = build_leaf_sql(_params(threshold=0.85)).render("bigquery")
        assert ">= 0.85" in sql

    def test_tags_pairs_with_leaf_name(self) -> None:
        sql = build_leaf_sql(_params(leaf_name="new_x_new")).render("bigquery")
        assert "'new_x_new' AS match_leaf" in sql

    def test_short_circuit_union_branch(self) -> None:
        sql = build_leaf_sql(
            _params(exact_key_short_circuit=["email_norm", "phone_e164"])
        ).render("bigquery")
        assert "UNION ALL" in sql
        assert "'short_circuit' AS match_method" in sql
        assert "l.email_norm = r.email_norm" in sql
        assert "l.phone_e164 = r.phone_e164" in sql

    def test_no_short_circuit_when_empty(self) -> None:
        sql = build_leaf_sql(_params(exact_key_short_circuit=[])).render("bigquery")
        assert "short_circuit" not in sql
        assert "UNION ALL" not in sql

    def test_max_pairs_cap(self) -> None:
        sql = build_leaf_sql(_params(max_pairs=500)).render("bigquery")
        assert "LIMIT 500" in sql

    def test_no_cap_when_unlimited(self) -> None:
        sql = build_leaf_sql(_params(max_pairs=None)).render("bigquery")
        assert "LIMIT" not in sql

    def test_predicates_render_into_partition_ctes(self) -> None:
        sql = build_leaf_sql(
            _params(
                left_predicate="source = 'crm'",
                right_predicate="updated_at >= 5",
            )
        ).render("bigquery")
        assert "WHERE source = 'crm'" in sql
        assert "WHERE updated_at >= 5" in sql

    def test_multiple_blocking_paths_are_ored(self) -> None:
        sql = build_leaf_sql(
            _params(
                blocking_paths=[
                    LeafBlockingPath(keys=["bk_email"]),
                    LeafBlockingPath(keys=["bk_last", "bk_zip"]),
                ]
            )
        ).render("bigquery")
        assert " OR " in sql
        # Composite path ANDs both keys (with NULL guards between them).
        assert "l.bk_last = r.bk_last" in sql
        assert "l.bk_zip = r.bk_zip" in sql

    def test_multiple_score_terms_use_greatest(self) -> None:
        sql = build_leaf_sql(
            _params(
                score_terms=[
                    LeafScoreTerm("a", "l.a = r.a", 1.0),
                    LeafScoreTerm("b", "l.b = r.b", 0.5),
                ]
            )
        ).render("bigquery")
        assert "GREATEST(" in sql

    def test_sql_parses_in_duckdb(self) -> None:
        expr = build_leaf_sql(
            _params(exact_key_short_circuit=["email"], max_pairs=100)
        )
        # SQLExpression.validate parses the rendered SQL; no errors expected.
        assert expr.validate("duckdb") == []

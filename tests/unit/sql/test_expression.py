"""Tests for the SQLExpression wrapper."""

import pytest

from bq_entity_resolution.sql.expression import SQLExpression


def test_raw_sql_expression():
    """Can create an expression from raw SQL."""
    expr = SQLExpression.from_raw("SELECT 1")
    assert expr.is_raw is True
    assert expr.render() == "SELECT 1"


def test_raw_sql_render_ignores_dialect():
    """Raw SQL is returned as-is regardless of dialect."""
    expr = SQLExpression.from_raw("SELECT `table`.col FROM `proj.ds.table`")
    assert expr.render("bigquery") == expr.render("duckdb")


def test_node_expression():
    """Can create from a sqlglot AST node."""
    import sqlglot
    node = sqlglot.parse_one("SELECT 1 AS x")
    expr = SQLExpression.from_node(node)
    assert expr.is_raw is False
    assert expr.node is not None
    rendered = expr.render("bigquery")
    assert "1" in rendered


def test_must_provide_node_or_raw():
    """Constructor requires either node or raw_sql."""
    with pytest.raises(ValueError, match="Must provide"):
        SQLExpression()


def test_repr_raw():
    """repr shows raw SQL preview."""
    expr = SQLExpression.from_raw("SELECT * FROM table")
    assert "raw=" in repr(expr)


def test_repr_node():
    """repr shows node type."""
    import sqlglot
    node = sqlglot.parse_one("SELECT 1")
    expr = SQLExpression.from_node(node)
    assert "node=" in repr(expr)


def test_validate_valid_sql():
    """validate returns empty list for valid SQL."""
    expr = SQLExpression.from_raw("SELECT 1 AS x FROM table1")
    errors = expr.validate("bigquery")
    assert errors == []


def test_render_different_dialects():
    """sqlglot node renders differently for different dialects."""
    import sqlglot
    # Parse as bigquery (uses backticks)
    node = sqlglot.parse_one("SELECT x FROM my_table", read="bigquery")
    expr = SQLExpression.from_node(node)

    bq_sql = expr.render("bigquery")
    duck_sql = expr.render("duckdb")
    # Both should contain the table name
    assert "my_table" in bq_sql
    assert "my_table" in duck_sql

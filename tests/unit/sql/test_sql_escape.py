"""Tests for SQL string escaping utilities."""

from bq_entity_resolution.sql.utils import bq_escape, sql_escape


def test_sql_escape_doubles_quotes():
    """sql_escape doubles single quotes."""
    assert sql_escape("O'Brien") == "O''Brien"
    assert sql_escape("it's a 'test'") == "it''s a ''test''"


def test_sql_escape_no_change_for_safe_strings():
    """sql_escape returns safe strings unchanged."""
    assert sql_escape("hello") == "hello"
    assert sql_escape("source_alpha") == "source_alpha"


def test_bq_escape_reserved_word():
    """Reserved words get backtick-escaped."""
    assert bq_escape("SELECT") == "`SELECT`"
    assert bq_escape("FROM") == "`FROM`"


def test_bq_escape_normal():
    """Normal identifiers are returned unchanged."""
    assert bq_escape("my_column") == "my_column"


def test_bq_escape_with_dot():
    """Dotted identifiers get backtick-escaped."""
    assert bq_escape("project.dataset") == "`project.dataset`"


def test_bq_escape_with_hyphen():
    """Hyphenated identifiers get backtick-escaped."""
    assert bq_escape("my-project") == "`my-project`"

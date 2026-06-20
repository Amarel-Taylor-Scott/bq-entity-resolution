"""Tests for SQL identifier and table reference validators."""

import pytest

from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref


class TestValidateIdentifier:
    def test_simple_name(self):
        assert validate_identifier("first_name") == "first_name"

    def test_leading_underscore(self):
        assert validate_identifier("_private") == "_private"

    def test_alphanumeric(self):
        assert validate_identifier("col123") == "col123"

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("first name")

    def test_rejects_semicolons(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("col; DROP TABLE")

    def test_rejects_quotes(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("col'name")

    def test_rejects_double_quotes(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier('col"name')

    def test_rejects_dots(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("schema.table")

    def test_rejects_hyphens(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("my-column")

    def test_rejects_leading_digit(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("123col")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("")

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid SQL"):
            validate_identifier("x; DROP TABLE users--")

    def test_custom_context(self):
        with pytest.raises(ValueError, match="column name"):
            validate_identifier("bad col", context="column name")


class TestValidateTableRef:
    def test_simple_three_part(self):
        assert validate_table_ref("project.dataset.table") == "project.dataset.table"

    def test_with_backticks(self):
        assert validate_table_ref("`project.dataset.table`") == "`project.dataset.table`"

    def test_with_hyphens_in_project(self):
        assert validate_table_ref("my-project.dataset.table") == "my-project.dataset.table"

    def test_rejects_two_parts(self):
        with pytest.raises(ValueError, match="Invalid table reference"):
            validate_table_ref("dataset.table")

    def test_rejects_one_part(self):
        with pytest.raises(ValueError, match="Invalid table reference"):
            validate_table_ref("table")

    def test_rejects_four_parts(self):
        with pytest.raises(ValueError, match="Invalid table reference"):
            validate_table_ref("a.b.c.d")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid table reference"):
            validate_table_ref("project.dataset.my table")

    def test_rejects_semicolons(self):
        with pytest.raises(ValueError, match="Invalid table reference"):
            validate_table_ref("project.dataset.table;DROP")

    def test_underscores_in_all_parts(self):
        result = validate_table_ref("my_project.my_dataset.my_table")
        assert result == "my_project.my_dataset.my_table"

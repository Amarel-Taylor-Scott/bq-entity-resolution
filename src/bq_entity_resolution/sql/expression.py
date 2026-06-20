"""SQLExpression: composable, dialect-aware SQL wrapper using sqlglot.

This is the foundation for the builder-based SQL generation system.
Each builder function returns an SQLExpression that can be:
1. Rendered to any supported dialect (bigquery, duckdb)
2. Validated syntactically
3. Inspected as an AST for testing
4. Composed with other expressions
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


class SQLExpression:
    """Wrapper around a sqlglot expression or raw SQL string.

    Supports two modes:
    - AST mode: wraps a sqlglot.Expression for full dialect translation
    - Raw mode: wraps a SQL string for templates that haven't been
      converted to builders yet (transitional)
    """

    def __init__(
        self,
        node: exp.Expression | None = None,
        raw_sql: str | None = None,
    ):
        if node is None and raw_sql is None:
            raise ValueError("Must provide either node or raw_sql")
        self._node = node
        self._raw_sql = raw_sql

    @classmethod
    def from_raw(cls, sql: str) -> SQLExpression:
        """Create from a raw SQL string (transitional, for templates)."""
        return cls(raw_sql=sql)

    @classmethod
    def from_node(cls, node: exp.Expression) -> SQLExpression:
        """Create from a sqlglot AST node."""
        return cls(node=node)

    @property
    def node(self) -> exp.Expression | None:
        """The sqlglot AST node, or None if raw SQL."""
        return self._node

    @property
    def is_raw(self) -> bool:
        """True if this is a raw SQL string (not yet converted to builder)."""
        return self._raw_sql is not None

    def render(self, dialect: str = "bigquery") -> str:
        """Render the expression to SQL for the given dialect."""
        if self._raw_sql is not None:
            return self._raw_sql
        if self._node is None:
            raise ValueError("SQLExpression has neither raw_sql nor AST node")
        return self._node.sql(dialect=dialect, pretty=True)

    def validate(self, dialect: str = "bigquery") -> list[str]:
        """Parse the rendered SQL and return any validation errors."""
        rendered = self.render(dialect)
        errors = []
        try:
            sqlglot.transpile(
                rendered,
                read=dialect,
                error_level=sqlglot.ErrorLevel.WARN,
            )
        except sqlglot.errors.ParseError as e:
            errors.append(str(e))
        return errors

    def __repr__(self) -> str:
        if self._raw_sql is not None:
            preview = self._raw_sql[:80].replace("\n", " ")
            return f"SQLExpression(raw='{preview}...')"
        return f"SQLExpression(node={type(self._node).__name__})"

"""BQ scripting interpreter: DECLARE, SET, IF, WHILE, LOOP handling.

Interprets BigQuery procedural scripting constructs (DECLARE/WHILE/SET/LOOP)
in Python, executing individual SQL statements against DuckDB.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import duckdb

logger = logging.getLogger(__name__)

_SCRIPTING_LOOP_MAX_ITERATIONS = 100


def is_bq_scripting(sql: str) -> bool:
    """Detect if SQL contains BQ scripting constructs.

    Uses line-start anchoring to avoid matching keywords inside
    comments, string literals, or substrings (e.g. a column named
    ``declared_amount``).
    """
    upper = sql.upper()
    # Match only at the start of a line (with optional leading whitespace)
    return bool(
        re.search(r'^\s*DECLARE\b', upper, re.MULTILINE)
        or re.search(r'^\s*SET\s+\w+\s*=', sql, re.IGNORECASE | re.MULTILINE)
        or re.search(r'^\s*BEGIN\b', upper, re.MULTILINE)
        or re.search(r'^\s*WHILE\b', upper, re.MULTILINE)
    )


def execute_bq_scripting(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    split_fn: Callable[[str], list[str]],
) -> int:
    """Interpret BQ scripting (DECLARE/WHILE/SET/LOOP) in Python.

    Args:
        conn: DuckDB connection to execute statements against.
        sql: The full SQL script containing BQ scripting constructs.
        split_fn: Function to split SQL into individual statements.

    Returns:
        Number of rows affected across all statements.
    """
    total_rows = 0
    variables: dict[str, object] = {}

    # Parse DECLARE statements
    for m in re.finditer(
        r'DECLARE\s+(\w+)\s+(\w+)(?:\s+DEFAULT\s+(.+?))?;',
        sql, re.IGNORECASE,
    ):
        var_name = m.group(1)
        default_val = m.group(3)
        if default_val is not None:
            default_val = default_val.strip()
            # Try to evaluate as SQL
            try:
                rows = conn.execute(f"SELECT {default_val}").fetchall()
                variables[var_name] = rows[0][0]
            except Exception as e:
                logger.debug("DECLARE DEFAULT eval failed for %s: %s", var_name, e)
                # Try as literal
                try:
                    variables[var_name] = int(default_val)
                except ValueError:
                    variables[var_name] = default_val
        else:
            variables[var_name] = None

    # Extract loop body
    loop_match = re.search(
        r'(?:WHILE\s+(.+?)\s+DO|LOOP)\s*(.*?)\s*END\s+(?:WHILE|LOOP)',
        sql, re.IGNORECASE | re.DOTALL,
    )

    if not loop_match:
        # No loop -- just execute non-DECLARE statements
        total_rows += _execute_linear(conn, sql, variables, split_fn)
        return total_rows

    condition = loop_match.group(1)  # None for LOOP (unconditional)
    loop_body = loop_match.group(2)

    # Extract pre-loop and post-loop statements
    pre_loop = sql[:loop_match.start()]
    post_loop = sql[loop_match.end():]

    # Execute pre-loop (non-DECLARE) statements
    for stmt in split_fn(pre_loop):
        stmt = stmt.strip()
        if not stmt or re.match(r'DECLARE\b', stmt, re.IGNORECASE):
            continue
        stmt = substitute_vars(stmt, variables)
        result = conn.execute(stmt)
        if result and result.description:
            try:
                total_rows += len(result.fetchall())
            except duckdb.InvalidInputException:
                pass

    # Execute loop — safety cap prevents infinite loops
    max_iterations = _SCRIPTING_LOOP_MAX_ITERATIONS
    for iteration_idx in range(max_iterations):
        # Check condition
        if condition:
            cond_sql = substitute_vars(condition, variables)
            try:
                result = conn.execute(f"SELECT {cond_sql}")
                row = result.fetchone()
                if row is None or not row[0]:
                    break
            except Exception as e:
                logger.warning("WHILE condition eval failed: %s", e)
                break

        # Execute loop body
        should_leave = False
        for stmt in split_fn(loop_body):
            stmt = stmt.strip()
            if not stmt:
                continue

            # Handle LEAVE
            if re.match(r'LEAVE\b', stmt, re.IGNORECASE):
                should_leave = True
                break

            # Skip END IF (artifact of statement splitting)
            if re.match(r'END\s+IF\b', stmt, re.IGNORECASE):
                continue

            # Handle IF ... THEN ... END IF
            if_match = re.match(
                r'IF\s+(.+?)\s+THEN\s+(.*?)(?:\s*END\s+IF)?$',
                stmt, re.IGNORECASE | re.DOTALL,
            )
            if if_match:
                cond_sql = substitute_vars(if_match.group(1), variables)
                try:
                    cond_result = conn.execute(f"SELECT {cond_sql}")
                    cond_row = cond_result.fetchone()
                    if cond_row is not None and cond_row[0]:
                        body = if_match.group(2).strip()
                        if re.match(r'LEAVE\b', body, re.IGNORECASE):
                            should_leave = True
                            break
                except Exception as e:
                    logger.warning("IF condition eval failed: %s", e)
                continue

            # Handle SET var = (expr)
            set_match = re.match(
                r'SET\s+(\w+)\s*=\s*(.+)', stmt, re.IGNORECASE
            )
            if set_match:
                var_name = set_match.group(1)
                expr = substitute_vars(set_match.group(2), variables)
                try:
                    result = conn.execute(f"SELECT {expr}")
                    set_row = result.fetchone()
                    variables[var_name] = set_row[0] if set_row is not None else None
                except Exception as e:
                    logger.error("SET %s eval failed in loop: %s", var_name, e)
                    variables[var_name] = None
                continue

            # Regular statement — errors propagate (no silent swallowing)
            stmt = substitute_vars(stmt, variables)
            result = conn.execute(stmt)
            if result and result.description:
                try:
                    total_rows += len(result.fetchall())
                except duckdb.InvalidInputException:
                    pass

        if should_leave:
            break
    else:
        # Loop completed without break — max iterations reached
        logger.warning(
            "DuckDB scripting loop reached max iterations (%d), results may be incomplete",
            _SCRIPTING_LOOP_MAX_ITERATIONS,
        )

    # Execute post-loop statements
    for stmt in split_fn(post_loop):
        stmt = stmt.strip()
        if not stmt:
            continue
        stmt = substitute_vars(stmt, variables)
        result = conn.execute(stmt)
        if result and result.description:
            try:
                total_rows += len(result.fetchall())
            except duckdb.InvalidInputException:
                pass

    return total_rows


def _execute_linear(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    variables: dict[str, object],
    split_fn: Callable[[str], list[str]],
) -> int:
    """Execute non-loop scripting (DECLARE + SET + regular statements)."""
    total_rows = 0
    for stmt in split_fn(sql):
        stmt = stmt.strip()
        if not stmt or re.match(r'DECLARE\b', stmt, re.IGNORECASE):
            continue
        # Handle SET var = expr
        set_match = re.match(
            r'SET\s+(\w+)\s*=\s*(.+)', stmt, re.IGNORECASE
        )
        if set_match:
            var_name = set_match.group(1)
            expr = substitute_vars(set_match.group(2), variables)
            try:
                r = conn.execute(f"SELECT {expr}")
                set_row = r.fetchone()
                variables[var_name] = set_row[0] if set_row is not None else None
            except Exception as e:
                logger.warning("SET %s eval failed: %s", var_name, e)
            continue
        stmt = substitute_vars(stmt, variables)
        result = conn.execute(stmt)
        if result and result.description:
            try:
                total_rows += len(result.fetchall())
            except duckdb.InvalidInputException:
                pass
    return total_rows


def substitute_vars(sql: str, variables: dict[str, object]) -> str:
    """Substitute variable references in SQL.

    Uses word-boundary matching to replace BQ scripting variables
    with their values. Only used for local DuckDB scripting emulation.
    """
    for var_name, value in variables.items():
        if value is None:
            replacement = "NULL"
        elif isinstance(value, str):
            # Escape single quotes to prevent SQL injection in local testing
            replacement = f"'{value.replace(chr(39), chr(39)+chr(39))}'"
        else:
            replacement = str(value)
        sql = re.sub(rf'\b{re.escape(var_name)}\b', replacement, sql)
    return sql


def split_statements(sql: str) -> list[str]:
    """Split SQL script into individual statements.

    Splits on semicolons that are not inside string literals.
    """
    statements = []
    current = []
    in_string = False
    escape_next = False
    for char in sql:
        if escape_next:
            current.append(char)
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            current.append(char)
            continue
        if char == "'":
            in_string = not in_string
        if char == ";" and not in_string:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)
    # Last statement (no trailing semicolon)
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements

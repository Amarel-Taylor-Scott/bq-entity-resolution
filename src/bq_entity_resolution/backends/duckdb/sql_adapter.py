"""SQL adaptation: rewrite BigQuery SQL to DuckDB-compatible SQL.

Contains the adapt_sql() function and its helpers for regex-based SQL
rewrites (backtick stripping, type mapping, function rewrites, etc.).
"""

from __future__ import annotations

import re


def adapt_sql(sql: str) -> str:
    """Adapt BigQuery SQL to DuckDB-compatible SQL."""
    # Replace fully-qualified backtick-quoted table names with simple names
    # e.g. `proj.dataset.table` -> table  (MUST run before backtick stripping)
    sql = re.sub(
        r'`([^`\s]+)\.([^`\s]+)\.([^`\s]+)`',
        lambda m: m.group(3),
        sql,
    )
    # Strip 2-part backtick-quoted names (UDF dataset refs):
    # e.g. `er_udfs.jaro_winkler`(...) -> jaro_winkler(...)
    sql = re.sub(
        r'`([^`\s]+)\.([^`\s]+)`',
        lambda m: m.group(2),
        sql,
    )
    # Remove remaining backtick quoting (simple identifiers)
    sql = sql.replace("`", "")
    # CURRENT_TIMESTAMP() -> current_timestamp (DuckDB form)
    sql = re.sub(r'CURRENT_TIMESTAMP\(\)', 'current_timestamp', sql)
    # ARRAY_AGG(col ORDER BY ... LIMIT 1)[OFFSET(0)] -> DuckDB FIRST()
    # BQ idiom for "first value when ordered by X"
    # DuckDB: FIRST(col ORDER BY expr)
    sql = re.sub(
        r'ARRAY_AGG\((\w+)\s+ORDER\s+BY\s+([^)]+?)\s+LIMIT\s+1\)\[OFFSET\(0\)\]',
        r'FIRST(\1 ORDER BY \2)',
        sql,
    )
    # APPROX_QUANTILES(col, n)[OFFSET(m)] -> PERCENTILE_CONT approximation
    sql = re.sub(
        r'APPROX_QUANTILES\(([^,]+),\s*2\)\[OFFSET\(1\)\]',
        r'MEDIAN(\1)',
        sql,
    )
    # UNIX_MICROS(ts) -> EPOCH_US(ts)
    sql = re.sub(r'UNIX_MICROS\(', 'EPOCH_US(', sql)
    # Strip BQ UDF dataset prefixes: {udf_dataset}.func(...) -> func(...)
    sql = re.sub(r'\{udf_dataset\}\.', '', sql)
    # Strip BQ raw string prefix: r'pattern' -> 'pattern'
    sql = re.sub(r"\br('(?:[^'\\]|\\.)*')", r'\1', sql)
    # Also strip resolved UDF dataset refs: `proj.dataset.func`(...) -> func(...)
    # (already handled by backtick stripping above for 3-part names)
    # SPLIT -> string_split (BQ SPLIT returns ARRAY<STRING>)
    sql = re.sub(r'\bSPLIT\(', 'string_split(', sql)
    # ARRAY_LENGTH -> len
    sql = re.sub(r'\bARRAY_LENGTH\(', 'len(', sql)
    # REGEXP_CONTAINS -> regexp_matches
    sql = re.sub(r'\bREGEXP_CONTAINS\(', 'regexp_matches(', sql)
    # Strip CLUSTER BY clause (DuckDB doesn't support it)
    sql = re.sub(r'\bCLUSTER\s+BY\s+[^\n]+', '', sql)
    # BQ type names -> DuckDB equivalents
    sql = re.sub(r'\bAS\s+FLOAT64\b', 'AS DOUBLE', sql)
    sql = re.sub(r'\bAS\s+INT64\b', 'AS BIGINT', sql)
    sql = re.sub(r'\bAS\s+STRING\b', 'AS VARCHAR', sql)
    sql = re.sub(r'\bAS\s+NUMERIC\b', 'AS DECIMAL(38, 9)', sql)
    sql = re.sub(r'\bAS\s+BIGNUMERIC\b', 'AS DECIMAL(76, 38)', sql)
    # [OFFSET(n)] -> [n+1] (BQ 0-indexed -> DuckDB 1-indexed)
    # Must run AFTER APPROX_QUANTILES and ARRAY_AGG[OFFSET] rewrites
    sql = re.sub(
        r'\[OFFSET\((\d+)\)\]',
        lambda m: f'[{int(m.group(1)) + 1}]',
        sql,
    )
    # [ORDINAL(n)] -> [n] (both 1-indexed, just strip the wrapper)
    sql = re.sub(r'\[ORDINAL\((\d+)\)\]', r'[\1]', sql)
    # TIMESTAMP_DIFF(ts1, ts2, UNIT) -> date_diff('unit', ts2, ts1)
    sql = re.sub(
        r'\bTIMESTAMP_DIFF\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*(\w+)\s*\)',
        lambda m: f"date_diff('{m.group(3).lower()}', {m.group(2).strip()}, {m.group(1).strip()})",
        sql,
    )
    # DATE_DIFF(d1, d2, UNIT) -> date_diff('unit', d2, d1) (arg reorder + lowercase unit)
    sql = re.sub(
        r'\bDATE_DIFF\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*(\w+)\s*\)',
        lambda m: f"date_diff('{m.group(3).lower()}', {m.group(2).strip()}, {m.group(1).strip()})",
        sql,
    )
    # * EXCEPT(col) -> * EXCLUDE(col) (DuckDB column exclusion syntax)
    sql = re.sub(r'\*\s+EXCEPT\s*\(', '* EXCLUDE(', sql)
    # SAFE_CAST(expr AS type) -> TRY_CAST(expr AS type)
    sql = re.sub(r'\bSAFE_CAST\(', 'TRY_CAST(', sql)
    # TO_JSON_STRING(STRUCT(cols)) -> CAST(STRUCT_PACK(cols) AS VARCHAR)
    # DuckDB doesn't have TO_JSON_STRING; CAST to VARCHAR gives a
    # readable string representation of the struct.
    sql = re.sub(
        r'\bTO_JSON_STRING\(STRUCT\(([^)]*)\)\)',
        r"CAST(struct_pack(\1) AS VARCHAR)",
        sql,
    )
    # ML.DISTANCE(a, b, 'COSINE') -> (1.0 - list_cosine_similarity(a, b))
    sql = rewrite_ml_distance(sql)
    # BQ UNNEST patterns -> DuckDB subquery wrappers
    sql = rewrite_unnest(sql)
    # QUALIFY is natively supported in DuckDB >=0.8 -- no rewrite needed
    return sql


def rewrite_unnest(sql: str) -> str:
    """Rewrite BQ UNNEST patterns to DuckDB-compatible syntax.

    BQ: FROM UNNEST(expr) AS alias [WITH OFFSET AS pos]
    DuckDB: FROM (SELECT UNNEST(expr) AS alias) _unnest_sub

    BQ: IN UNNEST(expr)
    DuckDB: = ANY(expr)
    """
    def find_matching_paren(s: str, start: int) -> int:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    # Iterative: process one UNNEST at a time, re-scanning after each change
    max_iter = 20
    for _ in range(max_iter):
        prev_sql = sql
        m = re.search(r'\bUNNEST\(', sql, re.IGNORECASE)
        if not m:
            break

        unnest_start = m.start()
        paren_start = m.end() - 1
        paren_end = find_matching_paren(sql, paren_start)
        if paren_end == -1:
            break

        inner_expr = sql[paren_start + 1:paren_end]
        before = sql[:unnest_start]
        after = sql[paren_end + 1:]

        # Skip if preceded by SELECT (already rewritten)
        if re.search(r'\bSELECT\s+$', before, re.IGNORECASE):
            # Mark as processed by moving past it
            # Replace UNNEST with a temporary marker to skip it
            sql = before + "_UNNEST_DONE_(" + inner_expr + ")" + after
            continue

        # IN UNNEST(expr) -> = ANY(expr)
        if re.search(r'\bIN\s*$', before, re.IGNORECASE):
            sql = (
                re.sub(r'\bIN\s*$', '= ANY(', before, flags=re.IGNORECASE)
                + inner_expr + ")"
                + after
            )
            continue

        # FROM UNNEST(expr) [AS] alias [WITH OFFSET [AS] pos]
        alias_match = re.match(
            r'\s+(?:AS\s+)?(\w+)(\s+WITH\s+OFFSET\s+(?:AS\s+)?(\w+))?',
            after, re.IGNORECASE,
        )
        if alias_match:
            alias = alias_match.group(1)
            has_offset = alias_match.group(2) is not None
            remaining = after[alias_match.end():]

            from_match = re.search(r'\bFROM\s*$', before, re.IGNORECASE)
            if from_match:
                sql = (
                    before[:from_match.start()]
                    + f"FROM (SELECT _UNNEST_DONE_({inner_expr}) AS {alias}) _usub"
                    + remaining
                )
            else:
                sql = (
                    before
                    + f"(SELECT _UNNEST_DONE_({inner_expr}) AS {alias}) _usub"
                    + remaining
                )

            if has_offset:
                offset_alias = alias_match.group(3) or "pos"
                sql = re.sub(
                    rf'\s+ORDER\s+BY\s+{offset_alias}\b', '', sql
                )
        else:
            # No alias -- skip to avoid infinite loop
            sql = before + "_UNNEST_DONE_(" + inner_expr + ")" + after

        # Safety: break if no progress was made
        if sql == prev_sql:
            break

    # Restore UNNEST from markers
    sql = sql.replace("_UNNEST_DONE_(", "UNNEST(")

    return sql


def rewrite_ml_distance(sql: str) -> str:
    """Rewrite ML.DISTANCE(a, b, 'COSINE') to DuckDB equivalent.

    Handles nested brackets/parens in arguments (e.g. array literals).
    """
    result = []
    i = 0
    marker = "ML.DISTANCE("
    while i < len(sql):
        pos = sql.upper().find(marker.upper(), i)
        if pos == -1:
            result.append(sql[i:])
            break
        result.append(sql[i:pos])
        # Parse args with bracket/paren awareness
        start = pos + len(marker)
        args = []
        depth = 0
        current: list[str] = []
        j = start
        while j < len(sql):
            ch = sql[j]
            if ch in ("(", "["):
                depth += 1
                current.append(ch)
            elif ch in (")", "]"):
                if depth == 0:
                    # End of ML.DISTANCE(...)
                    arg = "".join(current).strip()
                    if arg:
                        args.append(arg)
                    j += 1
                    break
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
            j += 1

        if len(args) >= 3 and "COSINE" in args[2].upper():
            result.append(f"(1.0 - list_cosine_similarity({args[0]}, {args[1]}))")
        else:
            # Not a COSINE distance -- keep original
            result.append(sql[pos:j])
        i = j
    return "".join(result)

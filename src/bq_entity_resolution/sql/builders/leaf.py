"""SQL builder for leaf-based resolution (see ``docs/leaf-resolution-design.md``).

A *leaf* is a self-contained candidate-pair generator over an ordered pair of
partitions of the entity space (``left × right``). This builder emits the leaf
candidate-pair SQL the design doc specifies and the standalone prototype
(``examples/leaf_prototype.py``) proves:

    WITH L AS (SELECT … FROM <left_table>  WHERE <left.predicate>),
         R AS (SELECT … FROM <right_table> WHERE <right.predicate>)
    SELECT l.entity_uid AS left_uid, r.entity_uid AS right_uid,
           <score>, '<leaf>' AS match_leaf, 'compare' AS match_method
    FROM L JOIN R
      ON (<blocking join>)
      AND <self-join / cross-partition guard>
    WHERE <score passes threshold>
    UNION ALL                                   -- exact-key short-circuit
    SELECT …, 1.0, '<leaf>', 'short_circuit' …  -- auto-accept high-recall keys

The shape deliberately matches the proven prototype:

- **Partition selection** binds ``batch`` → staging/featured, ``canonical`` →
  the canonical index, ``table`` → an explicit (validated) table ref. The UID
  column stays ``entity_uid`` (INT64) so all joins remain INT64-native, per the
  blocking builder's perf notes.
- **Blocking** is an OR-of-paths join, each path an AND of equality keys — the
  same multi-path semantics as ``sql/builders/blocking.py``.
- **Self-join guard**: a symmetric self-join (``left == right``) emits each
  unordered pair once (``l.entity_uid < r.entity_uid``); a cross-partition leaf
  uses ``l.entity_uid != r.entity_uid``.
- **Exact-key short-circuit** compiles to a ``UNION ALL`` branch that emits
  score=1.0 pairs on exact canonical-key equality (cheap, high-recall).
- **max_pairs** caps the leaf's output with a deterministic ``QUALIFY`` /
  ``ORDER BY … LIMIT`` so a single leaf can never explode the pair graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.columns import (
    ENTITY_UID,
    LEFT_ENTITY_UID,
    MATCH_LEAF,
    MATCH_METHOD,
    MATCH_TOTAL_SCORE,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import (
    sql_escape,
    validate_identifier,
    validate_table_ref,
)

__all__ = [
    "LeafBlockingPath",
    "LeafScoreTerm",
    "LeafSQLParams",
    "build_leaf_sql",
]


@dataclass(frozen=True)
class LeafBlockingPath:
    """A single blocking path for a leaf: a candidate pair is produced when it
    matches this path. Each path is an AND of equality conditions on the listed
    keys (the same multi-path semantics as the blocking builder).
    """

    keys: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("LeafBlockingPath requires at least one key")
        for key in self.keys:
            validate_identifier(key, "leaf blocking key")


@dataclass(frozen=True)
class LeafScoreTerm:
    """A single scored comparison term.

    ``sql_expr`` is a boolean SQL expression over ``l.``/``r.`` aliases (already
    validated/generated upstream, e.g. by the comparison registry). When it is
    true the term contributes ``weight`` to the pair's total score.
    """

    name: str
    sql_expr: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        validate_identifier(self.name, "leaf score term name")
        if not self.sql_expr.strip():
            raise ValueError(f"leaf score term {self.name!r} has empty sql_expr")


@dataclass(frozen=True)
class LeafSQLParams:
    """Parameters for one leaf's candidate-pair SQL.

    ``left_table``/``right_table`` are the physical tables the executor bound the
    leaf's partitions to. ``symmetric`` is honoured only for self-joins (it has
    no effect when ``left_table``/predicate differ from the right side, i.e. a
    cross-partition leaf, which always uses the ``!=`` guard).
    """

    target_table: str
    leaf_name: str
    left_table: str
    right_table: str
    blocking_paths: list[LeafBlockingPath]
    score_terms: list[LeafScoreTerm]
    threshold: float = 0.9
    left_predicate: str | None = None
    right_predicate: str | None = None
    is_self_join: bool = False
    symmetric: bool = True
    exact_key_short_circuit: list[str] = field(default_factory=list)
    max_pairs: int | None = None

    def __post_init__(self) -> None:
        validate_table_ref(self.target_table)
        validate_table_ref(self.left_table)
        validate_table_ref(self.right_table)
        validate_identifier(self.leaf_name, "leaf name")
        if not self.blocking_paths:
            raise ValueError(
                f"leaf {self.leaf_name!r} requires at least one blocking path"
            )
        if not self.score_terms:
            raise ValueError(
                f"leaf {self.leaf_name!r} requires at least one score term"
            )
        for key in self.exact_key_short_circuit:
            validate_identifier(key, "leaf short-circuit key")
        if self.max_pairs is not None and self.max_pairs < 1:
            raise ValueError(
                f"leaf {self.leaf_name!r}: max_pairs must be >= 1, "
                f"got {self.max_pairs}"
            )


def _guard(params: LeafSQLParams) -> str:
    """Self-join dedup guard vs. cross-partition guard.

    A symmetric self-join emits each unordered pair once; otherwise every
    ordered pair (excluding identity) is emitted.
    """
    if params.is_self_join and params.symmetric:
        return f"l.{ENTITY_UID} < r.{ENTITY_UID}"
    return f"l.{ENTITY_UID} != r.{ENTITY_UID}"


def _blocking_clause(paths: list[LeafBlockingPath]) -> str:
    """OR over paths; each path is an AND of equality conditions on its keys."""
    rendered_paths: list[str] = []
    for path in paths:
        conds = []
        for key in path.keys:
            conds.append(f"l.{key} = r.{key}")
            conds.append(f"l.{key} IS NOT NULL")
        rendered_paths.append("(" + " AND ".join(conds) + ")")
    return " OR ".join(rendered_paths)


def _score_expr(terms: list[LeafScoreTerm]) -> str:
    """GREATEST over each weighted boolean term (mirrors the prototype's
    ``greatest(...)`` shape: a pair's score is its strongest signal).
    """
    parts = [
        f"CASE WHEN {t.sql_expr} THEN {t.weight} ELSE 0.0 END" for t in terms
    ]
    if len(parts) == 1:
        return parts[0]
    return "GREATEST(\n    " + ",\n    ".join(parts) + "\n  )"


def _partition_cte(name: str, table: str, predicate: str | None) -> str:
    where = f" WHERE {predicate}" if predicate else ""
    return f"{name} AS (SELECT * FROM `{table}`{where})"


def build_leaf_sql(params: LeafSQLParams) -> SQLExpression:
    """Build the candidate-pair SQL for a single leaf.

    Emits ``CREATE OR REPLACE TABLE <target> AS`` with columns
    ``(left_entity_uid, right_entity_uid, match_total_score, match_leaf,
    match_method)``. The scored branch is filtered by ``threshold``; the
    optional short-circuit branch ``UNION ALL``s exact-key auto-accepts; a
    ``max_pairs`` cap bounds the leaf's total output.
    """
    leaf_lit = sql_escape(params.leaf_name)
    guard = _guard(params)
    blocking = _blocking_clause(params.blocking_paths)
    score = _score_expr(params.score_terms)

    parts: list[str] = []
    parts.append(f"CREATE OR REPLACE TABLE `{params.target_table}` AS")
    parts.append("")
    parts.append("WITH")
    parts.append(
        _partition_cte("leaf_l", params.left_table, params.left_predicate) + ","
    )
    parts.append(
        _partition_cte("leaf_r", params.right_table, params.right_predicate)
    )
    parts.append(", leaf_pairs AS (")

    # Scored comparison branch.
    parts.append("  SELECT")
    parts.append(f"    l.{ENTITY_UID} AS {LEFT_ENTITY_UID},")
    parts.append(f"    r.{ENTITY_UID} AS {RIGHT_ENTITY_UID},")
    parts.append(f"    {score} AS {MATCH_TOTAL_SCORE},")
    parts.append(f"    '{leaf_lit}' AS {MATCH_LEAF},")
    parts.append(f"    'compare' AS {MATCH_METHOD}")
    parts.append("  FROM leaf_l l")
    parts.append("  JOIN leaf_r r")
    parts.append(f"    ON ({blocking})")
    parts.append(f"    AND {guard}")
    parts.append(f"  WHERE ({score}) >= {params.threshold}")

    # Exact-key short-circuit branch (cheap, high-recall auto-accepts).
    if params.exact_key_short_circuit:
        sc = " OR ".join(
            f"(l.{k} = r.{k} AND l.{k} IS NOT NULL)"
            for k in params.exact_key_short_circuit
        )
        parts.append("  UNION ALL")
        parts.append("  SELECT")
        parts.append(f"    l.{ENTITY_UID} AS {LEFT_ENTITY_UID},")
        parts.append(f"    r.{ENTITY_UID} AS {RIGHT_ENTITY_UID},")
        parts.append(f"    1.0 AS {MATCH_TOTAL_SCORE},")
        parts.append(f"    '{leaf_lit}' AS {MATCH_LEAF},")
        parts.append(f"    'short_circuit' AS {MATCH_METHOD}")
        parts.append("  FROM leaf_l l")
        parts.append("  JOIN leaf_r r")
        parts.append(f"    ON ({sc})")
        parts.append(f"    AND {guard}")

    parts.append(")")
    parts.append("")

    # Deduplicate the union (a pair may appear via both branches) keeping the
    # highest score, then apply the optional max_pairs safety cap.
    parts.append("SELECT")
    parts.append(f"  {LEFT_ENTITY_UID},")
    parts.append(f"  {RIGHT_ENTITY_UID},")
    parts.append(f"  MAX({MATCH_TOTAL_SCORE}) AS {MATCH_TOTAL_SCORE},")
    parts.append(f"  ANY_VALUE({MATCH_LEAF}) AS {MATCH_LEAF},")
    parts.append(
        f"  MAX({MATCH_METHOD}) AS {MATCH_METHOD}"  # 'short_circuit' > 'compare'
    )
    parts.append("FROM leaf_pairs")
    parts.append(f"GROUP BY {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}")
    parts.append(f"ORDER BY {MATCH_TOTAL_SCORE} DESC, {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}")
    if params.max_pairs is not None:
        parts.append(f"LIMIT {params.max_pairs}")

    return SQLExpression.from_raw("\n".join(parts))

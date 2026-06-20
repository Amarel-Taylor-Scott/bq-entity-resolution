"""SQL builder for EM estimation (replaces em_estimation.sql.j2).

Generates BigQuery scripting SQL for Expectation-Maximization
algorithm to estimate m/u probabilities.

The EM loop runs as a BQ script (DECLARE/LOOP/SET).
Individual E-step and M-step SQL can also be generated separately
for local (DuckDB) execution where the iteration loop runs in Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bq_entity_resolution.columns import (
    ENTITY_UID,
    LEFT_ENTITY_UID,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref


@dataclass(frozen=True)
class EMLevel:
    """A comparison level for EM estimation."""
    label: str
    sql_expr: str
    has_expr: bool = True

    def __post_init__(self) -> None:
        validate_identifier(self.label, "level_label")


@dataclass(frozen=True)
class EMComparison:
    """A comparison definition for EM estimation."""
    name: str
    left: str
    right: str
    levels: list[EMLevel] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_identifier(self.name, "comparison_name")


@dataclass(frozen=True)
class EMParams:
    """Parameters for EM estimation SQL generation."""
    candidates_table: str
    source_table: str
    comparisons: list[EMComparison]
    max_iterations: int = 25
    convergence_threshold: float = 0.001
    sample_size: int = 10000
    initial_match_proportion: float = 0.1

    def __post_init__(self) -> None:
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.source_table)


def _all_expr_levels(comparisons: list[EMComparison]) -> list[tuple[str, str]]:
    """Get all (comp_name, level_label) pairs that have SQL expressions."""
    result: list[tuple[str, str]] = []
    for comp in comparisons:
        for level in comp.levels:
            if level.has_expr:
                result.append((comp.name, level.label))
    return result


def build_em_estimation_sql(params: EMParams) -> SQLExpression:
    """Build the full EM estimation SQL as a BigQuery script.

    Returns a single SQL script containing DECLARE, LOOP, and
    final SELECT for estimated parameters.
    """
    all_levels = _all_expr_levels(params.comparisons)
    lines: list[str] = []

    # Variable declarations
    lines.append("DECLARE iteration INT64 DEFAULT 0;")
    lines.append("DECLARE max_delta FLOAT64 DEFAULT 1.0;")
    lines.append(
        f"DECLARE match_prior FLOAT64 DEFAULT {params.initial_match_proportion};"
    )
    lines.append("DECLARE log_likelihood FLOAT64 DEFAULT 0.0;")
    lines.append("DECLARE prev_log_likelihood FLOAT64 DEFAULT -1e18;")
    lines.append("")

    # Step 1: Create sampled pairs with comparison outcomes
    lines.append("CREATE TEMP TABLE _em_pairs AS")
    lines.append("SELECT")
    lines.append(f"  c.{LEFT_ENTITY_UID},")
    lines.append(f"  c.{RIGHT_ENTITY_UID},")

    for comp in params.comparisons:
        for level in comp.levels:
            if level.has_expr:
                lines.append(
                    f"  CASE WHEN {level.sql_expr} THEN 1.0 ELSE 0.0 END "
                    f"AS {comp.name}__{level.label},"
                )

    lines.append("  0.5 AS match_weight")
    lines.append("FROM (")
    lines.append(f"  SELECT {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}")
    lines.append(f"  FROM `{params.candidates_table}`")
    lines.append(
        f"  ORDER BY FARM_FINGERPRINT(CONCAT({LEFT_ENTITY_UID}, '||', {RIGHT_ENTITY_UID}))"
    )
    lines.append(f"  LIMIT {params.sample_size}")
    lines.append(") c")
    lines.append(
        f"INNER JOIN `{params.source_table}` l ON c.{LEFT_ENTITY_UID} = l.{ENTITY_UID}"
    )
    lines.append(
        f"INNER JOIN `{params.source_table}` r ON c.{RIGHT_ENTITY_UID} = r.{ENTITY_UID};"
    )
    lines.append("")

    # Step 2: Initialize parameter table
    lines.append("CREATE TEMP TABLE _em_params (")
    lines.append("  comparison_name STRING,")
    lines.append("  level_label STRING,")
    lines.append("  m_prob FLOAT64,")
    lines.append("  u_prob FLOAT64")
    lines.append(");")
    lines.append("")

    lines.append(
        "INSERT INTO _em_params (comparison_name, level_label, m_prob, u_prob) VALUES"
    )

    init_values: list[str] = []
    for comp_name, level_label in all_levels:
        init_values.append(f"('{comp_name}', '{level_label}', 0.9, 0.1)")
    lines.append(",\n".join(init_values) + ";")
    lines.append("")

    # Step 3: EM iteration loop
    lines.append("LOOP")
    lines.append("  SET iteration = iteration + 1;")
    lines.append("")

    # E-step: compute match probability for each pair using log-space
    lines.append("  CREATE OR REPLACE TEMP TABLE _em_scored AS")
    lines.append("  SELECT")
    lines.append(f"    p.{LEFT_ENTITY_UID},")
    lines.append(f"    p.{RIGHT_ENTITY_UID},")

    for comp_name, level_label in all_levels:
        col = f"{comp_name}__{level_label}"
        lines.append(f"    p.{col},")

    # log_match
    lines.append("    (")
    lines.append("      LN(match_prior)")
    for comp_name, level_label in all_levels:
        col = f"{comp_name}__{level_label}"
        alias = f"mp_{col}"
        lines.append("      + CASE")
        lines.append(f"          WHEN p.{col} = 1.0")
        lines.append(
            f"          THEN LN(GREATEST({alias}.m_prob, 0.001))"
        )
        lines.append(
            f"          ELSE LN(GREATEST(1.0 - {alias}.m_prob, 0.001))"
        )
        lines.append("        END")

    lines.append("    ) AS log_match,")

    # log_nonmatch
    lines.append("    (")
    lines.append("      LN(1.0 - match_prior)")
    for comp_name, level_label in all_levels:
        col = f"{comp_name}__{level_label}"
        alias = f"mp_{col}"
        lines.append("      + CASE")
        lines.append(f"          WHEN p.{col} = 1.0")
        lines.append(
            f"          THEN LN(GREATEST({alias}.u_prob, 0.001))"
        )
        lines.append(
            f"          ELSE LN(GREATEST(1.0 - {alias}.u_prob, 0.001))"
        )
        lines.append("        END")

    lines.append("    ) AS log_nonmatch")
    lines.append("  FROM _em_pairs p")

    # CROSS JOINs for parameter lookup
    for comp_name, level_label in all_levels:
        col = f"{comp_name}__{level_label}"
        alias = f"mp_{col}"
        lines.append("  CROSS JOIN (")
        lines.append("    SELECT m_prob, u_prob FROM _em_params")
        lines.append(
            f"    WHERE comparison_name = '{comp_name}' "
            f"AND level_label = '{level_label}'"
        )
        lines.append(f"  ) {alias}")

    lines.append(";")
    lines.append("")

    # Compute posterior match probability (CREATE OR REPLACE avoids DROP+RENAME)
    lines.append("  CREATE OR REPLACE TEMP TABLE _em_pairs AS")
    lines.append("  SELECT")
    lines.append(f"    {LEFT_ENTITY_UID},")
    lines.append(f"    {RIGHT_ENTITY_UID},")
    for comp_name, level_label in all_levels:
        lines.append(f"    {comp_name}__{level_label},")
    lines.append("    SAFE_DIVIDE(")
    lines.append("      EXP(log_match),")
    lines.append("      EXP(log_match) + EXP(log_nonmatch)")
    lines.append("    ) AS match_weight")
    lines.append("  FROM _em_scored;")
    lines.append("")

    # Log-likelihood
    lines.append("  SET prev_log_likelihood = log_likelihood;")
    lines.append("  SET log_likelihood = (")
    lines.append("    SELECT COALESCE(SUM(LOG(")
    lines.append("      EXP(log_match) + EXP(log_nonmatch)")
    lines.append("    )), 0.0)")
    lines.append("    FROM _em_scored")
    lines.append("  );")
    lines.append("")

    # M-step: update m/u from weighted counts
    lines.append("  CREATE OR REPLACE TEMP TABLE _em_params_new AS")

    m_step_parts: list[str] = []
    for comp_name, level_label in all_levels:
        col = f"{comp_name}__{level_label}"
        m_step_parts.append("  SELECT")
        m_step_parts.append(f"    '{comp_name}' AS comparison_name,")
        m_step_parts.append(f"    '{level_label}' AS level_label,")
        m_step_parts.append("    GREATEST(0.001, LEAST(0.999,")
        m_step_parts.append("      COALESCE(SAFE_DIVIDE(")
        m_step_parts.append(f"        SUM(match_weight * {col}),")
        m_step_parts.append("        NULLIF(SUM(match_weight), 0)")
        m_step_parts.append("      ), 0.5)")
        m_step_parts.append("    )) AS m_prob,")
        m_step_parts.append("    GREATEST(0.001, LEAST(0.999,")
        m_step_parts.append("      COALESCE(SAFE_DIVIDE(")
        m_step_parts.append(f"        SUM((1.0 - match_weight) * {col}),")
        m_step_parts.append("        NULLIF(SUM(1.0 - match_weight), 0)")
        m_step_parts.append("      ), 0.5)")
        m_step_parts.append("    )) AS u_prob")
        m_step_parts.append("  FROM _em_pairs")

    lines.append("\n  UNION ALL\n".join(
        "\n".join(chunk)
        for chunk in [
            m_step_parts[i:i + 14]
            for i in range(0, len(m_step_parts), 14)
        ]
    ))

    lines.append(";")
    lines.append("")

    # Check convergence
    lines.append("  SET max_delta = (")
    lines.append(
        "    SELECT COALESCE(MAX(ABS(n.m_prob - o.m_prob) "
        "+ ABS(n.u_prob - o.u_prob)), 0)"
    )
    lines.append("    FROM _em_params_new n")
    lines.append("    JOIN _em_params o USING (comparison_name, level_label)")
    lines.append("  );")
    lines.append("")

    # Update params (IF EXISTS prevents errors on retry/resume)
    lines.append("  DROP TABLE IF EXISTS _em_params;")
    lines.append("  ALTER TABLE _em_params_new RENAME TO _em_params;")
    lines.append("")

    # Update match prior
    lines.append("  SET match_prior = (")
    lines.append(
        "    SELECT GREATEST(0.001, LEAST(0.999, AVG(match_weight))) "
        "FROM _em_pairs"
    )
    lines.append("  );")
    lines.append("")

    # Convergence check
    lines.append(f"  IF iteration >= {params.max_iterations}")
    lines.append(
        f"     OR max_delta < {params.convergence_threshold}"
    )
    lines.append(
        f"     OR ABS(log_likelihood - prev_log_likelihood) "
        f"< {params.convergence_threshold} THEN"
    )
    lines.append("    LEAVE;")
    lines.append("  END IF;")
    lines.append("END LOOP;")
    lines.append("")

    # Return final parameters
    lines.append("SELECT")
    lines.append("  comparison_name,")
    lines.append("  level_label,")
    lines.append("  m_prob AS m_probability,")
    lines.append("  u_prob AS u_probability,")
    lines.append("  match_prior AS match_rate,")
    lines.append("  iteration AS em_iterations,")
    lines.append("  log_likelihood AS final_log_likelihood")
    lines.append("FROM _em_params;")

    return SQLExpression.from_raw("\n".join(lines))


@dataclass(frozen=True)
class LabelEstimationParams:
    """Parameters for estimating m/u from labeled pairs."""
    labeled_pairs_table: str
    source_table: str
    # [{name, left, right, levels: [{label, sql_expr, has_expr}]}]
    comparisons: list[dict[str, Any]]

    def __post_init__(self) -> None:
        validate_table_ref(self.labeled_pairs_table)
        validate_table_ref(self.source_table)


def build_estimate_from_labels_sql(
    params: LabelEstimationParams,
) -> SQLExpression:
    """Build SQL to estimate m/u probabilities from labeled pairs.

    For each comparison and each level, computes:
    - m = P(level outcome | is_match = TRUE)
    - u = P(level outcome | is_match = FALSE)
    """
    parts: list[str] = []

    for comp in params.comparisons:
        for level in comp["levels"]:
            if not level.get("has_expr"):
                continue
            sql_expr = level["sql_expr"]
            part_lines = [
                "SELECT",
                f"  '{comp['name']}' AS comparison_name,",
                f"  '{level['label']}' AS level_label,",
                "  SAFE_DIVIDE(",
                f"    COUNTIF(lp.is_match AND ({sql_expr})),",
                "    NULLIF(COUNTIF(lp.is_match), 0)",
                "  ) AS m_probability,",
                "  SAFE_DIVIDE(",
                f"    COUNTIF(NOT lp.is_match AND ({sql_expr})),",
                "    NULLIF(COUNTIF(NOT lp.is_match), 0)",
                "  ) AS u_probability,",
                "  SAFE_DIVIDE(COUNTIF(lp.is_match), COUNT(*)) AS match_rate",
                f"FROM `{params.labeled_pairs_table}` lp",
                f"INNER JOIN `{params.source_table}` l "
                f"ON lp.{LEFT_ENTITY_UID} = l.{ENTITY_UID}",
                f"INNER JOIN `{params.source_table}` r "
                f"ON lp.{RIGHT_ENTITY_UID} = r.{ENTITY_UID}",
            ]
            parts.append("\n".join(part_lines))

    if not parts:
        return SQLExpression.from_raw(
            "SELECT CAST(NULL AS STRING) AS comparison_name WHERE FALSE"
        )

    return SQLExpression.from_raw("\nUNION ALL\n".join(parts))


def build_em_estep_sql() -> SQLExpression:
    """Build just the E-step SQL for local (DuckDB) execution.

    When running locally, the EM iteration loop runs in Python,
    and this generates the E-step SQL for a single iteration.
    """
    # This is used for DuckDB-based testing where the LOOP
    # must be driven by Python code.
    lines: list[str] = []
    lines.append("-- E-step: compute posterior match probability")
    lines.append("-- Parameters: _em_pairs table, _em_params table, match_prior")
    lines.append("-- This is a template for local execution;")
    lines.append("-- the actual SQL is generated dynamically per comparison set.")
    return SQLExpression.from_raw("\n".join(lines))


def build_em_mstep_sql(all_levels: list[tuple[str, str]]) -> SQLExpression:
    """Build just the M-step SQL for local (DuckDB) execution.

    Updates m/u probabilities from weighted counts.
    """
    lines: list[str] = []

    parts: list[str] = []
    for comp_name, level_label in all_levels:
        col = f"{comp_name}__{level_label}"
        part = (
            f"SELECT\n"
            f"  '{comp_name}' AS comparison_name,\n"
            f"  '{level_label}' AS level_label,\n"
            f"  GREATEST(0.001, LEAST(0.999,\n"
            f"    COALESCE(SAFE_DIVIDE(\n"
            f"      SUM(match_weight * {col}),\n"
            f"      NULLIF(SUM(match_weight), 0)\n"
            f"    ), 0.5)\n"
            f"  )) AS m_prob,\n"
            f"  GREATEST(0.001, LEAST(0.999,\n"
            f"    COALESCE(SAFE_DIVIDE(\n"
            f"      SUM((1.0 - match_weight) * {col}),\n"
            f"      NULLIF(SUM(1.0 - match_weight), 0)\n"
            f"    ), 0.5)\n"
            f"  )) AS u_prob\n"
            f"FROM _em_pairs"
        )
        parts.append(part)

    lines.append("\nUNION ALL\n".join(parts))

    return SQLExpression.from_raw("\n".join(lines))

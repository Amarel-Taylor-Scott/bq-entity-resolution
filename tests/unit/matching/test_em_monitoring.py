"""Tests for EM log-likelihood monitoring in the estimation builder."""

from bq_entity_resolution.sql.builders.em import (
    EMComparison,
    EMLevel,
    EMParams,
    build_em_estimation_sql,
)


def _render_em_sql() -> str:
    """Render the EM estimation SQL with minimal parameters."""
    params = EMParams(
        candidates_table="proj.silver.candidates",
        source_table="proj.silver.featured",
        comparisons=[
            EMComparison(
                name="name",
                left="first_name",
                right="first_name",
                levels=[
                    EMLevel(label="exact", sql_expr="l.first_name = r.first_name", has_expr=True),
                    EMLevel(label="else", sql_expr="", has_expr=False),
                ],
            )
        ],
        max_iterations=10,
        convergence_threshold=0.001,
        sample_size=10000,
        initial_match_proportion=0.1,
    )
    return build_em_estimation_sql(params).render()


def test_em_declares_log_likelihood():
    """EM SQL declares log_likelihood variable."""
    sql = _render_em_sql()
    assert "DECLARE log_likelihood FLOAT64" in sql


def test_em_tracks_prev_log_likelihood():
    """EM SQL declares prev_log_likelihood for tracking changes."""
    sql = _render_em_sql()
    assert "DECLARE prev_log_likelihood FLOAT64" in sql


def test_em_computes_log_likelihood():
    """EM SQL computes log-likelihood using LOG()."""
    sql = _render_em_sql()
    assert "SET log_likelihood" in sql or "log_likelihood" in sql
    assert "LOG(" in sql


def test_em_outputs_log_likelihood():
    """Final SELECT includes log_likelihood for callers to inspect."""
    sql = _render_em_sql()
    assert "final_log_likelihood" in sql


def test_em_convergence_uses_log_likelihood():
    """Convergence check references log_likelihood."""
    sql = _render_em_sql()
    assert "ABS(log_likelihood - prev_log_likelihood)" in sql


def test_em_mstep_zero_count_protection():
    """M-step COALESCE prevents NULL when SAFE_DIVIDE gets zero denominator."""
    sql = _render_em_sql()
    # COALESCE wraps SAFE_DIVIDE to fall back to 0.5 (uninformative prior)
    assert "COALESCE(SAFE_DIVIDE(" in sql
    assert ", 0.5)" in sql

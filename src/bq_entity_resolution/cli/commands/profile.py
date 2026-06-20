"""CLI command: profile — Profile source columns and suggest comparison weights."""

from __future__ import annotations

import sys

import click


@click.command()
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option("--defaults", default=None, type=click.Path(exists=True))
@click.option(
    "--source",
    default=None,
    help="Source name to profile (defaults to first source)",
)
@click.option(
    "--columns",
    default=None,
    help="Comma-separated column names to profile (defaults to all)",
)
def profile(
    config: str,
    defaults: str | None,
    source: str | None,
    columns: str | None,
) -> None:
    """Profile source columns and suggest comparison weights.

    Computes cardinality, null rates, and value distributions for
    source columns, then suggests comparison weights based on
    information content (log2(m/u)). No labeled data required.
    """
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.profiling.column_profiler import ColumnProfiler

    try:
        cfg = load_config(config, defaults)

        # Resolve source
        src = cfg.sources[0]
        if source:
            found = next((s for s in cfg.sources if s.name == source), None)
            if not found:
                available = [s.name for s in cfg.sources]
                click.echo(f"Source '{source}' not found. Available: {available}", err=True)
                sys.exit(1)
            src = found

        # Resolve columns
        if columns:
            col_names = [c.strip() for c in columns.split(",")]
        else:
            col_names = [c.name for c in src.columns]

        profiler = ColumnProfiler()
        sql = profiler.generate_profile_sql(src.table, col_names)

        click.echo(f"Source: {src.name} ({src.table})")
        click.echo(f"Columns: {', '.join(col_names)}")
        click.echo()
        click.echo("-- PROFILING SQL --")
        click.echo("-- Run this in BigQuery, then use the results to set weights --")
        click.echo(sql)
        click.echo()

        # Show suggestions from role-based defaults
        suggestions = []
        for comp_col in col_names:
            from bq_entity_resolution.config.roles import ROLE_COMPARISONS, detect_role

            role = detect_role(comp_col)
            if role and role in ROLE_COMPARISONS:
                for spec in ROLE_COMPARISONS[role]:
                    suggestions.append(
                        f"  {comp_col}: method={spec.method}, "
                        f"default_weight={spec.weight}"
                    )

        if suggestions:
            click.echo("Role-based default weights:")
            for s in suggestions:
                click.echo(s)
            click.echo()
            click.echo(
                "To use data-driven weights instead, run the SQL above "
                "in BigQuery and set weight_mode: profile in your config."
            )

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

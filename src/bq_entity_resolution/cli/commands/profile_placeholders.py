"""CLI command: profile-placeholders -- Scan source data for placeholder values."""

from __future__ import annotations

import logging
import sys

import click

logger = logging.getLogger(__name__)


@click.command("profile-placeholders")
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option(
    "--source",
    default=None,
    help="Source name to profile (default: first source)",
)
@click.option(
    "--top-n",
    default=20,
    type=int,
    help="Top-N suspected values per column (default: 20)",
)
def profile_placeholders(
    config: str,
    source: str | None,
    top_n: int,
) -> None:
    """Scan source data and recommend custom placeholder patterns.

    Detects known placeholder values (using built-in patterns) and
    suspected placeholders (high-frequency values that may be non-informative).

    Example:
        bq-er profile-placeholders --config config.yml
        bq-er profile-placeholders --config config.yml --source customers --top-n 30
    """
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.profiling.placeholder_profiler import PlaceholderProfiler

    try:
        cfg = load_config(config)
        src = None
        if source:
            for s in cfg.sources:
                if s.name == source:
                    src = s
                    break
            if src is None:
                click.echo(f"ERROR: Source '{source}' not found in config", err=True)
                sys.exit(1)
        else:
            src = cfg.sources[0]

        # Build column-role pairs
        columns_with_roles = [
            (col.name, getattr(col, "role", ""))
            for col in src.columns
        ]
        all_columns = [col.name for col in src.columns]

        click.echo(f"Source: {src.table}")
        click.echo(f"Columns: {len(all_columns)}")
        click.echo("")

        # The profiler generates SQL only — actual execution requires a backend.
        # For offline use (no BQ credentials), show the generated SQL.
        profiler = PlaceholderProfiler(backend=None)

        known_sql = profiler.build_known_pattern_sql(
            src.table, columns_with_roles
        )
        if known_sql:
            click.echo("Known pattern scan SQL:")
            click.echo(known_sql.render())
            click.echo("")

        suspected_sql = profiler.build_suspected_pattern_sql(
            src.table, all_columns, top_n=top_n
        )
        click.echo("Suspected pattern scan SQL:")
        click.echo(suspected_sql.render())

    except Exception as e:
        logger.exception("Placeholder profiling failed: %s", e)
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

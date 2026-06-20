"""CLI command: profile-cursors — Analyze columns for cursor strategies."""

from __future__ import annotations

import logging
import sys

import click

logger = logging.getLogger(__name__)


@click.command("profile-cursors")
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option(
    "--batch-size",
    default=5_000_000,
    type=int,
    help="Target batch size (default: 5,000,000)",
)
@click.option(
    "--candidates",
    multiple=True,
    help="Candidate columns to profile (auto-detected if not specified)",
)
@click.option(
    "--hash-column",
    default=None,
    help="Column for hash cursor profiling (default: source unique_key)",
)
def profile_cursors(
    config: str,
    batch_size: int,
    candidates: tuple[str, ...],
    hash_column: str | None,
) -> None:
    """Analyze source columns to recommend cursor strategies.

    Profiles candidate columns for use as secondary cursors in composite
    watermarks. Also profiles hash-based virtual cursors as a fallback.

    Example:
        bq-er profile-cursors --config config.yml --batch-size 5000000
        bq-er profile-cursors --config config.yml --candidates policy_id state
    """
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.tools.cursor_profiler import CursorProfiler

    try:
        cfg = load_config(config)
        source = cfg.sources[0]

        # Build candidate list
        if candidates:
            candidate_list = list(candidates)
        else:
            # Auto-detect: all non-timestamp, non-key columns
            candidate_list = [
                col.name for col in source.columns
                if col.name not in (source.unique_key, source.updated_at)
                and col.type not in ("TIMESTAMP", "DATETIME")
            ]

        primary_cursor = source.updated_at or "updated_at"
        hc = hash_column or source.unique_key

        click.echo(f"Source: {source.table}")
        click.echo(f"Primary cursor: {primary_cursor}")
        click.echo(f"Candidates: {candidate_list}")
        click.echo(f"Batch size: {batch_size:,}")
        click.echo("")

        from bq_entity_resolution.backends.bigquery import BigQueryBackend
        from bq_entity_resolution.clients.bigquery import BigQueryClient

        with BigQueryClient(
            project=cfg.project.bq_project,
            location=cfg.project.bq_location,
        ) as bq_client:
            with BigQueryBackend(bq_client) as backend:
                profiler = CursorProfiler(backend)

                # Profile natural columns
                natural_results = []
                if candidate_list:
                    click.echo("Profiling natural columns...")
                    natural_results = profiler.profile(
                        table=source.table,
                        primary_cursor=primary_cursor,
                        candidate_columns=candidate_list,
                        batch_size=batch_size,
                    )

                # Profile hash cursor
                click.echo("Profiling hash cursor...")
                hash_results = profiler.profile_hash_cursor(
                    table=source.table,
                    hash_column=hc,
                    primary_cursor=primary_cursor,
                    batch_size=batch_size,
                )

                # Print recommendation
                click.echo("")
                click.echo(profiler.recommend(natural_results, hash_results, batch_size))

    except Exception as e:
        logger.exception("Cursor profiling failed: %s", e)
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

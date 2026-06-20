"""CLI command: run — Execute the entity resolution pipeline."""

from __future__ import annotations

import logging
import sys

import click

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option(
    "--defaults",
    default=None,
    type=click.Path(exists=True),
    help="Path to defaults YAML",
)
@click.option("--full-refresh", is_flag=True, help="Ignore watermarks, reprocess all")
@click.option("--dry-run", is_flag=True, help="Generate SQL but don't execute")
@click.option("--drain", is_flag=True, help="Auto-loop through batches until all records processed")
@click.option("--resume", is_flag=True, help="Resume from last checkpoint on failure")
@click.option("--tier", multiple=True, help="Run only specific tier(s) by name")
def run(
    config: str,
    defaults: str | None,
    full_refresh: bool,
    dry_run: bool,
    drain: bool,
    resume: bool,
    tier: tuple[str, ...],
) -> None:
    """Execute the entity resolution pipeline."""
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.monitoring.logging import setup_logging
    from bq_entity_resolution.pipeline.executor import PipelineResult
    from bq_entity_resolution.pipeline.pipeline import Pipeline

    try:
        cfg = load_config(config, defaults)

        # Initialize structured logging from config
        setup_logging(
            level=cfg.monitoring.log_level,
            fmt=cfg.monitoring.log_format,
        )

        # Filter to specific tiers if requested
        if tier:
            tier_names = set(tier)
            original_count = len(cfg.matching_tiers)
            cfg.matching_tiers = [
                t for t in cfg.matching_tiers if t.name in tier_names
            ]
            if not cfg.matching_tiers:
                click.echo(
                    f"No matching tiers found for: {tier_names}. "
                    f"Available: "
                    f"{[t.name for t in load_config(config, defaults).matching_tiers]}",
                    err=True,
                )
                sys.exit(1)
            click.echo(
                f"Running {len(cfg.matching_tiers)}/{original_count} tier(s): "
                f"{[t.name for t in cfg.matching_tiers]}"
            )

        pipeline = Pipeline(cfg)

        if dry_run:
            plan = pipeline.plan(full_refresh=full_refresh)
            click.echo("DRY RUN — Generated SQL preview:")
            click.echo(plan.preview())
            # Also show cost estimate if backend is available
            try:
                from bq_entity_resolution.backends.bigquery import BigQueryBackend

                with BigQueryBackend(project=cfg.project.bq_project) as backend:
                    estimate = pipeline.estimate_cost(backend=backend)
                    click.echo(f"\nEstimated cost: {estimate.total_gb:.2f} GB "
                               f"(~${estimate.estimated_cost_usd:.4f})")
            except Exception:
                pass  # Cost estimation requires BQ access; skip if unavailable
        else:
            from bq_entity_resolution.backends.bigquery import BigQueryBackend
            from bq_entity_resolution.clients.bigquery import BigQueryClient

            bq_client = BigQueryClient(
                project=cfg.project.bq_project,
                location=cfg.project.bq_location,
                max_bytes_billed=cfg.scale.max_bytes_billed,
                default_timeout=cfg.execution.query_timeout_seconds,
            )
            with BigQueryBackend(bq_client) as backend:
                # Set up checkpoint manager for --resume
                checkpoint_manager = None
                if resume and cfg.scale.checkpoint_enabled:
                    from bq_entity_resolution.watermark.checkpoint import CheckpointManager

                    checkpoint_table = (
                        f"{cfg.project.bq_project}.{cfg.project.watermark_dataset}"
                        f".pipeline_checkpoints"
                    )
                    checkpoint_manager = CheckpointManager(bq_client, checkpoint_table)

                result = pipeline.run(
                    backend=backend,
                    full_refresh=full_refresh,
                    drain=drain,
                    resume=resume,
                    checkpoint_manager=checkpoint_manager,  # type: ignore[arg-type]
                )

                if isinstance(result, PipelineResult):
                    click.echo(f"\nPipeline completed: {result.run_id}")
                    click.echo(f"Stages executed: {len(result.completed_stages)}")
                    for stage in result.completed_stages:
                        click.echo(f"  - {stage}")

    except Exception as e:
        logger.exception("Pipeline failed: %s", e)
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

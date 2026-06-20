"""CLI command: ingest-labels — Ingest human labels and optionally retrain."""

from __future__ import annotations

import sys

import click


@click.command("ingest-labels")
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option("--defaults", default=None, type=click.Path(exists=True))
@click.option("--tier", required=True, help="Tier name to ingest labels for")
@click.option("--retrain", is_flag=True, help="Re-estimate m/u after ingestion")
@click.option("--dry-run", is_flag=True, help="Preview SQL without executing")
def ingest_labels(
    config: str,
    defaults: str | None,
    tier: str,
    retrain: bool,
    dry_run: bool,
) -> None:
    """Ingest human labels from the review queue and optionally retrain m/u."""
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.matching.active_learning import ActiveLearningEngine
    from bq_entity_resolution.matching.parameters import ParameterEstimator

    try:
        cfg = load_config(config, defaults)
        tier_cfg = next((t for t in cfg.matching_tiers if t.name == tier), None)
        if not tier_cfg:
            available = [t.name for t in cfg.matching_tiers]
            click.echo(f"Tier '{tier}' not found. Available: {available}", err=True)
            sys.exit(1)

        al_engine = ActiveLearningEngine(cfg)

        # Generate and show/execute ingestion SQL
        ingest_sql = al_engine.generate_label_ingestion_sql(tier_cfg)
        if dry_run:
            click.echo("-- LABEL INGESTION SQL --")
            click.echo(ingest_sql)
        else:
            from bq_entity_resolution.clients.bigquery import BigQueryClient
            from bq_entity_resolution.pipeline.runner import SQLRunner

            bq_client = BigQueryClient(
                project=cfg.project.bq_project,
                location=cfg.project.bq_location,
            )
            runner = SQLRunner(bq_client)
            runner.execute_script(ingest_sql, job_label=f"ingest_labels_{tier}")
            click.echo(f"Labels ingested for tier '{tier}'")

        # Optionally retrain
        if retrain:
            estimator = ParameterEstimator(cfg)
            retrain_sql = estimator.generate_reestimation_sql(tier_cfg)
            if dry_run:
                click.echo("\n-- REESTIMATION SQL --")
                click.echo(retrain_sql)
            else:
                click.echo(f"Re-estimating m/u for tier '{tier}'...")
                result = runner.execute_and_fetch(
                    retrain_sql, job_label=f"retrain_{tier}"
                )
                click.echo(f"Reestimation complete: {len(result)} parameter rows")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

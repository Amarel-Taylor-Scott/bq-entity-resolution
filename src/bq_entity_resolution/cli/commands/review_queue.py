"""CLI command: review-queue — Preview active learning review queue SQL."""

from __future__ import annotations

import sys

import click


@click.command("review-queue")
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option("--defaults", default=None, type=click.Path(exists=True))
@click.option("--tier", required=True, help="Tier name to generate review queue for")
def review_queue(config: str, defaults: str | None, tier: str) -> None:
    """Preview active learning review queue SQL for a tier."""
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.matching.active_learning import ActiveLearningEngine

    try:
        cfg = load_config(config, defaults)
        tier_cfg = next((t for t in cfg.matching_tiers if t.name == tier), None)
        if not tier_cfg:
            available = [t.name for t in cfg.matching_tiers]
            click.echo(f"Tier '{tier}' not found. Available: {available}", err=True)
            sys.exit(1)

        al_engine = ActiveLearningEngine(cfg)
        click.echo("-- ACTIVE LEARNING REVIEW QUEUE SQL --")
        click.echo(al_engine.generate_review_queue_sql(tier_cfg))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

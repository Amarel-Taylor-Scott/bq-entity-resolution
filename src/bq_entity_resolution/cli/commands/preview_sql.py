"""CLI command: preview-sql — Preview generated SQL for a specific tier."""

from __future__ import annotations

import sys

import click


@click.command("preview-sql")
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option("--defaults", default=None, type=click.Path(exists=True))
@click.option("--tier", required=True, help="Tier name to preview SQL for")
@click.option(
    "--stage",
    default="all",
    type=click.Choice(["all", "blocking", "matching"], case_sensitive=False),
    help="Which stage to preview",
)
def preview_sql(config: str, defaults: str | None, tier: str, stage: str) -> None:
    """Preview generated SQL for a specific tier without executing."""
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.stages.blocking import BlockingStage
    from bq_entity_resolution.stages.matching import MatchingStage

    try:
        cfg = load_config(config, defaults)
        tier_cfg = next((t for t in cfg.matching_tiers if t.name == tier), None)
        if not tier_cfg:
            available = [t.name for t in cfg.matching_tiers]
            click.echo(f"Tier '{tier}' not found. Available: {available}", err=True)
            sys.exit(1)

        tier_index = next(
            i for i, t in enumerate(cfg.matching_tiers) if t.name == tier
        )

        if stage in ("all", "blocking"):
            blocking_stage = BlockingStage(tier_cfg, tier_index, cfg)
            click.echo("-- BLOCKING SQL --")
            for expr in blocking_stage.plan():
                click.echo(expr.render())
            click.echo()

        if stage in ("all", "matching"):
            matching_stage = MatchingStage(tier_cfg, tier_index, cfg)
            click.echo("-- MATCHING SQL --")
            for expr in matching_stage.plan():
                click.echo(expr.render())

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

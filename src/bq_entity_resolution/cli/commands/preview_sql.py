"""CLI command: preview-sql — Preview generated SQL for a tier or a leaf."""

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
@click.option("--tier", default=None, help="Tier name to preview SQL for")
@click.option(
    "--leaf",
    default=None,
    help="Resolution leaf name to preview SQL for (e.g. new_x_old, old_x_old). "
    "Previews the leaf's candidate-pair SQL regardless of its schedule.",
)
@click.option(
    "--stage",
    default="all",
    type=click.Choice(["all", "blocking", "matching"], case_sensitive=False),
    help="Which stage to preview (tier mode only)",
)
def preview_sql(
    config: str,
    defaults: str | None,
    tier: str | None,
    leaf: str | None,
    stage: str,
) -> None:
    """Preview generated SQL for a specific tier or leaf without executing."""
    from bq_entity_resolution.config.loader import load_config

    try:
        cfg = load_config(config, defaults)

        if tier and leaf:
            click.echo("Specify only one of --tier / --leaf.", err=True)
            sys.exit(1)
        if not tier and not leaf:
            click.echo("Specify one of --tier / --leaf.", err=True)
            sys.exit(1)

        if leaf:
            _preview_leaf(cfg, leaf)
            return

        _preview_tier(cfg, tier, stage)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _preview_leaf(cfg, leaf: str) -> None:
    from bq_entity_resolution.stages.leaf_resolution import LeafResolutionStage

    known = {lf.name for lf in cfg.effective_leaves()}
    if leaf not in known:
        click.echo(f"Leaf '{leaf}' not found. Available: {sorted(known)}", err=True)
        sys.exit(1)

    selected = cfg.select_leaves(only=[leaf])
    leaf_stage = LeafResolutionStage(cfg, leaves=selected)
    click.echo(f"-- LEAF SQL ({leaf}) --")
    exprs = leaf_stage.plan()
    if not exprs:
        click.echo(
            f"-- (leaf '{leaf}' produced no SQL: no usable comparisons / "
            "blocking paths for the configured tiers)"
        )
        return
    for expr in exprs:
        click.echo(expr.render())
        click.echo()


def _preview_tier(cfg, tier: str, stage: str) -> None:
    from bq_entity_resolution.stages.blocking import BlockingStage
    from bq_entity_resolution.stages.matching import MatchingStage

    tier_cfg = next((t for t in cfg.matching_tiers if t.name == tier), None)
    if not tier_cfg:
        available = [t.name for t in cfg.matching_tiers]
        click.echo(f"Tier '{tier}' not found. Available: {available}", err=True)
        sys.exit(1)

    tier_index = next(i for i, t in enumerate(cfg.matching_tiers) if t.name == tier)

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

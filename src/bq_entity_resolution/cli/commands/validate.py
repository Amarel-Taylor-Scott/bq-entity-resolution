"""CLI command: validate — Validate configuration without running."""

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
def validate(config: str, defaults: str | None) -> None:
    """Validate configuration without running the pipeline."""
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.config.validators import validate_full

    try:
        cfg = load_config(config, defaults)
        validate_full(cfg)

        click.echo("Configuration valid!")
        click.echo(f"  Project: {cfg.project.name}")
        click.echo(f"  Sources: {len(cfg.sources)}")
        for s in cfg.sources:
            click.echo(f"    - {s.name} ({s.table}): {len(s.columns)} columns")
        click.echo(f"  Matching tiers: {len(cfg.matching_tiers)}")
        for t in cfg.matching_tiers:
            status = "enabled" if t.enabled else "disabled"
            click.echo(
                f"    - {t.name} ({status}): "
                f"{len(t.comparisons)} comparisons, "
                f"{len(t.blocking.paths)} blocking paths"
            )
        click.echo(f"  Embeddings: {'enabled' if cfg.embeddings.enabled else 'disabled'}")
        click.echo(f"  Incremental: {'enabled' if cfg.incremental.enabled else 'disabled'}")

    except Exception as e:
        click.echo(f"Configuration INVALID: {e}", err=True)
        sys.exit(1)

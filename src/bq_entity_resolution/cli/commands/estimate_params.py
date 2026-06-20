"""CLI command: estimate-params — Estimate m/u parameters for Fellegi-Sunter."""

from __future__ import annotations

import sys

import click


@click.command("estimate-params")
@click.option(
    "--config",
    required=True,
    type=click.Path(exists=True),
    help="Path to pipeline config YAML",
)
@click.option("--defaults", default=None, type=click.Path(exists=True))
@click.option("--tier", required=True, help="Tier name to estimate parameters for")
def estimate_params(config: str, defaults: str | None, tier: str) -> None:
    """Estimate m/u parameters for a Fellegi-Sunter tier."""
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.matching.parameters import ParameterEstimator

    try:
        cfg = load_config(config, defaults)
        tier_cfg = next((t for t in cfg.matching_tiers if t.name == tier), None)
        if not tier_cfg:
            available = [t.name for t in cfg.matching_tiers]
            click.echo(f"Tier '{tier}' not found. Available: {available}", err=True)
            sys.exit(1)

        estimator = ParameterEstimator(cfg)
        training = estimator.resolve_training_config(tier_cfg)

        if training.method == "none":
            click.echo(
                f"No training configured for tier '{tier}'. "
                f"Set training.method to 'labeled' or 'em'.",
                err=True,
            )
            sys.exit(1)

        click.echo(f"-- PARAMETER ESTIMATION SQL ({training.method}) --")
        if training.method == "labeled":
            click.echo(estimator.generate_label_estimation_sql(tier_cfg, training))
        else:
            click.echo(estimator.generate_em_estimation_sql(tier_cfg, training))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

"""CLI command: analyze — Analyze weight sensitivity for a matching tier."""

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
@click.option("--tier", required=True, help="Tier name to analyze")
@click.option(
    "--analysis",
    default="contribution",
    type=click.Choice(["contribution", "threshold", "impact"], case_sensitive=False),
    help="Type of analysis to run",
)
def analyze(config: str, defaults: str | None, tier: str, analysis: str) -> None:
    """Analyze weight sensitivity for a matching tier.

    Three analysis types:
    - contribution: which comparisons drive matches
    - threshold: match counts at different threshold values
    - impact: effect of changing each comparison's weight
    """
    from bq_entity_resolution.config.loader import load_config
    from bq_entity_resolution.profiling.weight_sensitivity import WeightSensitivityAnalyzer

    try:
        cfg = load_config(config, defaults)
        tier_cfg = next((t for t in cfg.matching_tiers if t.name == tier), None)
        if not tier_cfg:
            available = [t.name for t in cfg.matching_tiers]
            click.echo(f"Tier '{tier}' not found. Available: {available}", err=True)
            sys.exit(1)

        analyzer = WeightSensitivityAnalyzer(cfg)

        if analysis == "contribution":
            click.echo(f"-- WEIGHT CONTRIBUTION ANALYSIS: {tier} --")
            click.echo(analyzer.generate_contribution_sql(tier_cfg))
        elif analysis == "threshold":
            click.echo(f"-- THRESHOLD SWEEP: {tier} --")
            click.echo(analyzer.generate_threshold_sweep_sql(tier_cfg))
        elif analysis == "impact":
            click.echo(f"-- WEIGHT IMPACT ANALYSIS: {tier} --")
            click.echo(analyzer.generate_weight_impact_sql(tier_cfg))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

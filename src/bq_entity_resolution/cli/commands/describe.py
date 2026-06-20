"""CLI command: describe — Show a human-readable summary of pipeline configuration."""

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
def describe(config: str, defaults: str | None) -> None:
    """Show a human-readable summary of pipeline configuration.

    Displays sources, features, blocking keys, tiers, comparisons,
    and estimated table outputs — a quick way to understand
    what the pipeline will do before running it.
    """
    from bq_entity_resolution.config.loader import load_config

    try:
        cfg = load_config(config, defaults)

        click.echo(f"Pipeline: {cfg.project.name}")
        click.echo(f"Project:  {cfg.project.bq_project}")
        click.echo(f"Link type: {cfg.link_type}")
        click.echo()

        # Sources
        click.echo(f"Sources ({len(cfg.sources)}):")
        for s in cfg.sources:
            click.echo(f"  {s.name}")
            click.echo(f"    Table: {s.table}")
            click.echo(f"    Key: {s.unique_key}  Updated: {s.updated_at}")
            click.echo(f"    Columns: {len(s.columns)}")
            for c in s.columns[:8]:
                role_str = f" (role: {c.role})" if getattr(c, "role", None) else ""
                click.echo(f"      - {c.name}: {getattr(c, 'type', 'STRING')}{role_str}")
            if len(s.columns) > 8:
                click.echo(f"      ... and {len(s.columns) - 8} more")
        click.echo()

        # Feature engineering
        fe = cfg.feature_engineering
        all_features = []
        all_bk = []
        # Collect features from all groups using model_fields (Pydantic v2)
        field_names = fe.model_fields if hasattr(fe, "model_fields") else {}
        for group_name in field_names:
            group = getattr(fe, group_name, None)
            if group is not None and hasattr(group, "features"):
                all_features.extend(group.features)
        if hasattr(fe, "blocking_keys"):
            all_bk = fe.blocking_keys

        click.echo("Feature Engineering:")
        click.echo(f"  Features: {len(all_features)}")
        for feat in all_features[:6]:
            click.echo(f"    - {feat.name} ({feat.function})")
        if len(all_features) > 6:
            click.echo(f"    ... and {len(all_features) - 6} more")

        click.echo(f"  Blocking keys: {len(all_bk)}")
        for bk in all_bk:
            click.echo(f"    - {bk.name} ({bk.function})")
        click.echo()

        # Comparison pool
        if cfg.comparison_pool:
            click.echo(f"Comparison Pool ({len(cfg.comparison_pool)} methods):")
            for name, comp in list(cfg.comparison_pool.items())[:8]:
                click.echo(f"  - {name}: {comp.method} (weight: {comp.weight})")
            if len(cfg.comparison_pool) > 8:
                click.echo(f"  ... and {len(cfg.comparison_pool) - 8} more")
            click.echo()

        # Matching tiers
        click.echo(f"Matching Tiers ({len(cfg.matching_tiers)}):")
        for t in cfg.matching_tiers:
            status = "enabled" if t.enabled else "DISABLED"
            click.echo(f"  {t.name} [{status}]")
            if t.description:
                click.echo(f"    {t.description}")
            click.echo(f"    Blocking paths: {len(t.blocking.paths)}")
            for i, path in enumerate(t.blocking.paths):
                click.echo(f"      Path {i}: keys={path.keys}")
            click.echo(f"    Comparisons: {len(t.comparisons)}")
            for comp in t.comparisons[:4]:
                if getattr(comp, "ref", None):
                    click.echo(f"      - ref: {comp.ref}")
                else:
                    click.echo(
                        f"      - {comp.left} vs {comp.right}: {comp.method} (w={comp.weight})"
                    )
            if len(t.comparisons) > 4:
                click.echo(f"      ... and {len(t.comparisons) - 4} more")
            threshold = t.threshold
            click.echo(f"    Threshold: {threshold.method} >= {threshold.min_score}")
        click.echo()

        # Scale / incremental
        click.echo(f"Incremental: {'enabled' if cfg.incremental.enabled else 'disabled'}")
        click.echo(f"Embeddings:  {'enabled' if cfg.embeddings.enabled else 'disabled'}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

"""CLI command: init — Scaffold a starter config YAML."""

from __future__ import annotations

from typing import Any

import click


@click.command()
@click.option("--project", prompt="GCP project ID", help="GCP project ID")
@click.option(
    "--table",
    default=None,
    help="Source table (project.dataset.table) — auto-discovers columns if set",
)
@click.option(
    "--preset",
    default="auto",
    type=click.Choice(
        ["auto", "person_dedup", "person_linkage", "business_dedup",
         "insurance", "financial", "healthcare"],
        case_sensitive=False,
    ),
    help="Config preset to use",
)
@click.option(
    "--output",
    default="config.yml",
    type=click.Path(),
    help="Output config file path",
)
def init(project: str, table: str | None, preset: str, output: str) -> None:
    """Scaffold a starter config YAML from prompts or table auto-discovery.

    Examples:
        bq-er init --project my-project --table my-project.raw.customers
        bq-er init --project my-project --preset insurance --output insurance.yml
    """
    import yaml as _yaml

    from bq_entity_resolution.config.roles import (
        ROLE_COMPARISONS,
        ROLE_FEATURES,
        detect_role,
    )

    columns: list[dict[str, str]] = []
    features: list[dict[str, str]] = []
    blocking_keys: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    source_name = "source"
    source_table = table or f"{project}.raw.YOUR_TABLE"

    if table:
        # Extract source name from table
        parts = table.rsplit(".", 1)
        source_name = parts[-1] if parts else "source"

        # Try live auto-discovery via BigQuery INFORMATION_SCHEMA
        try:
            from google.cloud import bigquery as _bq  # noqa: F401

            dataset_parts = table.split(".")
            if len(dataset_parts) == 3:
                from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref

                # Validate full reference before using parts in SQL
                validate_table_ref(table)
                with _bq.Client(project=project) as client:
                    table_safe = sql_escape(dataset_parts[2])
                    schema_query = (
                        f"SELECT column_name, data_type "
                        f"FROM `{dataset_parts[0]}.{dataset_parts[1]}.INFORMATION_SCHEMA.COLUMNS` "
                        f"WHERE table_name = '{table_safe}' "
                        f"ORDER BY ordinal_position"
                    )
                    rows = list(client.query(schema_query).result())
                    click.echo(f"Discovered {len(rows)} columns from {table}")
                    for row in rows:
                        col_name = row["column_name"]
                        col_type = row["data_type"]
                        columns.append({"name": col_name, "type": col_type})
                        role = detect_role(col_name)
                        if role:
                            click.echo(f"  {col_name} ({col_type}) -> role: {role}")
        except Exception as exc:
            click.echo(
                f"Could not auto-discover columns from BigQuery: {exc}\n"
                f"Generating template config with placeholder columns.",
                err=True,
            )

    # If no columns discovered, provide placeholder examples
    if not columns:
        columns = [
            {"name": "id", "type": "STRING"},
            {"name": "first_name", "type": "STRING"},
            {"name": "last_name", "type": "STRING"},
            {"name": "email", "type": "STRING"},
            {"name": "phone", "type": "STRING"},
            {"name": "updated_at", "type": "TIMESTAMP"},
        ]

    # Auto-generate features and comparisons from discovered roles
    for col_def in columns:
        col_name = col_def["name"]
        role = detect_role(col_name)
        if not role:
            continue

        # Features
        for suffix, func in ROLE_FEATURES.get(role, []):
            feat_name = f"{col_name}_{suffix}" if suffix else col_name
            features.append({
                "name": feat_name,
                "function": func,
                "input": col_name,
            })

        # Blocking keys (first feature per role)
        from bq_entity_resolution.config.roles import ROLE_BLOCKING_KEYS

        for bk_suffix, bk_func in ROLE_BLOCKING_KEYS.get(role, []):
            blocking_keys.append({
                "name": f"bk_{bk_suffix}",
                "function": bk_func,
                "inputs": [col_name],
            })

        # Comparisons
        for spec in ROLE_COMPARISONS.get(role, []):
            feature_col = (
                f"{col_name}_{spec.feature_suffix}"
                if spec.feature_suffix
                else col_name
            )
            comp: dict[str, Any] = {
                "left": feature_col,
                "right": feature_col,
                "method": spec.method,
                "weight": spec.weight,
            }
            if spec.params:
                comp["params"] = dict(spec.params)
            comparisons.append(comp)

    # Build config dict
    total_weight = sum(c.get("weight", 1.0) for c in comparisons) if comparisons else 10.0

    config_dict: dict[str, Any] = {
        "version": "1.0",
        "project": {
            "name": source_name,
            "bq_project": f"${{BQ_PROJECT:-{project}}}",
        },
        "sources": [{
            "name": source_name,
            "table": (
                f"${{BQ_PROJECT:-{project}}}."
                + (
                    ".".join(source_table.split(".")[1:])
                    if "." in source_table
                    else "raw." + source_name
                )
            ),
            "unique_key": "id",
            "updated_at": "updated_at",
            "columns": columns,
        }],
    }

    if features:
        config_dict["feature_engineering"] = {
            "auto_features": {"features": features},
            "blocking_keys": blocking_keys,
        }

    if comparisons:
        bk_names = [bk["name"] for bk in blocking_keys] if blocking_keys else ["bk_email_domain"]
        config_dict["matching_tiers"] = [
            {
                "name": "exact",
                "description": "High-confidence exact matches",
                "blocking": {"paths": [{"keys": bk_names[:2] if len(bk_names) >= 2 else bk_names}]},
                "comparisons": comparisons,
                "threshold": {"min_score": round(total_weight * 0.7, 1)},
            },
            {
                "name": "fuzzy",
                "description": "Fuzzy probabilistic matches",
                "blocking": {
                    "paths": [{"keys": bk_names[2:4] if len(bk_names) > 2 else bk_names[:1]}],
                },
                "comparisons": comparisons,
                "threshold": {"min_score": round(total_weight * 0.4, 1)},
            },
        ]

    # Write YAML
    from pathlib import Path as _Path

    output_path = _Path(output)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Auto-generated config for {source_name}\n")
        f.write(f"# Generated by: bq-er init --project {project}\n")
        f.write("#\n")
        f.write("# Next steps:\n")
        f.write("#   1. Review and adjust columns, features, and comparisons\n")
        f.write(f"#   2. Validate: bq-er validate --config {output}\n")
        f.write(f"#   3. Preview:  bq-er preview-sql --config {output} --tier exact --stage all\n")
        f.write(f"#   4. Run:      bq-er run --config {output} --dry-run\n")
        f.write(f"#   5. Execute:  bq-er run --config {output}\n")
        f.write("#\n\n")
        _yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    click.echo(f"\nConfig written to {output_path}")
    click.echo(f"  Sources: 1 ({source_name})")
    click.echo(f"  Columns: {len(columns)}")
    click.echo(f"  Features: {len(features)}")
    click.echo(f"  Blocking keys: {len(blocking_keys)}")
    click.echo(f"  Comparisons: {len(comparisons)}")
    click.echo(f"  Tiers: {'2 (exact + fuzzy)' if comparisons else '0 — add comparisons manually'}")
    click.echo(f"\nRun 'bq-er validate --config {output}' to check the config.")

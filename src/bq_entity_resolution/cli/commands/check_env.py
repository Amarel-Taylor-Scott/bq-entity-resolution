"""CLI command: check-env — Verify environment setup for running the pipeline."""

from __future__ import annotations

import os
import sys

import click


@click.command("check-env")
@click.option(
    "--config",
    default=None,
    type=click.Path(exists=True),
    help="Optional config to check project-specific settings",
)
def check_env(config: str | None) -> None:
    """Verify environment setup for running the pipeline.

    Checks: Python version, required packages, GCP auth,
    BQ_PROJECT env var, and dataset accessibility.
    """
    import importlib

    issues: list[str] = []
    ok: list[str] = []

    # Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):  # noqa: UP036 — runtime user-facing check
        ok.append(f"Python {py_version}")
    else:
        issues.append(f"Python {py_version} (requires 3.11+)")

    # Required packages
    required_packages = [
        ("pydantic", "pydantic"),
        ("yaml", "pyyaml"),
        ("click", "click"),
        ("sqlglot", "sqlglot"),
    ]
    for import_name, pip_name in required_packages:
        try:
            mod = importlib.import_module(import_name)
            try:
                from importlib.metadata import version as _pkg_version

                ver = _pkg_version(pip_name)
            except Exception:
                ver = getattr(mod, "__version__", "?")
            ok.append(f"{pip_name} {ver}")
        except ImportError:
            issues.append(f"{pip_name} not installed — pip install {pip_name}")

    # google-cloud-bigquery (optional but needed for execution)
    try:
        from google.cloud import bigquery as _bq

        ok.append(f"google-cloud-bigquery {_bq.__version__}")
    except ImportError:
        issues.append(
            "google-cloud-bigquery not installed — "
            "pip install google-cloud-bigquery (required for BQ execution)"
        )

    # BQ_PROJECT env var
    bq_project = os.environ.get("BQ_PROJECT")
    if bq_project:
        ok.append(f"BQ_PROJECT={bq_project}")
    else:
        issues.append(
            "BQ_PROJECT not set — export BQ_PROJECT=your-gcp-project"
        )

    # GCP auth
    try:
        import google.auth

        credentials, project = google.auth.default()
        ok.append(f"GCP auth OK (project: {project or 'from credentials'})")
    except Exception as exc:
        issues.append(
            f"GCP auth failed: {exc} — "
            f"run 'gcloud auth application-default login' "
            f"or set GOOGLE_APPLICATION_CREDENTIALS"
        )

    # If config provided, check project-specific settings
    if config:
        try:
            from bq_entity_resolution.config.loader import load_config

            cfg = load_config(config)
            ok.append(f"Config valid: {cfg.project.name} ({len(cfg.sources)} source(s))")

            # Try to validate dataset exists
            if bq_project:
                try:
                    from google.cloud import bigquery as _bq2

                    with _bq2.Client(project=cfg.project.bq_project) as client:
                        for source in cfg.sources:
                            parts = source.table.split(".")
                            if len(parts) >= 2:
                                ds_ref = f"{parts[0]}.{parts[1]}"
                                try:
                                    client.get_dataset(ds_ref)
                                    ok.append(f"Dataset accessible: {ds_ref}")
                                except Exception:
                                    issues.append(f"Dataset not accessible: {ds_ref}")
                except Exception:
                    pass  # BQ client errors already covered
        except Exception as exc:
            issues.append(f"Config invalid: {exc}")

    # Print results
    click.echo("Environment check:")
    click.echo()
    for item in ok:
        click.echo(f"  [OK] {item}")
    for item in issues:
        click.echo(f"  [!!] {item}")

    click.echo()
    if issues:
        click.echo(f"{len(issues)} issue(s) found. Fix these before running the pipeline.")
        sys.exit(1)
    else:
        click.echo("All checks passed. Ready to run.")

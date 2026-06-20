"""Main CLI group for bq-entity-resolution."""

from __future__ import annotations

import click

from bq_entity_resolution.cli.commands.analyze import analyze
from bq_entity_resolution.cli.commands.check_env import check_env
from bq_entity_resolution.cli.commands.describe import describe
from bq_entity_resolution.cli.commands.estimate_params import estimate_params
from bq_entity_resolution.cli.commands.ingest_labels import ingest_labels
from bq_entity_resolution.cli.commands.init_config import init
from bq_entity_resolution.cli.commands.preview_sql import preview_sql
from bq_entity_resolution.cli.commands.profile import profile
from bq_entity_resolution.cli.commands.profile_cursors import profile_cursors
from bq_entity_resolution.cli.commands.profile_placeholders import profile_placeholders
from bq_entity_resolution.cli.commands.review_queue import review_queue
from bq_entity_resolution.cli.commands.run import run
from bq_entity_resolution.cli.commands.validate import validate
from bq_entity_resolution.version import __version__


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level",
)
@click.option(
    "--log-format",
    default="json",
    type=click.Choice(["json", "text"], case_sensitive=False),
    help="Log output format",
)
def cli(log_level: str, log_format: str) -> None:
    """BigQuery Entity Resolution Pipeline."""
    from bq_entity_resolution.monitoring.logging import setup_logging

    setup_logging(log_level, log_format)


cli.add_command(run)
cli.add_command(validate)
cli.add_command(preview_sql)
cli.add_command(estimate_params)
cli.add_command(review_queue)
cli.add_command(ingest_labels)
cli.add_command(profile)
cli.add_command(profile_cursors)
cli.add_command(profile_placeholders)
cli.add_command(analyze)
cli.add_command(init)
cli.add_command(check_env)
cli.add_command(describe)

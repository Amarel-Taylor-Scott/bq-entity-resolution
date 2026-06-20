"""Placeholder detection stage: scans featured data for sentinel values.

Logs suspected placeholder values to a tracking table for data quality
monitoring. Runs after feature engineering so detection functions have
access to all engineered features.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS
from bq_entity_resolution.naming import featured_table, placeholder_detection_table
from bq_entity_resolution.sql.builders.placeholder_tracking import (
    PlaceholderScanColumn,
    PlaceholderScanParams,
    build_create_placeholder_table_sql,
    build_placeholder_scan_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)

# Maps column roles to placeholder detection function names
_ROLE_TO_DETECTION: dict[str, str] = {
    "phone": "is_placeholder_phone",
    "mobile_phone": "is_placeholder_phone",
    "home_phone": "is_placeholder_phone",
    "work_phone": "is_placeholder_phone",
    "fax": "is_placeholder_phone",
    "email": "is_placeholder_email",
    "personal_email": "is_placeholder_email",
    "work_email": "is_placeholder_email",
    "first_name": "is_placeholder_name",
    "last_name": "is_placeholder_name",
    "middle_name": "is_placeholder_name",
    "full_name": "is_placeholder_name",
    "company_name": "is_placeholder_name",
    "address_line_1": "is_placeholder_address",
    "address_line_2": "is_placeholder_address",
    "street_address": "is_placeholder_address",
    "ssn": "is_placeholder_ssn",
    "tin": "is_placeholder_ssn",
}


class PlaceholderDetectionStage(Stage):
    """Scan featured data for suspected placeholder values.

    Generates CREATE TABLE + INSERT per source, logging values that
    match known placeholder patterns with counts above min_count.
    """

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "placeholder_detection"

    @property
    def inputs(self) -> dict[str, TableRef]:
        target = featured_table(self._config)
        return {
            "featured": TableRef(name="featured", fq_name=target),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = placeholder_detection_table(self._config)
        return {
            "placeholder_detection_log": TableRef(
                name="placeholder_detection_log",
                fq_name=target,
                description="Placeholder detection log table",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate placeholder scan SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        config = self._config
        tracking = config.monitoring.placeholder_tracking
        target = placeholder_detection_table(config)
        source_table = featured_table(config)

        sqls: list[SQLExpression] = []

        # Create tracking table
        sqls.append(build_create_placeholder_table_sql(target))

        # Build scan columns from source column roles
        placeholder_cfg = config.feature_engineering.placeholder
        scan_columns: list[PlaceholderScanColumn] = []

        for source in config.sources:
            for col in source.columns:
                role = getattr(col, "role", "")
                if role not in _ROLE_TO_DETECTION:
                    continue

                detection_fn_name = _ROLE_TO_DETECTION[role]

                # Check domain-level enable flags
                if "phone" in detection_fn_name and not placeholder_cfg.detect_phone:
                    continue
                if "email" in detection_fn_name and not placeholder_cfg.detect_email:
                    continue
                if "name" in detection_fn_name and not placeholder_cfg.detect_name:
                    continue
                if "address" in detection_fn_name and not placeholder_cfg.detect_address:
                    continue
                if "ssn" in detection_fn_name and not placeholder_cfg.detect_ssn:
                    continue

                # Get the detection SQL expression
                func = FEATURE_FUNCTIONS.get(detection_fn_name)
                if func is None:
                    continue

                try:
                    detection_sql = func([col.name])
                except Exception as exc:
                    logger.warning(
                        "Skipping placeholder scan for column '%s': %s",
                        col.name, exc,
                    )
                    continue

                # Avoid duplicates
                if not any(sc.column_name == col.name for sc in scan_columns):
                    pattern_type = role.split("_")[0] if "_" in role else role
                    scan_columns.append(PlaceholderScanColumn(
                        column_name=col.name,
                        pattern_type=pattern_type,
                        detection_sql=detection_sql,
                    ))

        if scan_columns:
            for source in config.sources:
                params = PlaceholderScanParams(
                    target_table=target,
                    source_table=source_table,
                    run_id=kwargs.get("run_id", ""),
                    source_name=source.name,
                    scan_columns=scan_columns,
                    min_count=tracking.min_count,
                )
                sqls.append(build_placeholder_scan_sql(params))

        return sqls

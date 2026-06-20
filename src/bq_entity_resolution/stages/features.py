"""Feature engineering stage: computes features, blocking keys, and term frequencies.

Extracted from PipelineOrchestrator._engineer_features() and
_compute_term_frequencies().
Uses the features SQL builder for SQL generation.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS
from bq_entity_resolution.naming import featured_table, staged_table
from bq_entity_resolution.sql.builders.features import (
    EnrichmentJoin,
    FeatureExpr,
    FeatureParams,
    TFColumn,
    build_features_sql,
    build_term_frequencies_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


def _get_features_config(config: Any) -> Any:
    """Get the features config, supporting both attribute names.

    Real PipelineConfig uses 'feature_engineering', test mocks use 'features'.
    """
    return getattr(
        config, "feature_engineering",
        getattr(config, "features", None),
    )


def _get_feature_groups(features_config: Any) -> Any:
    """Get feature groups, supporting both real config and test mocks.

    Real FeatureEngineeringConfig has all_groups() method.
    Test mocks have a 'groups' attribute.
    """
    if hasattr(features_config, "all_groups"):
        return features_config.all_groups()
    return getattr(features_config, "groups", [])


class FeatureEngineeringStage(Stage):
    """Compute all engineered features from staged source data.

    Multi-pass feature computation:
    1. Independent features (from source columns)
    2. Dependent features (reference pass 1 features)
    3. Blocking keys and composite keys
    """

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "feature_engineering"

    @property
    def inputs(self) -> dict[str, TableRef]:
        refs = {}
        for source in self._config.sources:
            target = staged_table(self._config, source.name)
            refs[f"staged_{source.name}"] = TableRef(
                name=f"staged_{source.name}",
                fq_name=target,
            )
        return refs

    @property
    def outputs(self) -> dict[str, TableRef]:
        target = featured_table(self._config)
        return {
            "featured": TableRef(
                name="featured",
                fq_name=target,
                description="Featured table with all engineered features",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate feature engineering SQL."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        config = self._config
        target = self.outputs["featured"].fq_name
        source_tables = [
            staged_table(config, s.name) for s in config.sources
        ]

        # Collect source columns
        source_columns = set()
        for source in config.sources:
            for col in source.columns:
                source_columns.add(col.name)
        source_col_list = sorted(source_columns)

        # Resolve features
        fc = _get_features_config(config)
        all_features: list[dict[str, Any]] = []
        for group in _get_feature_groups(fc):
            for feat in group.features:
                func = FEATURE_FUNCTIONS.get(feat.function)
                if func is None:
                    logger.warning(
                        "Unknown feature function '%s' for feature '%s' — skipping. "
                        "Available: %s",
                        feat.function, feat.name,
                        sorted(FEATURE_FUNCTIONS.keys())[:10],
                    )
                    continue
                inputs = feat.inputs if isinstance(feat.inputs, list) else [feat.inputs]
                params = feat.params or {}
                try:
                    expression = func(inputs, **params)
                except Exception as exc:
                    logger.warning(
                        "Skipping feature '%s' (function=%s): %s",
                        feat.name, feat.function, exc,
                    )
                    continue
                all_features.append({
                    "name": feat.name,
                    "expression": expression,
                    "inputs": inputs,
                })

        # Auto-inject placeholder detection flag features when enabled
        ph = getattr(fc, "placeholder", None)
        if ph and getattr(ph, "enabled", False):
            # Map column roles to detection function names
            role_to_domain: dict[str, str] = {
                "phone": "is_placeholder_phone",
                "mobile_phone": "is_placeholder_phone",
                "home_phone": "is_placeholder_phone",
                "work_phone": "is_placeholder_phone",
                "email": "is_placeholder_email",
                "personal_email": "is_placeholder_email",
                "work_email": "is_placeholder_email",
                "first_name": "is_placeholder_name",
                "last_name": "is_placeholder_name",
                "middle_name": "is_placeholder_name",
                "full_name": "is_placeholder_name",
                "address_line_1": "is_placeholder_address",
                "address_line_2": "is_placeholder_address",
                "ssn": "is_placeholder_ssn",
                "tin": "is_placeholder_ssn",
            }
            domain_enabled: dict[str, bool] = {
                "is_placeholder_phone": getattr(ph, "detect_phone", True),
                "is_placeholder_email": getattr(ph, "detect_email", True),
                "is_placeholder_name": getattr(ph, "detect_name", True),
                "is_placeholder_address": getattr(ph, "detect_address", True),
                "is_placeholder_ssn": getattr(ph, "detect_ssn", True),
            }
            injected_flags: set[str] = set()
            for source in config.sources:
                for col in source.columns:
                    role = getattr(col, "role", "")
                    fn_name = role_to_domain.get(role)
                    if not fn_name or not domain_enabled.get(fn_name, True):
                        continue
                    feat_name = f"{fn_name}_{col.name}"
                    if feat_name in injected_flags:
                        continue
                    func = FEATURE_FUNCTIONS.get(fn_name)
                    if func is None:
                        continue
                    try:
                        expression = func([col.name])
                    except Exception as exc:
                        logger.warning(
                            "Skipping placeholder flag '%s': %s",
                            feat_name, exc,
                        )
                        continue
                    all_features.append({
                        "name": feat_name,
                        "expression": expression,
                        "inputs": [col.name],
                    })
                    injected_flags.add(feat_name)

        # Auto-inject compound detection features when enabled
        cd = getattr(fc, "compound_detection", None)
        if cd and getattr(cd, "enabled", False):
            name_col = getattr(cd, "name_column", "first_name")
            flag_col = getattr(cd, "flag_column", "is_compound_name")
            for fn_name, feat_name in [
                ("is_compound_name", flag_col),
                ("compound_pattern", "compound_pattern"),
            ]:
                func = FEATURE_FUNCTIONS.get(fn_name)
                if func is not None:
                    try:
                        expression = func([name_col])
                    except Exception as exc:
                        logger.warning(
                            "Skipping compound feature '%s': %s",
                            fn_name, exc,
                        )
                        continue
                    all_features.append({
                        "name": feat_name,
                        "expression": expression,
                        "inputs": [name_col],
                    })

        # Split into independent and dependent
        feature_names = {f["name"] for f in all_features}
        pass1 = []
        pass2 = []
        for f in all_features:
            if any(inp in feature_names for inp in f["inputs"]):
                pass2.append(FeatureExpr(f["name"], f["expression"]))
            else:
                pass1.append(FeatureExpr(f["name"], f["expression"]))

        # Auto-nullify blocking key inputs for placeholder prevention
        _nullify_substitutions: dict[str, str] = {}
        if (
            ph
            and getattr(ph, "enabled", False)
            and getattr(ph, "auto_nullify_blocking_inputs", True)
        ):
            role_to_nullify: dict[str, str] = {
                "phone": "nullify_placeholder_phone",
                "mobile_phone": "nullify_placeholder_phone",
                "home_phone": "nullify_placeholder_phone",
                "work_phone": "nullify_placeholder_phone",
                "email": "nullify_placeholder_email",
                "personal_email": "nullify_placeholder_email",
                "work_email": "nullify_placeholder_email",
                "first_name": "nullify_placeholder_name",
                "last_name": "nullify_placeholder_name",
                "middle_name": "nullify_placeholder_name",
                "full_name": "nullify_placeholder_name",
                "address_line_1": "nullify_placeholder_address",
                "address_line_2": "nullify_placeholder_address",
            }
            # Build a map of source column name → role
            col_roles: dict[str, str] = {}
            for source in config.sources:
                for col in source.columns:
                    role = getattr(col, "role", "")
                    if role:
                        col_roles[col.name] = role

            # For each blocking key input, if it matches a nullifiable role,
            # inject a safe version and record the substitution
            for bk in fc.blocking_keys:
                bk_inputs = bk.inputs if isinstance(bk.inputs, list) else [bk.inputs]
                for inp in bk_inputs:
                    if inp in _nullify_substitutions:
                        continue  # Already handled
                    role = col_roles.get(inp, "")
                    nullify_fn = role_to_nullify.get(role)
                    if not nullify_fn:
                        continue
                    func = FEATURE_FUNCTIONS.get(nullify_fn)
                    if func is None:
                        continue
                    safe_name = f"{inp}_safe"
                    try:
                        expression = func([inp])
                    except Exception as exc:
                        logger.warning(
                            "Skipping nullify for blocking input '%s': %s",
                            inp, exc,
                        )
                        continue
                    pass1.append(FeatureExpr(safe_name, expression))
                    _nullify_substitutions[inp] = safe_name

        # Blocking keys
        blocking_keys = []
        for bk in fc.blocking_keys:
            func = FEATURE_FUNCTIONS.get(bk.function)
            if func is None:
                continue
            inputs = bk.inputs if isinstance(bk.inputs, list) else [bk.inputs]
            # Apply placeholder nullification substitutions
            inputs = [_nullify_substitutions.get(i, i) for i in inputs]
            params = getattr(bk, "params", None) or {}
            try:
                expression = func(inputs, **params)
            except Exception as exc:
                logger.warning(
                    "Skipping blocking key '%s' (function=%s): %s",
                    bk.name, bk.function, exc,
                )
                continue
            blocking_keys.append(FeatureExpr(bk.name, expression))

        # Composite keys
        composite_keys = []
        for ck in fc.composite_keys:
            # Support both pre-computed expression and function+inputs
            ck_expr = getattr(ck, "expression", None)
            if not ck_expr:
                func = FEATURE_FUNCTIONS.get(getattr(ck, "function", ""))
                if func is None:
                    continue
                ck_inputs = ck.inputs if isinstance(ck.inputs, list) else [ck.inputs]
                try:
                    ck_expr = func(ck_inputs)
                except Exception as exc:
                    logger.warning(
                        "Skipping composite key '%s': %s", ck.name, exc,
                    )
                    continue
            composite_keys.append(FeatureExpr(ck.name, ck_expr))

        # Enrichment joins — resolve from config to SQL builder dataclasses.
        # Each enrichment join computes a key from source columns using a
        # registered feature function, then LEFT JOINs an external lookup table.
        enrichment_joins: list[EnrichmentJoin] = []
        for ej in getattr(fc, "enrichment_joins", []):
            ej_func = FEATURE_FUNCTIONS.get(ej.source_key_function)
            if ej_func is None:
                continue
            ej_inputs = (
                ej.source_key_inputs
                if isinstance(ej.source_key_inputs, list)
                else [ej.source_key_inputs]
            )
            ej_params = getattr(ej, "source_key_params", None) or {}
            try:
                key_expr = ej_func(ej_inputs, **ej_params)
            except Exception as exc:
                logger.warning(
                    "Skipping enrichment join '%s' (function=%s): %s",
                    ej.name, ej.source_key_function, exc,
                )
                continue
            enrichment_joins.append(EnrichmentJoin(
                table=ej.table,
                alias=ej.name,
                join_key_expression=key_expr,
                lookup_key=ej.lookup_key,
                columns=list(ej.columns),
                column_prefix=getattr(ej, "column_prefix", ""),
                match_flag=getattr(ej, "match_flag", ""),
                join_type=getattr(ej, "type", "LEFT"),
            ))

        # Clustering from ScaleConfig
        cluster_by = getattr(
            getattr(config, "scale", None), "featured_table_clustering", []
        ) or []

        params = FeatureParams(
            target_table=target,
            source_tables=source_tables,
            source_columns=source_col_list,
            feature_expressions=pass1,
            dependent_features=pass2,
            blocking_keys=blocking_keys,
            composite_keys=composite_keys,
            enrichment_joins=enrichment_joins,
            cluster_by=list(cluster_by),
        )

        return [build_features_sql(params)]

    def validate(self) -> list[str]:
        errors = []
        fc = _get_features_config(self._config)
        for group in _get_feature_groups(fc):
            for feat in group.features:
                if feat.function not in FEATURE_FUNCTIONS:
                    errors.append(
                        f"Unknown feature function: '{feat.function}' "
                        f"for feature '{feat.name}'"
                    )

        # Schema alignment: all sources must define the same column set
        if len(self._config.sources) >= 2:
            ref = self._config.sources[0]
            ref_names = {c.name for c in ref.columns}
            for source in self._config.sources[1:]:
                src_names = {c.name for c in source.columns}
                diff = ref_names.symmetric_difference(src_names)
                if diff:
                    errors.append(
                        f"Source '{source.name}' columns differ from "
                        f"'{ref.name}': {sorted(diff)}"
                    )

        return errors


class TermFrequencyStage(Stage):
    """Compute term frequency statistics for TF-adjusted matching."""

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "term_frequencies"

    @property
    def inputs(self) -> dict[str, TableRef]:
        target = featured_table(self._config)
        return {
            "featured": TableRef(name="featured", fq_name=target),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        from bq_entity_resolution.naming import term_frequency_table
        target = term_frequency_table(self._config)
        return {
            "tf_stats": TableRef(
                name="tf_stats",
                fq_name=target,
                description="Term frequency statistics",
            ),
        }

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate TF computation SQL, or empty if no TF-enabled comparisons."""
        logger.debug("Planning %s stage", self.__class__.__name__)
        tf_columns: list[TFColumn] = []

        for tier in self._config.enabled_tiers():
            for comp in tier.comparisons:
                if getattr(comp, "tf_enabled", False):
                    col_name = getattr(comp, "tf_column", comp.left)
                    if col_name and not any(
                        c.column_name == col_name for c in tf_columns
                    ):
                        tf_columns.append(TFColumn(col_name))

        if not tf_columns:
            return []  # No TF-enabled comparisons

        return [
            build_term_frequencies_sql(
                target_table=self.outputs["tf_stats"].fq_name,
                source_table=self.inputs["featured"].fq_name,
                tf_columns=tf_columns,
            )
        ]

"""
Cross-field validation helpers for pipeline configuration.

These validators check relationships between config sections that
Pydantic's per-model validation cannot catch.
"""

from __future__ import annotations

import difflib

from bq_entity_resolution.config.schema import PipelineConfig, SourceConfig
from bq_entity_resolution.exceptions import ConfigurationError


def _suggest_closest(name: str, valid: set[str], n: int = 3) -> str:
    """Suggest closest matches for a typo."""
    matches = difflib.get_close_matches(name, sorted(valid), n=n, cutoff=0.6)
    if matches:
        return f" Did you mean: {', '.join(repr(m) for m in matches)}?"
    return ""


def validate_comparison_columns_exist(config: PipelineConfig) -> None:
    """Ensure tier comparison columns are defined as features or source columns."""
    # Collect all known column names
    known: set[str] = set()
    for source in config.sources:
        for col in source.columns:
            known.add(col.name)
        known.update(source.passthrough_columns)

    known |= config.feature_engineering.all_feature_names()

    # Check tier references
    errors: list[str] = []
    for tier in config.enabled_tiers():
        for comp in tier.comparisons:
            if comp.left not in known:
                suggestion = _suggest_closest(comp.left, known)
                errors.append(
                    f"Tier '{tier.name}' comparison references unknown column "
                    f"'{comp.left}'.{suggestion}"
                )
            if comp.right not in known:
                suggestion = _suggest_closest(comp.right, known)
                errors.append(
                    f"Tier '{tier.name}' comparison references unknown column "
                    f"'{comp.right}'.{suggestion}"
                )
        for hn in tier.hard_negatives:
            if hn.left not in known:
                suggestion = _suggest_closest(hn.left, known)
                errors.append(
                    f"Tier '{tier.name}' hard_negative references "
                    f"unknown column '{hn.left}'.{suggestion}"
                )
        for ss in tier.soft_signals:
            if ss.left not in known:
                suggestion = _suggest_closest(ss.left, known)
                errors.append(
                    f"Tier '{tier.name}' soft_signal references "
                    f"unknown column '{ss.left}'.{suggestion}"
                )

    # Global hard negatives / soft signals
    for hn in config.global_hard_negatives:
        if hn.left not in known:
            errors.append(f"Global hard_negative references unknown column '{hn.left}'")
    for ss in config.global_soft_signals:
        if ss.left not in known:
            errors.append(f"Global soft_signal references unknown column '{ss.left}'")

    if errors:
        raise ConfigurationError(
            "Column reference validation failed:\n  " + "\n  ".join(errors)
            + "\n\n  Hint: Run 'bq-er describe --config <file>' to see available "
            "columns and features."
        )


def validate_feature_inputs_exist(config: PipelineConfig) -> None:
    """Ensure feature function inputs reference known source columns or prior features."""
    source_cols = set()
    for source in config.sources:
        for cm in source.columns:
            source_cols.add(cm.name)

    defined: set[str] = set(source_cols)

    # Add enrichment join output columns (available after feature engineering CTE)
    for ej in config.feature_engineering.enrichment_joins:
        for ej_col in ej.columns:
            defined.add(f"{ej.column_prefix}{ej_col}")
        if ej.match_flag:
            defined.add(ej.match_flag)

    errors: list[str] = []

    for group in config.feature_engineering.all_groups():
        if not group.enabled:
            continue
        for feat in group.features:
            inputs = [feat.input] if feat.input else (feat.inputs or [])
            for inp in inputs:
                if inp not in defined:
                    suggestion = _suggest_closest(inp, defined)
                    errors.append(
                        f"Feature '{feat.name}' references unknown input '{inp}'.{suggestion} "
                        f"Ensure it is defined in sources or prior features."
                    )
            defined.add(feat.name)

    if errors:
        raise ConfigurationError(
            "Feature input validation failed:\n  " + "\n  ".join(errors)
            + "\n\n  Hint: Run 'bq-er describe --config <file>' to see available "
            "columns and features."
        )


def validate_feature_dependencies(config: PipelineConfig) -> None:
    """Validate feature dependency graph: check references exist and detect cycles."""
    fe = config.feature_engineering
    if not fe:
        return

    # Collect all feature definitions: name -> depends_on
    all_features: dict[str, list[str]] = {}
    for group in fe.all_groups():
        for f in group.features:
            all_features[f.name] = list(f.depends_on) if f.depends_on else []
    for f in fe.custom_features:
        all_features[f.name] = list(f.depends_on) if f.depends_on else []

    # Check that depends_on references exist
    all_names = set(all_features.keys())
    source_cols: set[str] = set()
    for s in config.sources:
        for c in s.columns:
            source_cols.add(c.name)
    available = all_names | source_cols

    errors: list[str] = []
    for name, deps in all_features.items():
        for dep in deps:
            if dep not in available:
                errors.append(
                    f"Feature '{name}' depends_on '{dep}' which is not defined as a "
                    "feature or source column."
                )

    if errors:
        raise ConfigurationError(
            "Feature dependency validation failed:\n  " + "\n  ".join(errors)
        )

    # DFS cycle detection (white=0/unvisited, gray=1/in-progress, black=2/done)
    _white, _gray, _black = 0, 1, 2
    color: dict[str, int] = {n: _white for n in all_features}
    path: list[str] = []

    def dfs(node: str) -> None:
        color[node] = _gray
        path.append(node)
        for dep in all_features.get(node, []):
            if dep not in color:
                continue  # External dependency (source column)
            if color[dep] == _gray:
                cycle_start = path.index(dep)
                cycle = path[cycle_start:] + [dep]
                raise ConfigurationError(
                    f"Circular feature dependency detected: {' -> '.join(cycle)}"
                )
            if color[dep] == _white:
                dfs(dep)
        path.pop()
        color[node] = _black

    for name in all_features:
        if color[name] == _white:
            dfs(name)

    # Warn about deep dependencies (>1 level)
    # The feature builder only supports 2-pass CTE (independent + dependent)
    def max_depth(name: str, visited: set[str] | None = None) -> int:
        if visited is None:
            visited = set()
        if name in visited:
            return 0
        visited.add(name)
        deps = all_features.get(name, [])
        if not deps:
            return 0
        feature_deps = [d for d in deps if d in all_features]
        if not feature_deps:
            return 0
        return 1 + max(max_depth(d, visited.copy()) for d in feature_deps)

    for name in all_features:
        depth = max_depth(name)
        if depth > 1:
            import warnings

            warnings.warn(
                f"Feature '{name}' has dependency depth {depth} (max supported: 1). "
                "The feature builder uses a 2-pass CTE; features with deeper "
                "dependencies may not resolve correctly.",
                UserWarning,
                stacklevel=2,
            )
            break  # Only warn once


def validate_comparison_weights(config: PipelineConfig) -> None:
    """Validate comparison weights are positive numbers."""
    import warnings

    errors: list[str] = []
    for tier in config.enabled_tiers():
        for comp in tier.comparisons:
            if comp.weight < 0:
                errors.append(
                    f"Tier '{tier.name}' comparison {comp.left}/{comp.right} "
                    f"has negative weight {comp.weight}"
                )
            elif comp.weight == 0.0:
                warnings.warn(
                    f"Tier '{tier.name}' comparison '{comp.left}' has weight=0.0. "
                    f"This comparison will not contribute to the total score.",
                    UserWarning,
                    stacklevel=2,
                )

    if errors:
        raise ConfigurationError(
            "Comparison weight validation failed:\n  " + "\n  ".join(errors)
        )


def validate_fellegi_sunter_config(config: PipelineConfig) -> None:
    """Validate Fellegi-Sunter tier configuration completeness."""
    errors: list[str] = []
    for tier in config.enabled_tiers():
        if tier.threshold.method != "fellegi_sunter":
            continue

        # Resolve training config (tier-level overrides global)
        training = tier.training if tier.training.method != "none" else config.training

        for comp in tier.comparisons:
            if not comp.levels:
                # No levels = auto-created binary; only valid with training
                if training.method == "none":
                    errors.append(
                        f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}': "
                        f"fellegi_sunter requires either comparison levels with m/u "
                        f"or a training config (labeled/em)"
                    )
                continue

            # Verify last level is else (no method)
            if comp.levels[-1].method is not None:
                errors.append(
                    f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}': "
                    f"last level must have method=null (else/fallthrough)"
                )

            # If no training, all levels must have manual m/u
            if training.method == "none":
                for lvl in comp.levels:
                    if lvl.m is None or lvl.u is None:
                        errors.append(
                            f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}' "
                            f"level '{lvl.label}': m and u required when training.method=none"
                        )

        # Validate labeled training has table
        if training.method == "labeled" and not training.labeled_pairs_table:
            errors.append(
                f"Tier '{tier.name}': labeled training requires labeled_pairs_table"
            )

    if errors:
        raise ConfigurationError(
            "Fellegi-Sunter config validation failed:\n  " + "\n  ".join(errors)
        )


def validate_tf_columns_exist(config: PipelineConfig) -> None:
    """Ensure TF adjustment columns reference known features or source columns."""
    known: set[str] = set()
    for source in config.sources:
        for cm in source.columns:
            known.add(cm.name)
    known |= config.feature_engineering.all_feature_names()

    errors: list[str] = []
    for tier in config.enabled_tiers():
        for comp in tier.comparisons:
            if comp.tf_adjustment and comp.tf_adjustment.enabled:
                tf_col = comp.tf_adjustment.tf_adjustment_column or comp.left
                if tf_col not in known:
                    suggestion = _suggest_closest(tf_col, known)
                    errors.append(
                        f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}': "
                        f"tf_adjustment_column '{tf_col}' not found in features or "
                        f"source columns.{suggestion}"
                    )

    if errors:
        raise ConfigurationError(
            "Term frequency column validation failed:\n  " + "\n  ".join(errors)
        )


def validate_source_schema_alignment(config: PipelineConfig) -> None:
    """Ensure all sources define the same feature column names for safe UNION ALL.

    When multiple sources are UNION-ALLed during feature engineering,
    they must share the same column set.  This validator catches schema
    mismatches at config load time rather than at BigQuery runtime.

    Note: ``unique_key`` and ``updated_at`` columns are excluded from
    this check because they are per-source system columns mapped to
    ``entity_uid`` and ``source_updated_at`` during staging.
    """
    if len(config.sources) < 2:
        return

    def _feature_column_names(source: SourceConfig) -> set[str]:
        """Column names excluding system columns (unique_key, updated_at)."""
        system_cols = {source.unique_key, source.updated_at}
        return {c.name for c in source.columns if c.name not in system_cols}

    reference = config.sources[0]
    ref_names = _feature_column_names(reference)
    errors: list[str] = []

    for source in config.sources[1:]:
        src_names = _feature_column_names(source)
        missing = ref_names - src_names
        extra = src_names - ref_names
        if missing:
            errors.append(
                f"Source '{source.name}' missing columns present in "
                f"'{reference.name}': {sorted(missing)}"
            )
        if extra:
            errors.append(
                f"Source '{source.name}' has extra columns not in "
                f"'{reference.name}': {sorted(extra)}"
            )

    if errors:
        raise ConfigurationError(
            "Source schema alignment failed:\n  " + "\n  ".join(errors)
        )


def validate_comparison_methods_registered(config: PipelineConfig) -> None:
    """Validate that all comparison/hard_negative/soft_signal method names are registered.

    Catches typos like ``method: "levenstein"`` at config load time
    instead of at SQL generation time.
    """
    from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS, load_feature_plugins
    from bq_entity_resolution.matching.comparisons import (
        COMPARISON_FUNCTIONS,
        load_comparison_plugins,
    )

    # Ensure external plugins are discovered before validation
    load_feature_plugins()
    load_comparison_plugins()

    known_comparison = set(COMPARISON_FUNCTIONS.keys())
    known_feature = set(FEATURE_FUNCTIONS.keys())
    errors: list[str] = []

    # Feature function names
    for group in config.feature_engineering.all_groups():
        if not group.enabled:
            continue
        for feat in group.features:
            if feat.sql:
                continue  # raw SQL override — no function to validate
            if feat.function not in known_feature:
                suggestion = _suggest_closest(feat.function, known_feature)
                errors.append(
                    f"Feature '{feat.name}' references unknown function "
                    f"'{feat.function}'.{suggestion}"
                )

    for feat in config.feature_engineering.custom_features:
        if feat.sql:
            continue
        if feat.function not in known_feature:
            suggestion = _suggest_closest(feat.function, known_feature)
            errors.append(
                f"Custom feature '{feat.name}' references unknown function "
                f"'{feat.function}'.{suggestion}"
            )

    # Blocking key function names
    for bk in config.feature_engineering.blocking_keys:
        if bk.function not in known_feature:
            suggestion = _suggest_closest(bk.function, known_feature)
            errors.append(
                f"Blocking key '{bk.name}' references unknown function "
                f"'{bk.function}'.{suggestion}"
            )

    # Comparison method names
    for tier in config.enabled_tiers():
        for comp in tier.comparisons:
            if comp.method not in known_comparison:
                suggestion = _suggest_closest(comp.method, known_comparison)
                errors.append(
                    f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}' "
                    f"references unknown method '{comp.method}'.{suggestion}"
                )
            # Multi-level comparisons
            if comp.levels:
                for lvl in comp.levels:
                    if lvl.method and lvl.method not in known_comparison:
                        suggestion = _suggest_closest(lvl.method, known_comparison)
                        errors.append(
                            f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}' "
                            f"level '{lvl.label}' references unknown method "
                            f"'{lvl.method}'.{suggestion}"
                        )

        # Hard negative methods
        for hn in tier.hard_negatives:
            if hn.sql:
                continue  # raw SQL override
            if hn.method not in known_comparison:
                suggestion = _suggest_closest(hn.method, known_comparison)
                errors.append(
                    f"Tier '{tier.name}' hard_negative references unknown method "
                    f"'{hn.method}'.{suggestion}"
                )

        # Soft signal methods
        for ss in tier.soft_signals:
            if ss.sql:
                continue  # raw SQL override
            if ss.method not in known_comparison:
                suggestion = _suggest_closest(ss.method, known_comparison)
                errors.append(
                    f"Tier '{tier.name}' soft_signal references unknown method "
                    f"'{ss.method}'.{suggestion}"
                )

    if errors:
        raise ConfigurationError(
            "Method/function registry validation failed:\n  " + "\n  ".join(errors)
            + "\n\n  Hint: List available functions with: "
            "from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS; "
            "print(sorted(FEATURE_FUNCTIONS))"
        )


def validate_entity_type_conditions(config: PipelineConfig) -> None:
    """Validate that entity_type_condition values reference known types.

    Checks all hard negatives, hard positives, and soft signals
    (global and per-tier) for unrecognized entity type conditions.
    """
    from bq_entity_resolution.config.entity_types import ENTITY_TYPE_TEMPLATES

    valid_conditions: set[str] = set()
    for name in ENTITY_TYPE_TEMPLATES:
        valid_conditions.add(name.lower())
    # Legacy aliases for backward compatibility
    valid_conditions.update({
        "personal", "person", "business", "organization", "org",
    })

    errors: list[str] = []

    def _check(signal_type: str, context: str, condition: str | None) -> None:
        if condition and condition.lower() not in valid_conditions:
            suggestion = _suggest_closest(condition.lower(), valid_conditions)
            errors.append(
                f"{context} {signal_type} has unknown entity_type_condition "
                f"'{condition}'.{suggestion}"
            )

    # Global signals
    for hn in config.global_hard_negatives:
        _check("hard_negative", "Global", hn.entity_type_condition)
    for hp in config.global_hard_positives:
        _check("hard_positive", "Global", hp.entity_type_condition)
    for ss in config.global_soft_signals:
        _check("soft_signal", "Global", ss.entity_type_condition)

    # Per-tier signals
    for tier in config.enabled_tiers():
        ctx = f"Tier '{tier.name}'"
        for hn in tier.hard_negatives:
            _check("hard_negative", ctx, hn.entity_type_condition)
        for hp in tier.hard_positives:
            _check("hard_positive", ctx, hp.entity_type_condition)
        for ss in tier.soft_signals:
            _check("soft_signal", ctx, ss.entity_type_condition)

    if errors:
        raise ConfigurationError(
            "Entity type condition validation failed:\n  " + "\n  ".join(errors)
        )


def validate_entity_type_roles(config: PipelineConfig) -> None:
    """Warn when source columns don't include required roles for entity type.

    This is a WARNING-level check (not an error). Users may intentionally
    omit some roles for their use case.
    """
    import logging

    from bq_entity_resolution.config.entity_types import resolve_hierarchy

    logger = logging.getLogger(__name__)

    for source in config.sources:
        if not source.entity_type:
            continue
        try:
            template = resolve_hierarchy(source.entity_type)
        except KeyError:
            logger.warning(
                "Source '%s' declares unknown entity_type='%s'. "
                "Available types: use list_entity_types() to see options.",
                source.name, source.entity_type,
            )
            continue

        source_roles = {col.role for col in source.columns if col.role}
        missing_required = template.required_roles - source_roles
        if missing_required:
            logger.warning(
                "Source '%s' (entity_type='%s') is missing required roles: %s",
                source.name, source.entity_type, sorted(missing_required),
            )


def validate_tier_comparisons(config: PipelineConfig) -> None:
    """Ensure tiers have comparisons and thresholds are reachable.

    Catches two common misconfigurations:
    1. A tier with an empty comparisons list (SQL compilation error)
    2. A threshold higher than the maximum possible score (no matches)
    """
    errors: list[str] = []
    for tier in config.enabled_tiers():
        if not tier.comparisons:
            errors.append(
                f"Tier '{tier.name}' has no comparisons. "
                f"Add at least one comparison or remove the tier."
            )
            continue

        total_weight = sum(c.weight for c in tier.comparisons)
        if total_weight <= 0:
            errors.append(
                f"Tier '{tier.name}' has total comparison weight "
                f"{total_weight}. At least one comparison must have "
                f"weight > 0."
            )
            continue

        # Check if threshold is reachable
        if tier.threshold.method == "sum":
            min_score = tier.threshold.min_score
            if min_score > total_weight:
                errors.append(
                    f"Tier '{tier.name}' threshold ({min_score}) "
                    f"exceeds maximum possible score ({total_weight}). "
                    f"No pairs can match. Lower the threshold or "
                    f"increase comparison weights."
                )

    if errors:
        raise ConfigurationError(
            "Tier comparison validation failed:\n  "
            + "\n  ".join(errors)
            + "\n\n  Hint: Ensure min_score <= sum of comparison weights. "
            "See docs/TUNING.md for calibration guidance."
        )


def validate_enrichment_joins(config: PipelineConfig) -> None:
    """Validate enrichment join configurations.

    Checks that:
    1. source_key_function references a registered feature function.
    2. source_key_inputs reference known source columns or features.
    3. No duplicate enrichment join names.
    """
    joins = config.feature_engineering.enrichment_joins
    if not joins:
        return

    from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS, load_feature_plugins
    load_feature_plugins()

    known_features = set(FEATURE_FUNCTIONS.keys())
    known_cols: set[str] = set()
    for source in config.sources:
        for col in source.columns:
            known_cols.add(col.name)
    known_cols |= config.feature_engineering.all_feature_names()

    errors: list[str] = []
    seen_names: set[str] = set()

    for join in joins:
        # Duplicate name check
        if join.name in seen_names:
            errors.append(f"Duplicate enrichment join name: '{join.name}'")
        seen_names.add(join.name)

        # Validate source_key_function
        if join.source_key_function not in known_features:
            suggestion = _suggest_closest(join.source_key_function, known_features)
            errors.append(
                f"Enrichment join '{join.name}' references unknown "
                f"source_key_function '{join.source_key_function}'.{suggestion}"
            )

        # Validate source_key_inputs
        for inp in join.source_key_inputs:
            if inp not in known_cols:
                suggestion = _suggest_closest(inp, known_cols)
                errors.append(
                    f"Enrichment join '{join.name}' references unknown "
                    f"source_key_input '{inp}'.{suggestion}"
                )

    if errors:
        raise ConfigurationError(
            "Enrichment join validation failed:\n  " + "\n  ".join(errors)
        )


def validate_udf_usage(config: PipelineConfig) -> None:
    """Reject UDF-requiring methods when execution.allow_udfs is False.

    Some BigQuery environments (shared tenants, CMEK-restricted projects,
    org policies) prohibit JavaScript UDFs.  When ``allow_udfs: false``
    is set, this validator checks all comparison methods and feature
    functions for UDF dependencies and raises a clear error with
    native alternatives.
    """
    execution = getattr(config, "execution", None)
    if execution is None or getattr(execution, "allow_udfs", True):
        return

    from bq_entity_resolution.features.registry import UDF_FEATURE_FUNCTIONS
    from bq_entity_resolution.matching.comparisons import UDF_COMPARISON_METHODS

    errors: list[str] = []

    # Check tier comparisons (pool refs are already resolved by model_validator)
    for tier in config.enabled_tiers():
        for comp in tier.comparisons:
            if comp.method in UDF_COMPARISON_METHODS:
                errors.append(
                    f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}' "
                    f"uses UDF method '{comp.method}' but allow_udfs=false. "
                    f"Use a native alternative (e.g. levenshtein_normalized)."
                )
            # Multi-level comparisons
            if comp.levels:
                for lvl in comp.levels:
                    if lvl.method and lvl.method in UDF_COMPARISON_METHODS:
                        errors.append(
                            f"Tier '{tier.name}' comparison '{comp.left}/{comp.right}' "
                            f"level '{lvl.label}' uses UDF method '{lvl.method}' "
                            f"but allow_udfs=false."
                        )

    # Check feature functions
    for group in config.feature_engineering.all_groups():
        if not group.enabled:
            continue
        for feat in group.features:
            if feat.function in UDF_FEATURE_FUNCTIONS:
                errors.append(
                    f"Feature '{feat.name}' uses UDF function '{feat.function}' "
                    f"but allow_udfs=false. Use a native alternative "
                    f"(e.g. soundex)."
                )

    for feat in config.feature_engineering.custom_features:
        if feat.function in UDF_FEATURE_FUNCTIONS:
            errors.append(
                f"Custom feature '{feat.name}' uses UDF function "
                f"'{feat.function}' but allow_udfs=false."
            )

    if errors:
        raise ConfigurationError(
            "UDF usage validation failed (allow_udfs=false):\n  "
            + "\n  ".join(errors)
        )


def validate_composite_key_inputs(config: PipelineConfig) -> None:
    """Validate that composite key inputs reference known features or source columns."""
    if not config.feature_engineering.composite_keys:
        return

    known: set[str] = set()
    for source in config.sources:
        for col in source.columns:
            known.add(col.name)
    known |= config.feature_engineering.all_feature_names()

    errors: list[str] = []
    for ck in config.feature_engineering.composite_keys:
        for inp in ck.inputs:
            if inp not in known:
                suggestion = _suggest_closest(inp, known)
                errors.append(
                    f"Composite key '{ck.name}' references unknown input "
                    f"'{inp}'.{suggestion}"
                )

    if errors:
        raise ConfigurationError(
            "Composite key input validation failed:\n  " + "\n  ".join(errors)
        )


def validate_blocking_key_inputs(config: PipelineConfig) -> None:
    """Validate that blocking key inputs reference known features or source columns."""
    if not config.feature_engineering.blocking_keys:
        return

    known: set[str] = set()
    for source in config.sources:
        for col in source.columns:
            known.add(col.name)
    # Include features defined in all groups (blocking keys can reference them)
    for group in config.feature_engineering.all_groups():
        for feat in group.features:
            known.add(feat.name)
    for feat in config.feature_engineering.custom_features:
        known.add(feat.name)

    errors: list[str] = []
    for bk in config.feature_engineering.blocking_keys:
        for inp in bk.inputs:
            if inp not in known:
                suggestion = _suggest_closest(inp, known)
                errors.append(
                    f"Blocking key '{bk.name}' references unknown input "
                    f"'{inp}'.{suggestion}"
                )

    if errors:
        raise ConfigurationError(
            "Blocking key input validation failed:\n  " + "\n  ".join(errors)
            + "\n\n  Hint: Blocking key inputs must be defined as features in "
            "feature_engineering or as source columns."
        )


def validate_entity_type_column(config: PipelineConfig) -> None:
    """Validate that entity_type_column references a known feature or source column."""
    col = config.feature_engineering.entity_type_column
    if not col:
        return

    known: set[str] = set()
    for source in config.sources:
        for c in source.columns:
            known.add(c.name)
    known |= config.feature_engineering.all_feature_names()

    if col not in known:
        suggestion = _suggest_closest(col, known)
        raise ConfigurationError(
            f"entity_type_column '{col}' is not a known feature or source "
            f"column.{suggestion}"
        )


def validate_score_banding(config: PipelineConfig) -> None:
    """Validate score banding configuration for overlap and coverage issues."""
    errors: list[str] = []

    for tier in config.enabled_tiers():
        banding = tier.score_banding
        if not banding or not banding.enabled or not banding.bands:
            continue

        bands = sorted(banding.bands, key=lambda b: b.min_score)

        # Check for overlapping bands
        for i in range(len(bands) - 1):
            current = bands[i]
            next_band = bands[i + 1]
            if current.max_score > next_band.min_score:
                errors.append(
                    f"Tier '{tier.name}' score banding: band '{current.name}' "
                    f"(max={current.max_score}) overlaps with "
                    f"'{next_band.name}' (min={next_band.min_score})"
                )

        # Check for gaps between bands
        for i in range(len(bands) - 1):
            current = bands[i]
            next_band = bands[i + 1]
            if current.max_score < next_band.min_score:
                errors.append(
                    f"Tier '{tier.name}' score banding: gap between band "
                    f"'{current.name}' (max={current.max_score}) and "
                    f"'{next_band.name}' (min={next_band.min_score})"
                )

    if errors:
        raise ConfigurationError(
            "Score banding validation failed:\n  " + "\n  ".join(errors)
        )


def validate_skip_stages(config: PipelineConfig) -> None:
    """Validate that skip_stages names reference known pipeline stages.

    Catches typos like ``skip_stages: [cluter_quality]`` at config load time
    instead of silently ignoring the misspelled stage.
    """
    skip = config.execution.skip_stages
    if not skip:
        return

    # Known built-in stage names (from stages/ module)
    known_stages = {
        "staging", "feature_engineering", "create_udfs",
        "blocking", "matching", "match_accumulation",
        "clustering", "canonical_index", "gold_output",
        "cluster_quality", "active_learning",
        "watermark_read", "watermark_advance",
        "embeddings", "embeddings_lsh",
        "em_estimation", "init_matches",
        "bqml_training", "bqml_prediction",
        "bqml_threshold_tuning", "bqml_match_integration",
        "term_frequencies",
    }
    # Also include tier-specific stage names
    for tier in config.matching_tiers:
        known_stages.add(f"blocking_{tier.name}")
        known_stages.add(f"matching_{tier.name}")
        known_stages.add(f"accumulation_{tier.name}")

    errors: list[str] = []
    for stage_name in skip:
        if stage_name not in known_stages:
            suggestion = _suggest_closest(stage_name, known_stages)
            errors.append(
                f"skip_stages references unknown stage '{stage_name}'.{suggestion}"
            )

    if errors:
        raise ConfigurationError(
            "skip_stages validation failed:\n  " + "\n  ".join(errors)
        )


def validate_incremental_cursor_columns(config: PipelineConfig) -> None:
    """Validate that cursor_columns reference columns present in all sources.

    Catches misconfigurations where the incremental cursor references
    a column that doesn't exist in the source table.

    Note: "updated_at" is always valid as a cursor column because every
    source declares an ``updated_at`` column that gets staged as
    ``source_updated_at``. The pipeline watermark system handles
    this mapping internally.
    """
    inc = config.incremental
    if not inc or not inc.enabled:
        return

    # Cursor columns must exist in every source
    errors: list[str] = []
    for source in config.sources:
        source_cols = {col.name for col in source.columns}
        # System columns always available: updated_at (staged as source_updated_at),
        # unique_key (staged as entity_uid)
        source_cols.add(source.updated_at)
        source_cols.add(source.unique_key)
        # "updated_at" is always valid — every source has an updated_at column
        source_cols.add("updated_at")
        for cursor_col in inc.cursor_columns:
            if cursor_col not in source_cols:
                suggestion = _suggest_closest(cursor_col, source_cols)
                errors.append(
                    f"Incremental cursor_column '{cursor_col}' not found in "
                    f"source '{source.name}'.{suggestion}"
                )

    # Partition cursor columns
    for pc in inc.partition_cursors:
        for source in config.sources:
            source_cols = {col.name for col in source.columns}
            source_cols.add(source.updated_at)
            source_cols.add(source.unique_key)
            source_cols.add("updated_at")
            if pc.column not in source_cols:
                suggestion = _suggest_closest(pc.column, source_cols)
                errors.append(
                    f"Partition cursor column '{pc.column}' not found in "
                    f"source '{source.name}'.{suggestion}"
                )

    if errors:
        raise ConfigurationError(
            "Incremental cursor validation failed:\n  " + "\n  ".join(errors)
        )


def validate_embedding_source_columns(config: PipelineConfig) -> None:
    """Validate that embedding source_columns reference known columns.

    When embeddings are enabled, source_columns must reference either
    source columns or engineered features.
    """
    emb = config.embeddings
    if not emb.enabled or not emb.source_columns:
        return

    known: set[str] = set()
    for source in config.sources:
        for cm in source.columns:
            known.add(cm.name)
    known |= config.feature_engineering.all_feature_names()

    errors: list[str] = []
    for emb_col in emb.source_columns:
        if emb_col not in known:
            suggestion = _suggest_closest(emb_col, known)
            errors.append(
                f"Embedding source_column '{emb_col}' not found in features "
                f"or source columns.{suggestion}"
            )

    if errors:
        raise ConfigurationError(
            "Embedding source_columns validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_hash_cursor_column(config: PipelineConfig) -> None:
    """Validate that hash_cursor.column references a known source column."""
    inc = config.incremental
    if not inc or not inc.enabled or not inc.hash_cursor:
        return

    known: set[str] = set()
    for source in config.sources:
        for cm in source.columns:
            known.add(cm.name)
        known.add(source.unique_key)
        known.add(source.updated_at)
    # entity_uid is the default and always valid after staging
    known.add("entity_uid")

    hc_col = inc.hash_cursor.column
    if hc_col not in known:
        suggestion = _suggest_closest(hc_col, known)
        raise ConfigurationError(
            f"Hash cursor column '{hc_col}' not found in source columns.{suggestion}"
        )


def validate_hard_positive_target_band(config: PipelineConfig) -> None:
    """Validate that hard_positive target_band references a defined score band.

    When action='elevate_band', the target_band must match a band name
    in the tier's score_banding configuration.
    """
    errors: list[str] = []
    for tier in config.enabled_tiers():
        band_names: set[str] = set()
        if tier.score_banding and tier.score_banding.enabled:
            band_names = {b.name for b in tier.score_banding.bands}

        for hp in tier.hard_positives:
            if hp.action == "elevate_band" and hp.target_band:
                if not band_names:
                    errors.append(
                        f"Tier '{tier.name}' hard_positive with "
                        f"action='elevate_band' but score_banding is not enabled."
                    )
                elif hp.target_band not in band_names:
                    suggestion = _suggest_closest(hp.target_band, band_names)
                    errors.append(
                        f"Tier '{tier.name}' hard_positive target_band "
                        f"'{hp.target_band}' not in score bands: "
                        f"{sorted(band_names)}.{suggestion}"
                    )

        # Also check global hard positives against each tier
        for hp in config.global_hard_positives:
            if hp.action == "elevate_band" and hp.target_band:
                if tier.score_banding and tier.score_banding.enabled:
                    if hp.target_band not in band_names:
                        errors.append(
                            f"Global hard_positive target_band "
                            f"'{hp.target_band}' not in tier '{tier.name}' "
                            f"score bands: {sorted(band_names)}."
                        )

    if errors:
        raise ConfigurationError(
            "Hard positive target_band validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_score_band_name_uniqueness(config: PipelineConfig) -> None:
    """Validate that score band names are unique within each tier."""
    errors: list[str] = []
    for tier in config.enabled_tiers():
        banding = tier.score_banding
        if not banding or not banding.enabled or not banding.bands:
            continue

        seen: set[str] = set()
        for band in banding.bands:
            if band.name in seen:
                errors.append(
                    f"Tier '{tier.name}' has duplicate score band "
                    f"name '{band.name}'."
                )
            seen.add(band.name)

    if errors:
        raise ConfigurationError(
            "Score band name uniqueness validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_clustering_method(config: PipelineConfig) -> None:
    """Validate that the clustering method is supported.

    Supported methods: connected_components, star, best_match.
    """
    valid_methods = {"connected_components", "star", "best_match"}
    method = config.reconciliation.clustering.method
    if method not in valid_methods:
        suggestion = _suggest_closest(method, valid_methods)
        raise ConfigurationError(
            f"Unknown clustering method '{method}'.{suggestion} "
            f"Supported: {sorted(valid_methods)}"
        )


def validate_golden_record_columns(config: PipelineConfig) -> None:
    """Validate that golden record output columns reference known columns."""
    output = config.reconciliation.output
    if not output.cluster_columns:
        return

    known: set[str] = set()
    for source in config.sources:
        for cm in source.columns:
            known.add(cm.name)
        known.update(source.passthrough_columns)
    known |= config.feature_engineering.all_feature_names()
    # System columns
    known.update({"entity_uid", "cluster_id", "source_name", "source_updated_at"})

    errors: list[str] = []
    for out_col in output.cluster_columns:
        if out_col not in known:
            suggestion = _suggest_closest(out_col, known)
            errors.append(
                f"Output cluster_column '{out_col}' not found in features "
                f"or source columns.{suggestion}"
            )

    if errors:
        raise ConfigurationError(
            "Golden record output column validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_canonical_field_strategies(config: PipelineConfig) -> None:
    """Validate that canonical field_strategies reference known columns."""
    strategies = config.reconciliation.canonical_selection.field_strategies
    if not strategies:
        return

    known: set[str] = set()
    for source in config.sources:
        for col in source.columns:
            known.add(col.name)
        known.update(source.passthrough_columns)
    known |= config.feature_engineering.all_feature_names()

    errors: list[str] = []
    for fs in strategies:
        if fs.column not in known:
            suggestion = _suggest_closest(fs.column, known)
            errors.append(
                f"Canonical field_strategy column '{fs.column}' not found "
                f"in features or source columns.{suggestion}"
            )

    if errors:
        raise ConfigurationError(
            "Canonical field strategy validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_active_learning_config(config: PipelineConfig) -> None:
    """Validate active learning configuration completeness.

    When active learning is enabled for a tier, the review_queue_table
    must be specified as a fully-qualified BigQuery table reference.
    """
    errors: list[str] = []
    for tier in config.enabled_tiers():
        al = tier.active_learning
        if not al.enabled:
            continue

        if not al.review_queue_table:
            errors.append(
                f"Tier '{tier.name}' has active_learning enabled but "
                f"review_queue_table is not set."
            )

        if al.label_feedback.enabled and not al.label_feedback.feedback_table:
            errors.append(
                f"Tier '{tier.name}' has label_feedback enabled but "
                f"feedback_table is not set."
            )

    if errors:
        raise ConfigurationError(
            "Active learning config validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_enrichment_join_table_format(config: PipelineConfig) -> None:
    """Validate that enrichment join table references are fully-qualified.

    Enrichment join tables must be in project.dataset.table format.
    """
    from bq_entity_resolution.sql.utils import _VALID_TABLE_REF

    joins = config.feature_engineering.enrichment_joins
    if not joins:
        return

    errors: list[str] = []
    for join in joins:
        clean = join.table.strip("`")
        if not _VALID_TABLE_REF.match(clean):
            errors.append(
                f"Enrichment join '{join.name}' table '{join.table}' is not "
                f"a valid fully-qualified reference (expected project.dataset.table)."
            )

    if errors:
        raise ConfigurationError(
            "Enrichment join table format validation failed:\n  "
            + "\n  ".join(errors)
        )


def validate_source_priority(config: PipelineConfig) -> None:
    """Validate that source_priority entries reference defined source names.

    Checks both top-level ``canonical_selection.source_priority`` and
    per-field ``field_strategies[].source_priority`` lists against the
    set of source names declared in ``config.sources``.
    """
    source_names = {s.name for s in config.sources}
    if not source_names:
        return

    errors: list[str] = []
    cs = config.reconciliation.canonical_selection

    # Top-level source_priority
    for sp in cs.source_priority:
        if sp not in source_names:
            suggestion = _suggest_closest(sp, source_names)
            errors.append(
                f"canonical_selection.source_priority references unknown source "
                f"'{sp}'.{suggestion}"
            )

    # Per-field source_priority
    for fs in cs.field_strategies:
        for sp in fs.source_priority:
            if sp not in source_names:
                suggestion = _suggest_closest(sp, source_names)
                errors.append(
                    f"canonical_selection.field_strategies['{fs.column}'].source_priority "
                    f"references unknown source '{sp}'.{suggestion}"
                )

    if errors:
        raise ConfigurationError(
            "Source priority validation failed:\n  " + "\n  ".join(errors)
            + f"\n\n  Available sources: {sorted(source_names)}"
        )


def validate_name_collisions(config: PipelineConfig) -> None:
    """Check that feature names and blocking key names don't collide."""
    fe = config.feature_engineering
    if not fe:
        return

    feature_names: set[str] = set()
    for group in fe.all_groups():
        for f in group.features:
            feature_names.add(f.name)
    for f in fe.custom_features:
        feature_names.add(f.name)

    bk_names = {bk.name for bk in (fe.blocking_keys or [])}
    collisions = feature_names & bk_names
    if collisions:
        raise ConfigurationError(
            f"Feature names collide with blocking key names: {sorted(collisions)}. "
            "Rename the blocking keys to avoid ambiguity (e.g., prefix with 'bk_')."
        )


def validate_incremental_config(config: PipelineConfig) -> None:
    """Validate incremental processing configuration consistency."""
    inc = config.incremental
    if not inc or not inc.enabled:
        return

    if not inc.cursor_columns:
        raise ConfigurationError(
            "incremental.enabled=true but cursor_columns is empty. "
            "At least one cursor column is required for watermark tracking."
        )

    for source in config.sources:
        if not source.updated_at:
            raise ConfigurationError(
                f"incremental.enabled=true but source '{source.name}' has no "
                "updated_at column. This column is required for incremental processing."
            )


def validate_clustering_compatibility(config: PipelineConfig) -> None:
    """Warn about clustering method / incremental mode incompatibilities."""
    inc = config.incremental
    clustering = config.reconciliation.clustering
    if not inc or not inc.enabled:
        return
    if clustering.method in ("star", "best_match"):
        import warnings

        warnings.warn(
            f"clustering.method='{clustering.method}' does not support "
            "incremental mode. Only 'connected_components' supports incremental "
            "cluster merging across batches. Consider switching to "
            "'connected_components' or disabling incremental mode.",
            UserWarning,
            stacklevel=2,
        )


def validate_threshold_consistency(config: PipelineConfig) -> None:
    """Warn about threshold configuration conflicts."""
    import warnings

    for tier in config.enabled_tiers():
        if tier.threshold.method == "sum" and tier.threshold.match_threshold is not None:
            warnings.warn(
                f"Tier '{tier.name}': match_threshold is set but method='sum'. "
                "match_threshold is only used with method='fellegi_sunter'. "
                "For sum scoring, use min_score instead.",
                UserWarning,
                stacklevel=2,
            )


def validate_source_names_unique(config: PipelineConfig) -> None:
    """Validate that source names are unique."""
    seen: dict[str, int] = {}
    for src in config.sources:
        seen[src.name] = seen.get(src.name, 0) + 1
    dupes = [name for name, count in seen.items() if count > 1]
    if dupes:
        raise ConfigurationError(
            f"Duplicate source names: {dupes}. "
            f"Each source must have a unique name to avoid table name collisions."
        )


def validate_matching_tiers_not_empty(config: PipelineConfig) -> None:
    """Validate that at least one matching tier is defined."""
    if not config.matching_tiers:
        raise ConfigurationError(
            "No matching tiers defined. At least one matching tier is required.\n\n"
            "  Hint: Add a 'matching_tiers' section to your config YAML. "
            "Run 'bq-er init --project <project>' to generate a starter config."
        )


def validate_partition_cursor_equality_value(config: PipelineConfig) -> None:
    """Validate that partition cursors with equality strategy have a value set."""
    if not config.incremental.enabled:
        return
    errors: list[str] = []
    for pc in config.incremental.partition_cursors:
        if pc.strategy == "equality" and pc.value is None:
            errors.append(
                f"Partition cursor '{pc.column}' uses strategy='equality' but has no value set. "
                f"Set 'value' to the literal value for equality filtering."
            )
    if errors:
        raise ConfigurationError(
            "Partition cursor validation failed:\n  " + "\n  ".join(errors)
        )


def validate_blocking_key_functions_registered(config: PipelineConfig) -> None:
    """Validate that blocking key function names are registered feature functions."""
    from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

    errors: list[str] = []
    for bk in config.feature_engineering.blocking_keys:
        if bk.function not in FEATURE_FUNCTIONS:
            suggestion = _suggest_closest(bk.function, set(FEATURE_FUNCTIONS.keys()))
            errors.append(
                f"Blocking key '{bk.name}' uses unregistered function "
                f"'{bk.function}'.{suggestion}"
            )
    if errors:
        raise ConfigurationError(
            "Blocking key function validation failed:\n  " + "\n  ".join(errors)
            + "\n\n  Hint: Check feature function names in the registry. "
            "Available functions can be found with: "
            "from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS"
        )


def validate_feature_functions_registered(config: PipelineConfig) -> None:
    """Validate that feature function names are registered."""
    from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

    errors: list[str] = []
    for group in config.feature_engineering.all_groups():
        for feat in group.features:
            if feat.function not in FEATURE_FUNCTIONS:
                suggestion = _suggest_closest(feat.function, set(FEATURE_FUNCTIONS.keys()))
                errors.append(
                    f"Feature '{feat.name}' uses unregistered function "
                    f"'{feat.function}'.{suggestion}"
                )
    for feat in config.feature_engineering.custom_features:
        if feat.function not in FEATURE_FUNCTIONS:
            suggestion = _suggest_closest(feat.function, set(FEATURE_FUNCTIONS.keys()))
            errors.append(
                f"Custom feature '{feat.name}' uses unregistered function "
                f"'{feat.function}'.{suggestion}"
            )
    if errors:
        raise ConfigurationError(
            "Feature function validation failed:\n  " + "\n  ".join(errors)
        )


def validate_embeddings_config(config: PipelineConfig) -> None:
    """Validate that embeddings have source_columns when enabled.

    When ``embeddings.enabled=True`` the pipeline needs at least one
    ``source_columns`` entry to know which columns to embed.
    """
    emb = config.embeddings
    if emb.enabled and not emb.source_columns:
        raise ConfigurationError(
            "Embeddings are enabled but 'embeddings.source_columns' is empty. "
            "Specify at least one source column to embed, e.g.:\n\n"
            "  embeddings:\n"
            "    enabled: true\n"
            "    source_columns: [first_name_clean, last_name_clean]\n\n"
            "Hint: source_columns should reference engineered features or "
            "raw source columns."
        )


def validate_field_merge_source_priority(config: PipelineConfig) -> None:
    """Warn when field_merge strategies use source_priority with an empty list.

    If ``reconciliation.canonical_selection.method='field_merge'`` and any
    ``field_merge_strategies`` entry has ``strategy='source_priority'``
    but an empty ``source_priority`` list, the merge cannot determine
    which source to prefer.
    """
    import warnings

    cs = config.reconciliation.canonical_selection
    if cs.method != "field_merge":
        return

    for fs in cs.field_strategies:
        if fs.strategy == "source_priority" and not fs.source_priority:
            warnings.warn(
                f"Field merge strategy for column '{fs.column}' uses "
                f"strategy='source_priority' but has an empty "
                f"'source_priority' list. The strategy will have no "
                f"effect without specifying source priority order.",
                UserWarning,
                stacklevel=2,
            )


def validate_full(config: PipelineConfig) -> None:
    """Run all cross-field validations."""
    validate_source_names_unique(config)
    validate_source_schema_alignment(config)
    validate_feature_inputs_exist(config)
    validate_feature_dependencies(config)
    validate_name_collisions(config)
    validate_comparison_columns_exist(config)
    validate_comparison_weights(config)
    validate_tier_comparisons(config)
    validate_fellegi_sunter_config(config)
    validate_tf_columns_exist(config)
    validate_blocking_key_inputs(config)
    validate_composite_key_inputs(config)
    validate_comparison_methods_registered(config)
    validate_enrichment_joins(config)
    validate_enrichment_join_table_format(config)
    validate_udf_usage(config)
    validate_entity_type_column(config)
    validate_entity_type_conditions(config)
    validate_entity_type_roles(config)
    validate_score_banding(config)
    validate_score_band_name_uniqueness(config)
    validate_hard_positive_target_band(config)
    validate_clustering_method(config)
    validate_golden_record_columns(config)
    validate_canonical_field_strategies(config)
    validate_source_priority(config)
    validate_active_learning_config(config)
    validate_embedding_source_columns(config)
    validate_hash_cursor_column(config)
    validate_skip_stages(config)
    validate_incremental_cursor_columns(config)
    validate_incremental_config(config)
    validate_clustering_compatibility(config)
    validate_threshold_consistency(config)
    validate_matching_tiers_not_empty(config)
    validate_partition_cursor_equality_value(config)
    validate_blocking_key_functions_registered(config)
    validate_feature_functions_registered(config)
    validate_embeddings_config(config)
    validate_field_merge_source_priority(config)

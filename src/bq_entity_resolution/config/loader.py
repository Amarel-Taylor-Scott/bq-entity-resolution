"""
Configuration loader: YAML parsing, environment variable interpolation,
defaults merging, and Pydantic validation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.config.validators import validate_full
from bq_entity_resolution.exceptions import ConfigurationError

ENV_VAR_PATTERN = re.compile(r"\$\{([^}^{]+)\}")


def _interpolate_env_vars(obj: Any) -> Any:
    """Recursively replace ${VAR} and ${VAR:-default} with environment values."""
    if isinstance(obj, str):

        def _replacer(match: re.Match[str]) -> str:
            expr = match.group(1)
            if ":-" in expr:
                var_name, default = expr.split(":-", 1)
                return os.environ.get(var_name.strip(), default)
            value = os.environ.get(expr)
            if value is None or value.strip() == "":
                raise ConfigurationError(
                    f"Environment variable '${{{expr}}}' is not set or empty. "
                    f"Set it to a non-empty value or provide a default: "
                    f"${{{expr}:-default_value}}"
                )
            return value

        return ENV_VAR_PATTERN.sub(_replacer, obj)

    if isinstance(obj, dict):
        return {k: _interpolate_env_vars(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [_interpolate_env_vars(item) for item in obj]

    return obj


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge *override* into *base*. Override wins on leaf conflicts."""
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_includes(
    config_dir: Path,
    include_paths: list[str],
    seen: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve and merge included config files.

    Includes are resolved relative to the including file's directory.
    Circular includes are detected and rejected.
    """
    if seen is None:
        seen = set()

    if len(seen) > 50:
        raise ConfigurationError(
            "Include chain too deep (max 50 levels). "
            "Check for circular or excessively nested includes."
        )

    merged: dict[str, Any] = {}
    for include_rel in include_paths:
        include_path = (config_dir / include_rel).resolve()
        canonical = str(include_path)

        if canonical in seen:
            raise ConfigurationError(
                f"Circular include detected: {include_rel} "
                f"(already included via: {' -> '.join(seen)})"
            )

        if not include_path.exists():
            raise ConfigurationError(f"Included config not found: {include_path}")

        seen.add(canonical)

        with open(include_path, encoding="utf-8") as f:
            included = yaml.safe_load(f) or {}

        # Recursively resolve nested includes
        if "includes" in included:
            nested_includes = included.pop("includes")
            nested = _resolve_includes(include_path.parent, nested_includes, seen)
            included = _deep_merge(nested, included)

        merged = _deep_merge(merged, included)

    return merged


def load_config(
    config_path: str | Path,
    defaults_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    skip_env_interpolation: bool = False,
    validate: bool = True,
) -> PipelineConfig:
    """
    Load, merge, interpolate, and validate pipeline configuration.

    Order of precedence (highest wins):
      1. *overrides* dict
      2. User config YAML
      3. Included config files (``includes:`` key)
      4. Defaults YAML
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}")

    # Load defaults
    base: dict[str, Any] = {}
    if defaults_path:
        dp = Path(defaults_path)
        if dp.exists():
            with open(dp, encoding="utf-8") as f:
                base = yaml.safe_load(f) or {}

    # Load user config
    with open(config_path, encoding="utf-8") as f:
        user_config = yaml.safe_load(f) or {}

    # Resolve includes before merging
    if "includes" in user_config:
        include_paths = user_config.pop("includes")
        if isinstance(include_paths, str):
            include_paths = [include_paths]
        included = _resolve_includes(
            config_path.resolve().parent,
            include_paths,
            {str(config_path.resolve())},
        )
        base = _deep_merge(base, included)

    # Merge: defaults <- includes <- user <- overrides
    merged = _deep_merge(base, user_config)
    if overrides:
        merged = _deep_merge(merged, overrides)

    # Environment variable interpolation
    if not skip_env_interpolation:
        try:
            merged = _interpolate_env_vars(merged)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(f"Environment variable interpolation failed: {exc}") from exc

    # Validate with Pydantic
    try:
        config = PipelineConfig(**merged)
    except Exception as exc:
        raise ConfigurationError(f"Configuration validation failed: {exc}") from exc

    # Cross-field validation (comparison columns exist, feature inputs valid, etc.)
    if validate:
        validate_full(config)

    return config

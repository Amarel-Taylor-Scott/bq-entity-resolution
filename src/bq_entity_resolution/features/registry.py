"""
Feature function registry.

Maps config function names to BigQuery SQL expression generators.
Each registered function takes a list of input column names and optional
keyword params, and returns a BigQuery SQL expression string.

Usage in YAML:
  features:
    - name: "first_name_clean"
      function: "name_clean"
      input: "raw_first_name"

This translates to:  FEATURE_FUNCTIONS["name_clean"](["raw_first_name"]) -> SQL expr

BigQuery Performance Notes — Column Types and Blocking Efficiency
=================================================================
BigQuery stores and compares column types with very different performance
characteristics. When choosing features for **blocking keys**, prefer
functions that produce INT64 output over STRING output:

    INT64 equality    ~3-5x faster than STRING equality in JOINs/WHEREs
    INT64 GROUP BY    uses hash aggregation natively (8-byte fixed width)
    INT64 CLUSTER BY  produces tighter physical sort blocks in BQ storage

The cost hierarchy for column types in BigQuery equi-joins:

    INT64 / DATE (fixed-width)  >  short STRING (< 32 bytes)
    >  long STRING              >  REGEXP/LIKE
    >  EDIT_DISTANCE             >  JS UDF (jaro_winkler)

Functions that return INT64 (prefer these for blocking keys):
    farm_fingerprint, farm_fingerprint_concat, name_fingerprint,
    sorted_name_fingerprint, nickname_match_key, dob_year, year_of_date,
    char_length, age_from_dob

Functions that return STRING (fine for feature comparison, slower for blocking):
    soundex, name_clean, email_domain, phone_last_four, zip3, zip5,
    metaphone, initials, address_standardize, etc.

To convert any STRING blocking key to INT64, wrap it in FARM_FINGERPRINT:
    FARM_FINGERPRINT(SOUNDEX(col))  — phonetic blocking as INT64
    FARM_FINGERPRINT(LEFT(col, 3))  — prefix blocking as INT64

FARM_FINGERPRINT produces a deterministic INT64 hash. Collisions are
astronomically rare (~1 in 2^63) and acceptable for blocking because
blocking is a recall-oriented filter — false positives are eliminated
in the comparison stage.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

FeatureFunction = Callable[..., str]

FEATURE_FUNCTIONS: dict[str, FeatureFunction] = {}

# Feature functions that require BigQuery JavaScript UDFs.
# Used by config validation to reject these when allow_udfs=False.
UDF_FEATURE_FUNCTIONS: frozenset[str] = frozenset({
    "metaphone",
})

_plugins_loaded = False
_lock = threading.Lock()


def register(name: str) -> Callable[[FeatureFunction], FeatureFunction]:
    """Decorator to register a feature function.

    Can be used by external packages to add custom feature functions::

        from bq_entity_resolution import register_feature

        @register_feature("my_custom_feature")
        def my_custom_feature(inputs: list[str], **_: Any) -> str:
            return f"UPPER(TRIM({inputs[0]}))"

    The function is then available in YAML config::

        features:
          - name: cleaned
            function: my_custom_feature
            input: raw_column

    External packages can also auto-register via entry_points in
    ``pyproject.toml``::

        [project.entry-points."bq_er.features"]
        my_pkg = "my_pkg.features"
    """

    def decorator(func: FeatureFunction) -> FeatureFunction:
        with _lock:
            if name in FEATURE_FUNCTIONS:
                logger.warning(
                    "Feature function '%s' registered by %s is being "
                    "overwritten by %s",
                    name,
                    getattr(FEATURE_FUNCTIONS[name], "__module__", "?"),
                    getattr(func, "__module__", "?"),
                )
            FEATURE_FUNCTIONS[name] = func
        return func

    return decorator


def load_feature_plugins() -> None:
    """Discover and load feature function plugins from entry_points.

    Called automatically on first registry miss during config validation.
    Safe to call multiple times — only loads once. Thread-safe.
    """
    global _plugins_loaded
    with _lock:
        if _plugins_loaded:
            return
        _plugins_loaded = True

    try:
        from importlib.metadata import entry_points
    except ImportError:
        return

    try:
        eps = entry_points(group="bq_er.features")
    except TypeError:
        all_eps = entry_points()
        eps = all_eps.get("bq_er.features", [])  # type: ignore[arg-type]

    for ep in eps:
        try:
            ep.load()
            logger.debug("Loaded feature plugin '%s'", ep.name)
        except Exception as exc:
            logger.warning("Failed to load feature plugin '%s': %s", ep.name, exc)


# Import sub-modules to trigger @register decorators
import bq_entity_resolution.features.address_features  # noqa: E402, F401
import bq_entity_resolution.features.blocking_keys  # noqa: E402, F401
import bq_entity_resolution.features.business_features  # noqa: E402, F401
import bq_entity_resolution.features.contact_features  # noqa: E402, F401
import bq_entity_resolution.features.date_identity_features  # noqa: E402, F401
import bq_entity_resolution.features.email_features  # noqa: E402, F401
import bq_entity_resolution.features.entity_features  # noqa: E402, F401
import bq_entity_resolution.features.geo_features  # noqa: E402, F401
import bq_entity_resolution.features.industry_features  # noqa: E402, F401
import bq_entity_resolution.features.name_features  # noqa: E402, F401
import bq_entity_resolution.features.negative_features  # noqa: E402, F401
import bq_entity_resolution.features.phonetic_features  # noqa: E402, F401
import bq_entity_resolution.features.placeholder_features  # noqa: E402, F401
import bq_entity_resolution.features.utility_features  # noqa: E402, F401
import bq_entity_resolution.features.zip_features  # noqa: E402, F401

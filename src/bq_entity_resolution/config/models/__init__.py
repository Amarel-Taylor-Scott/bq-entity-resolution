"""
Domain-specific Pydantic v2 configuration models.

Sub-modules are organized by domain. The parent ``config.schema`` module
re-exports everything so existing imports remain unchanged.
"""

from bq_entity_resolution.config.models import (  # noqa: E402
    blocking as _blocking_mod,
)
from bq_entity_resolution.config.models import (
    features as _features_mod,
)
from bq_entity_resolution.config.models import (
    infrastructure as _infra_mod,
)
from bq_entity_resolution.config.models import (
    matching as _matching_mod,
)
from bq_entity_resolution.config.models import (
    pipeline as _pipeline_mod,
)
from bq_entity_resolution.config.models import (
    reconciliation as _recon_mod,
)
from bq_entity_resolution.config.models import (
    source as _source_mod,
)
from bq_entity_resolution.config.models.blocking import *  # noqa: F401,F403
from bq_entity_resolution.config.models.features import *  # noqa: F401,F403
from bq_entity_resolution.config.models.infrastructure import *  # noqa: F401,F403
from bq_entity_resolution.config.models.matching import *  # noqa: F401,F403
from bq_entity_resolution.config.models.pipeline import *  # noqa: F401,F403
from bq_entity_resolution.config.models.reconciliation import *  # noqa: F401,F403
from bq_entity_resolution.config.models.source import *  # noqa: F401,F403

__all__ = [
    *_blocking_mod.__all__,
    *_features_mod.__all__,
    *_infra_mod.__all__,
    *_matching_mod.__all__,
    *_pipeline_mod.__all__,
    *_recon_mod.__all__,
    *_source_mod.__all__,
]

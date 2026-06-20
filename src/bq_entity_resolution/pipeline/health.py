"""File-based health probe for Kubernetes liveness/readiness checks.

Writes a heartbeat file at a configurable path after each stage
completion. K8s can use an ``exec`` probe to check for the file::

    livenessProbe:
      exec:
        command: [test, -f, /tmp/pipeline_healthy]
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class HealthProbe:
    """File-based health probe for K8s liveness checks.

    Usage::

        probe = HealthProbe("/tmp/pipeline_healthy")
        probe.mark_healthy(stage="staging")
        # ... on shutdown ...
        probe.mark_unhealthy()
    """

    def __init__(self, path: str = "/tmp/pipeline_healthy", enabled: bool = True):
        self._path = path
        self._enabled = enabled
        self._last_stage: str = ""
        self._consecutive_failures: int = 0

    @property
    def path(self) -> str:
        return self._path

    @property
    def enabled(self) -> bool:
        return self._enabled

    def mark_healthy(self, stage: str = "", run_id: str = "") -> None:
        """Write the health file with current timestamp and stage info."""
        if not self._enabled:
            return
        self._last_stage = stage
        try:
            payload = {
                "status": "healthy",
                "timestamp": datetime.now(UTC).isoformat(),
                "stage": stage,
                "run_id": run_id,
                "pid": os.getpid(),
            }
            # Atomic write: write to temp file then rename
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(payload, f)
            os.replace(tmp_path, self._path)
            self._consecutive_failures = 0
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 5:
                logger.error(
                    "Failed to write health probe to %s (%d consecutive failures)",
                    self._path, self._consecutive_failures, exc_info=True,
                )
            else:
                logger.warning(
                    "Failed to write health probe to %s", self._path, exc_info=True
                )

    def mark_unhealthy(self) -> None:
        """Remove the health file to signal unhealthy status."""
        if not self._enabled:
            return
        try:
            os.remove(self._path)
        except FileNotFoundError:
            pass  # Already removed
        except Exception:
            logger.warning("Failed to remove health probe at %s", self._path, exc_info=True)

    def is_healthy(self) -> bool:
        """Check if the health file exists (for testing/debugging)."""
        return os.path.exists(self._path)

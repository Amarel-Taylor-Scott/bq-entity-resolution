"""Graceful shutdown handler for SIGTERM/SIGINT signals.

Registers signal handlers that:
1. Cancel in-flight BigQuery jobs via BigQueryClient.cancel_active_jobs()
2. Mark the health probe as unhealthy
3. Release distributed locks
4. Exit cleanly

Designed for Kubernetes pod termination where SIGTERM is sent
before the grace period expires.
"""

from __future__ import annotations

import logging
import signal
import sys
from typing import Any

logger = logging.getLogger(__name__)


class GracefulShutdown:
    """Signal handler for clean pipeline shutdown.

    Usage::

        shutdown = GracefulShutdown()
        shutdown.register_client(bq_client)
        shutdown.register_health_probe(health_probe)
        shutdown.register_lock(lock, pipeline_name)
        shutdown.install()

        # ... run pipeline ...

        shutdown.uninstall()
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._clients: list[Any] = []  # Objects with cancel_active_jobs()
        self._health_probes: list[Any] = []  # Objects with mark_unhealthy()
        self._locks: list[tuple[Any, str]] = []  # (lock, pipeline_name) pairs
        self._original_sigterm: Any = None
        self._original_sigint: Any = None
        self._installed = False
        self._shutting_down = False

    @property
    def installed(self) -> bool:
        return self._installed

    def register_client(self, client: Any) -> None:
        """Register a BigQueryClient for job cancellation on shutdown."""
        self._clients.append(client)

    def register_health_probe(self, probe: Any) -> None:
        """Register a health probe to mark unhealthy on shutdown."""
        self._health_probes.append(probe)

    def register_lock(self, lock: Any, pipeline_name: str) -> None:
        """Register a distributed lock to release on shutdown."""
        self._locks.append((lock, pipeline_name))

    def install(self) -> None:
        """Install SIGTERM and SIGINT signal handlers."""
        if not self._enabled or self._installed:
            return
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        self._installed = True
        logger.debug("Graceful shutdown handlers installed")

    def uninstall(self) -> None:
        """Restore original signal handlers."""
        if not self._installed:
            return
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
        self._installed = False
        logger.debug("Graceful shutdown handlers uninstalled")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM/SIGINT by cleaning up and exiting."""
        if self._shutting_down:
            # Already shutting down, force exit
            logger.warning("Forced exit on second signal")
            sys.exit(128 + signum)

        self._shutting_down = True
        sig_name = signal.Signals(signum).name
        logger.warning("Received %s, initiating graceful shutdown...", sig_name)

        # 1. Cancel in-flight BigQuery jobs
        total_cancelled = 0
        for client in self._clients:
            try:
                count = client.cancel_active_jobs()
                total_cancelled += count
            except Exception:
                logger.warning("Error cancelling jobs", exc_info=True)
        if total_cancelled:
            logger.info("Cancelled %d in-flight BigQuery job(s)", total_cancelled)

        # 2. Mark health probes as unhealthy
        for probe in self._health_probes:
            try:
                probe.mark_unhealthy()
            except Exception:
                logger.debug(
                    "Failed to mark health probe unhealthy during shutdown",
                    exc_info=True,
                )

        # 3. Release distributed locks
        for lock, name in self._locks:
            try:
                lock.release(name)
            except Exception:
                logger.warning("Failed to release lock '%s'", name, exc_info=True)

        logger.info("Graceful shutdown complete, exiting")
        sys.exit(128 + signum)

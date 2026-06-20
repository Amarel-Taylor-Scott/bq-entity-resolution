"""Tests for BigQuery client retry logic."""

import inspect

from google.api_core.exceptions import InternalServerError, ServiceUnavailable, TooManyRequests

from bq_entity_resolution.clients.bigquery import (
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    RETRYABLE_ERRORS,
    BigQueryClient,
)


def test_retryable_errors_includes_service_unavailable():
    """ServiceUnavailable is in RETRYABLE_ERRORS."""
    assert ServiceUnavailable in RETRYABLE_ERRORS


def test_retryable_errors_includes_internal_server_error():
    """InternalServerError (500) is in RETRYABLE_ERRORS."""
    assert InternalServerError in RETRYABLE_ERRORS


def test_retryable_errors_includes_too_many_requests():
    """TooManyRequests (429) is in RETRYABLE_ERRORS."""
    assert TooManyRequests in RETRYABLE_ERRORS


def test_retryable_errors_tuple_length():
    """RETRYABLE_ERRORS contains exactly 3 error types."""
    assert len(RETRYABLE_ERRORS) == 3


def test_execute_and_fetch_has_timeout_param():
    """execute_and_fetch accepts a timeout parameter (default None, uses default_timeout)."""
    sig = inspect.signature(BigQueryClient.execute_and_fetch)
    assert "timeout" in sig.parameters
    assert sig.parameters["timeout"].default is None


def test_max_retries_constant():
    """MAX_RETRIES is 3."""
    assert MAX_RETRIES == 3


def test_retry_delay_constant():
    """RETRY_DELAY_SECONDS is 5."""
    assert RETRY_DELAY_SECONDS == 5


def test_execute_and_fetch_returns_list():
    """execute_and_fetch return annotation is list[dict[str, Any]]."""
    hints = inspect.get_annotations(BigQueryClient.execute_and_fetch)
    assert hints.get("return") == "list[dict[str, Any]]"

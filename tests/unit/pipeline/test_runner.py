"""Tests for SQLRunner — specifically execute_script_and_fetch()."""

from unittest.mock import MagicMock

import pytest

from bq_entity_resolution.clients.bigquery import BigQueryClient
from bq_entity_resolution.pipeline.runner import SQLRunner


@pytest.fixture
def mock_bq_client():
    return MagicMock(spec=BigQueryClient)


@pytest.fixture
def runner(mock_bq_client):
    return SQLRunner(mock_bq_client)


def test_execute_script_and_fetch_exists(runner):
    """Method exists on SQLRunner."""
    assert hasattr(runner, "execute_script_and_fetch")
    assert callable(runner.execute_script_and_fetch)


def test_execute_script_and_fetch_delegates(runner, mock_bq_client):
    """Delegates to bq_client.execute_script_and_fetch()."""
    mock_bq_client.execute_script_and_fetch.return_value = [
        {"m": 0.9, "u": 0.1}
    ]
    rows = runner.execute_script_and_fetch("DECLARE x INT64; SELECT 1;", "em_est")
    mock_bq_client.execute_script_and_fetch.assert_called_once_with(
        "DECLARE x INT64; SELECT 1;", job_label="em_est"
    )
    assert rows == [{"m": 0.9, "u": 0.1}]


def test_execute_script_and_fetch_tracks_success(runner, mock_bq_client):
    """Successful call is tracked in executed_queries."""
    mock_bq_client.execute_script_and_fetch.return_value = [{"a": 1}, {"a": 2}]
    runner.execute_script_and_fetch("SELECT 1;", "test_label")

    assert len(runner.executed_queries) == 1
    entry = runner.executed_queries[0]
    assert entry["label"] == "test_label"
    assert entry["status"] == "success"
    assert entry["rows_returned"] == 2


def test_execute_script_and_fetch_tracks_failure(runner, mock_bq_client):
    """Failed call is tracked with error details."""
    mock_bq_client.execute_script_and_fetch.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        runner.execute_script_and_fetch("BAD SQL;", "fail_label")

    assert len(runner.executed_queries) == 1
    entry = runner.executed_queries[0]
    assert entry["status"] == "failed"
    assert "boom" in entry["error"]


def test_execute_script_and_fetch_returns_list_of_dicts(runner, mock_bq_client):
    """Return type is list[dict]."""
    mock_bq_client.execute_script_and_fetch.return_value = [
        {"comp": "name", "level": "exact", "m": 0.95, "u": 0.05},
        {"comp": "name", "level": "fuzzy", "m": 0.70, "u": 0.15},
    ]
    result = runner.execute_script_and_fetch("SCRIPT;", "params")
    assert isinstance(result, list)
    assert all(isinstance(r, dict) for r in result)
    assert len(result) == 2
    assert result[0]["comp"] == "name"

"""Tests for CheckpointManager."""

from unittest.mock import MagicMock

import pytest

from bq_entity_resolution.sql.utils import validate_safe_value
from bq_entity_resolution.watermark.checkpoint import CheckpointManager


def _make_mgr():
    client = MagicMock()
    mgr = CheckpointManager(
        bq_client=client,
        checkpoint_table="proj.meta.pipeline_checkpoints",
    )
    return mgr, client


def test_ensure_table_exists():
    mgr, client = _make_mgr()
    mgr.ensure_table_exists()
    client.execute.assert_called_once()
    sql = client.execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "pipeline_checkpoints" in sql


def test_load_completed_stages_returns_set():
    mgr, client = _make_mgr()
    client.execute_and_fetch.return_value = [
        {"stage_name": "init_watermarks"},
        {"stage_name": "stage_sources"},
    ]
    result = mgr.load_completed_stages("run_123")
    assert result == {"init_watermarks", "stage_sources"}
    sql = client.execute_and_fetch.call_args[0][0]
    assert "run_123" in sql
    assert "status = 'completed'" in sql


def test_load_completed_stages_empty():
    mgr, client = _make_mgr()
    client.execute_and_fetch.return_value = []
    result = mgr.load_completed_stages("run_123")
    assert result == set()


def test_find_resumable_run_found():
    mgr, client = _make_mgr()
    client.execute_and_fetch.return_value = [{"run_id": "er_run_20250101_120000"}]
    result = mgr.find_resumable_run()
    assert result == "er_run_20250101_120000"
    sql = client.execute_and_fetch.call_args[0][0]
    assert "__run_complete__" in sql


def test_find_resumable_run_none():
    mgr, client = _make_mgr()
    client.execute_and_fetch.return_value = []
    result = mgr.find_resumable_run()
    assert result is None


def test_mark_stage_complete():
    mgr, client = _make_mgr()
    mgr.mark_stage_complete("run_123", "stage_sources")
    client.execute.assert_called_once()
    sql = client.execute.call_args[0][0]
    assert "INSERT INTO" in sql
    assert "run_123" in sql
    assert "stage_sources" in sql


def test_mark_run_complete():
    mgr, client = _make_mgr()
    mgr.mark_run_complete("run_123")
    client.execute.assert_called_once()
    sql = client.execute.call_args[0][0]
    assert "__run_complete__" in sql
    assert "run_123" in sql


def test_single_quote_in_run_id_rejected():
    """Single quotes in run_id are now rejected (not just escaped)."""
    mgr, client = _make_mgr()
    with pytest.raises(ValueError, match="Unsafe characters"):
        mgr.load_completed_stages("it's_a_test")


# -- Input validation tests ---------------------------------------------------


class TestValidateSafeValue:
    def test_safe_alphanumeric(self):
        assert validate_safe_value("run_123", "run_id") == "run_123"

    def test_safe_with_hyphens_dots(self):
        assert validate_safe_value("er_run_2025-01-01.v2", "run_id") == "er_run_2025-01-01.v2"

    def test_safe_with_colons_slashes(self):
        """Timestamps and paths are allowed."""
        assert validate_safe_value("2025-01-01T12:00:00", "run_id") == "2025-01-01T12:00:00"

    def test_rejects_single_quotes(self):
        """Single quotes are rejected (injection vector)."""
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("it's_bad", "run_id")

    def test_rejects_semicolons(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("run_123; DROP TABLE --", "run_id")

    def test_rejects_parentheses(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("run_123()", "run_id")

    def test_rejects_newlines(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("run_123\nDROP TABLE", "run_id")

    def test_rejects_backticks(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("run`123`", "run_id")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            validate_safe_value("", "run_id")

    def test_mark_stage_rejects_injection(self):
        mgr, client = _make_mgr()
        with pytest.raises(ValueError, match="Unsafe characters"):
            mgr.mark_stage_complete("run_123", "stage'; DROP TABLE x; --")

    def test_load_stages_rejects_injection(self):
        mgr, client = _make_mgr()
        with pytest.raises(ValueError, match="Unsafe characters"):
            mgr.load_completed_stages("'; DROP TABLE x; --")


class TestFencingTokenValidation:
    """Tests for partial fencing config warning."""

    def test_full_fencing_uses_fenced_insert(self):
        mgr, client = _make_mgr()
        mgr.mark_stage_complete(
            "run_1", "staging",
            fencing_token=42,
            lock_table="proj.meta.locks",
            pipeline_name="my_pipe",
        )
        client.execute_script.assert_called_once()

    def test_no_fencing_uses_unfenced_insert(self):
        mgr, client = _make_mgr()
        mgr.mark_stage_complete("run_1", "staging")
        client.execute.assert_called_once()

    def test_partial_fencing_raises_value_error(self):
        """Providing only some fencing params raises ValueError (fail-fast)."""
        mgr, client = _make_mgr()
        with pytest.raises(ValueError, match="Partial fencing config"):
            mgr.mark_stage_complete(
                "run_1", "staging",
                fencing_token=42,
                lock_table="proj.meta.locks",
                pipeline_name=None,  # Missing!
            )
        client.execute.assert_not_called()
        client.execute_script.assert_not_called()

    def test_partial_fencing_token_only_raises(self):
        """Providing only fencing_token raises ValueError."""
        mgr, client = _make_mgr()
        with pytest.raises(ValueError, match="Partial fencing config"):
            mgr.mark_stage_complete(
                "run_1", "staging",
                fencing_token=42,
            )

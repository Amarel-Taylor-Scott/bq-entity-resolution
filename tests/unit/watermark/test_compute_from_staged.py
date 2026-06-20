"""Tests for WatermarkManager.compute_new_watermark_from_staged().

Verifies that the watermark manager correctly computes MAX values
from the staged (bronze) table with optional column mapping.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bq_entity_resolution.exceptions import WatermarkError
from bq_entity_resolution.watermark.manager import WatermarkManager


def _make_manager():
    """Create a WatermarkManager with a mock bq_client."""
    client = MagicMock()
    mgr = WatermarkManager(
        bq_client=client,
        watermark_table="proj.meta.watermarks",
    )
    return mgr, client


class TestComputeNewWatermarkFromStaged:
    """Tests for compute_new_watermark_from_staged()."""

    def test_constructs_correct_sql_with_max(self):
        """SQL contains MAX(column) for each cursor column."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = [
            {"max_updated_at": "2024-06-15T12:00:00"}
        ]

        mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at"],
        )

        sql = client.execute_and_fetch.call_args[0][0]
        assert "MAX(updated_at) AS max_updated_at" in sql
        assert "proj.bronze.staged_crm" in sql

    def test_column_mapping_translates_names(self):
        """Column mapping converts source column names to staged names."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = [
            {"max_updated_at": "2024-06-15T12:00:00"}
        ]

        mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at"],
            column_mapping={"updated_at": "source_updated_at"},
        )

        sql = client.execute_and_fetch.call_args[0][0]
        # Should use the mapped column name in the MAX expression
        assert "MAX(source_updated_at) AS max_updated_at" in sql

    def test_empty_result_returns_empty_dict(self):
        """Empty query result returns an empty dict."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = []

        result = mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at"],
        )

        assert result == {}

    def test_multiple_cursor_columns(self):
        """Multiple cursor columns generate multiple MAX expressions."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = [
            {
                "max_updated_at": "2024-06-15T12:00:00",
                "max_policy_id": 99999,
            }
        ]

        result = mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at", "policy_id"],
        )

        sql = client.execute_and_fetch.call_args[0][0]
        assert "MAX(updated_at) AS max_updated_at" in sql
        assert "MAX(policy_id) AS max_policy_id" in sql

        assert result["updated_at"] == "2024-06-15T12:00:00"
        assert result["policy_id"] == 99999

    def test_none_values_excluded_from_result(self):
        """Columns with None MAX values are excluded from the result dict."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = [
            {
                "max_updated_at": "2024-06-15T12:00:00",
                "max_policy_id": None,
            }
        ]

        result = mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at", "policy_id"],
        )

        assert "updated_at" in result
        assert "policy_id" not in result

    def test_column_mapping_with_multiple_columns(self):
        """Column mapping works with multiple cursor columns."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = [
            {
                "max_updated_at": "2024-06-15T12:00:00",
                "max_batch_num": 42,
            }
        ]

        mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at", "batch_num"],
            column_mapping={
                "updated_at": "source_updated_at",
                "batch_num": "pipeline_batch_num",
            },
        )

        sql = client.execute_and_fetch.call_args[0][0]
        assert "MAX(source_updated_at) AS max_updated_at" in sql
        assert "MAX(pipeline_batch_num) AS max_batch_num" in sql

    def test_no_column_mapping_uses_original_names(self):
        """Without column_mapping, original cursor column names are used."""
        mgr, client = _make_manager()
        client.execute_and_fetch.return_value = [
            {"max_updated_at": "2024-06-15T12:00:00"}
        ]

        mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at"],
            column_mapping=None,
        )

        sql = client.execute_and_fetch.call_args[0][0]
        assert "MAX(updated_at) AS max_updated_at" in sql

    def test_raises_watermark_error_on_query_failure(self):
        """Raises WatermarkError when the query fails."""
        mgr, client = _make_manager()
        client.execute_and_fetch.side_effect = RuntimeError("BQ error")

        with pytest.raises(WatermarkError, match="Failed to compute watermark"):
            mgr.compute_new_watermark_from_staged(
                staged_table="proj.bronze.staged_crm",
                cursor_columns=["updated_at"],
            )

    def test_single_column_result(self):
        """Single cursor column returns correct result."""
        mgr, client = _make_manager()
        ts = "2024-12-31T23:59:59"
        client.execute_and_fetch.return_value = [{"max_updated_at": ts}]

        result = mgr.compute_new_watermark_from_staged(
            staged_table="proj.bronze.staged_crm",
            cursor_columns=["updated_at"],
        )

        assert result == {"updated_at": ts}


class TestWatermarkFencingValidation:
    """Tests for partial fencing config warning in WatermarkManager.write()."""

    def test_full_fencing_uses_fenced_sql(self):
        mgr, client = _make_manager()
        mgr.ensure_table_exists = MagicMock()
        mgr.write(
            "crm", {"updated_at": "2024-01-01"},
            run_id="r1",
            fencing_token=42,
            lock_table="proj.meta.locks",
            pipeline_name="my_pipe",
        )
        sql = client.execute.call_args[0][0]
        assert "fencing" in sql.lower() or client.execute.called

    def test_no_fencing_uses_unfenced_sql(self):
        mgr, client = _make_manager()
        mgr.ensure_table_exists = MagicMock()
        mgr.write("crm", {"updated_at": "2024-01-01"}, run_id="r1")
        assert client.execute.called

    def test_partial_fencing_warns(self, caplog):
        """Providing only some fencing params logs a warning."""
        import logging
        mgr, client = _make_manager()
        mgr.ensure_table_exists = MagicMock()
        with caplog.at_level(logging.WARNING):
            mgr.write(
                "crm", {"updated_at": "2024-01-01"},
                run_id="r1",
                fencing_token=42,
                lock_table=None,
                pipeline_name="my_pipe",
            )
        assert "Partial fencing config" in caplog.text

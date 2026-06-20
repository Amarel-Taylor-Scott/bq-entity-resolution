"""Tests for monitoring/audit SQL builder."""

from __future__ import annotations

from bq_entity_resolution.sql.builders.monitoring import build_persist_sql_log_sql


class TestBuildPersistSqlLogSql:
    """Tests for build_persist_sql_log_sql."""

    def test_returns_sql_expression(self):
        result = build_persist_sql_log_sql("proj.meta.audit", "run-1", [])
        sql = result.render()
        assert "CREATE TABLE IF NOT EXISTS" in sql

    def test_creates_table_ddl(self):
        sql = build_persist_sql_log_sql("proj.meta.audit", "run-1", []).render()
        assert "run_id STRING" in sql
        assert "stage STRING" in sql
        assert "step STRING" in sql
        assert "sql_text STRING" in sql
        assert "executed_at STRING" in sql

    def test_inserts_entries(self):
        entries = [
            {"stage": "staging", "step": "load", "sql": "SELECT 1", "timestamp": "2024-01-01"},
            {"stage": "features", "step": "compute", "sql": "SELECT 2", "timestamp": "2024-01-02"},
        ]
        sql = build_persist_sql_log_sql("t", "run-1", entries).render()
        assert "INSERT INTO" in sql
        assert "staging" in sql
        assert "features" in sql
        assert "SELECT 1" in sql
        assert "SELECT 2" in sql

    def test_escapes_sql_text(self):
        entries = [
            {"stage": "s", "step": "p", "sql": "WHERE name = 'O''Brien'", "timestamp": "t"},
        ]
        sql = build_persist_sql_log_sql("t", "run-1", entries).render()
        # The SQL text with quotes should be escaped
        assert "INSERT INTO" in sql

    def test_empty_entries_no_insert(self):
        sql = build_persist_sql_log_sql("t", "run-1", []).render()
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "INSERT" not in sql

    def test_includes_run_id_in_values(self):
        entries = [
            {"stage": "s", "step": "p", "sql": "q", "timestamp": "t"},
        ]
        sql = build_persist_sql_log_sql("t", "my-run-id", entries).render()
        assert "my-run-id" in sql

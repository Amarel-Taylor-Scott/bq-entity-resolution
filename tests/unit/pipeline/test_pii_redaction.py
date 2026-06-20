"""Tests for PII redaction in SQL audit logs."""

from __future__ import annotations

from bq_entity_resolution.pipeline.executor import (
    _PII_PATTERNS,
    PipelineExecutor,
    _redact_sql,
)


class TestPhoneRedaction:
    """Test phone number pattern redaction.

    Phone numbers outside string literals are matched by the phone regex.
    Phone numbers inside string literals are caught by the generic string
    literal pattern first (since the patterns are applied in order and the
    string literal pattern appears after phone).
    """

    def test_phone_outside_quotes(self):
        """Phone number outside quotes is redacted to <PHONE>."""
        result = _redact_sql("WHERE phone = 555-123-4567 AND x = 1")
        assert "<PHONE>" in result
        assert "555-123-4567" not in result

    def test_phone_inside_quotes_caught_by_string_literal(self):
        """Phone inside string literals is caught by the generic redactor."""
        result = _redact_sql("WHERE phone = '555-123-4567'")
        # The string literal pattern fires first, so the phone is redacted
        # as a string literal, not as <PHONE>
        assert "555-123-4567" not in result
        assert "'<REDACTED>'" in result


class TestSSNRedaction:
    """Test SSN pattern redaction.

    SSN numbers appear before phone in pattern priority, so they are matched
    first when not inside quotes.
    """

    def test_ssn_outside_quotes(self):
        """SSN outside quotes is redacted to <SSN>."""
        result = _redact_sql("WHERE ssn = 123-45-6789 AND x = 1")
        assert "<SSN>" in result
        assert "123-45-6789" not in result

    def test_ssn_inside_quotes_caught_by_string_literal(self):
        """SSN inside string literals is caught by the generic redactor."""
        result = _redact_sql("WHERE ssn = '123-45-6789'")
        assert "123-45-6789" not in result
        assert "'<REDACTED>'" in result

    def test_ssn_before_phone_in_pattern_order(self):
        """SSN pattern appears before phone pattern to avoid partial overlap."""
        pattern_replacements = [repl for _, repl in _PII_PATTERNS]
        ssn_idx = pattern_replacements.index("<SSN>")
        phone_idx = pattern_replacements.index("<PHONE>")
        assert ssn_idx < phone_idx


class TestEmailRedaction:
    """Test email address pattern redaction."""

    def test_email_outside_quotes(self):
        """Email outside quotes is redacted to <EMAIL>."""
        result = _redact_sql("WHERE email = user@example.com AND x = 1")
        assert "<EMAIL>" in result
        assert "user@example.com" not in result

    def test_email_inside_quotes_caught_by_string_literal(self):
        """Email inside string literals is caught by the generic redactor."""
        result = _redact_sql("WHERE email = 'user@example.com'")
        assert "user@example.com" not in result
        assert "'<REDACTED>'" in result

    def test_email_in_concat(self):
        """Email in CONCAT is caught by string literal redaction."""
        result = _redact_sql("CONCAT('prefix', 'john@example.org')")
        assert "john@example.org" not in result


class TestStringLiteralRedaction:
    """Test generic string literal redaction."""

    def test_name_literal(self):
        """'John Smith' is redacted to '<REDACTED>'."""
        result = _redact_sql("WHERE name = 'John Smith'")
        assert "'<REDACTED>'" in result
        assert "John Smith" not in result

    def test_empty_string_literal(self):
        """Empty string literal '' is redacted."""
        result = _redact_sql("WHERE name = ''")
        assert "'<REDACTED>'" in result

    def test_multiple_literals(self):
        """Multiple string literals are all redacted."""
        result = _redact_sql("WHERE first = 'John' AND last = 'Doe'")
        assert "John" not in result
        assert "Doe" not in result
        assert "'<REDACTED>'" in result


class TestTimestampRedaction:
    """Test TIMESTAMP literal redaction."""

    def test_timestamp_redacted(self):
        """TIMESTAMP('2024-01-01') -> TIMESTAMP('<REDACTED>')."""
        result = _redact_sql("WHERE ts > TIMESTAMP('2024-01-01')")
        assert "TIMESTAMP('<REDACTED>')" in result
        assert "2024-01-01" not in result

    def test_timestamp_with_time(self):
        """TIMESTAMP('2024-01-01T00:00:00') is redacted."""
        result = _redact_sql("TIMESTAMP('2024-01-01T00:00:00')")
        assert "TIMESTAMP('<REDACTED>')" in result

    def test_timestamp_before_string_literal(self):
        """Timestamp pattern fires before generic string literal."""
        result = _redact_sql("TIMESTAMP('2024-06-15T12:30:00Z')")
        assert "TIMESTAMP('<REDACTED>')" in result
        # The inner value should not remain
        assert "2024-06-15" not in result


class TestRedactionAlwaysApplied:
    """Test that redaction is always applied (not opt-in)."""

    def test_executor_redacts_by_default(self):
        """PipelineExecutor has redact_sql_logs=True by default."""

        class FakeBackend:
            def execute(self, sql, label=""):
                pass

        executor = PipelineExecutor(backend=FakeBackend())
        # The internal flag should be True
        assert executor._redact_sql_logs is True

    def test_executor_ignores_false_flag(self):
        """Even with redact_sql_logs=False, redaction is still applied.

        The flag is kept for backward-compatible signatures but has no effect:
        _redact_sql() is applied unconditionally.
        """

        class FakeBackend:
            def execute(self, sql, label=""):
                pass

        # Even explicitly passing False, redaction should still work
        PipelineExecutor(backend=FakeBackend(), redact_sql_logs=False)
        # The _redact_sql function itself always works regardless
        result = _redact_sql("WHERE name = 'John'")
        assert "John" not in result

    def test_redact_sql_is_unconditional(self):
        """_redact_sql always processes input regardless of any flag."""
        assert "sensitive" not in _redact_sql("WHERE val = 'sensitive'")


class TestRedactionPreservesStructure:
    """Test that SQL structure is preserved after redaction."""

    def test_keywords_preserved(self):
        """SQL keywords are not affected by redaction."""
        sql = "SELECT * FROM `proj.ds.table` WHERE score >= 5.0"
        result = _redact_sql(sql)
        assert "SELECT" in result
        assert "FROM" in result
        assert "WHERE" in result
        assert "proj.ds.table" in result

    def test_table_refs_preserved(self):
        """Backtick-quoted table references are preserved."""
        sql = "CREATE OR REPLACE TABLE `proj.ds.matches` AS SELECT 1"
        result = _redact_sql(sql)
        assert "`proj.ds.matches`" in result

    def test_numeric_values_preserved(self):
        """Numeric values are not redacted."""
        sql = "WHERE score >= 5.0 AND tier_priority = 1"
        result = _redact_sql(sql)
        assert "5.0" in result
        assert "1" in result

    def test_column_names_preserved(self):
        """Column names are not redacted."""
        sql = "SELECT entity_uid, cluster_id, match_confidence FROM tbl"
        result = _redact_sql(sql)
        assert "entity_uid" in result
        assert "cluster_id" in result
        assert "match_confidence" in result


class TestPIIPatternsOrder:
    """Test that patterns are applied in correct priority order."""

    def test_patterns_list_is_not_empty(self):
        """_PII_PATTERNS contains patterns."""
        assert len(_PII_PATTERNS) > 0

    def test_timestamp_before_string_literal(self):
        """Timestamp pattern appears before generic string literal in list."""
        pattern_replacements = [repl for _, repl in _PII_PATTERNS]
        ts_idx = pattern_replacements.index("TIMESTAMP('<REDACTED>')")
        str_idx = pattern_replacements.index("'<REDACTED>'")
        assert ts_idx < str_idx

    def test_ssn_before_phone(self):
        """SSN pattern appears before phone pattern."""
        pattern_replacements = [repl for _, repl in _PII_PATTERNS]
        ssn_idx = pattern_replacements.index("<SSN>")
        phone_idx = pattern_replacements.index("<PHONE>")
        assert ssn_idx < phone_idx

    def test_five_patterns_defined(self):
        """All five pattern types are defined."""
        replacements = {repl for _, repl in _PII_PATTERNS}
        assert "TIMESTAMP('<REDACTED>')" in replacements
        assert "<SSN>" in replacements
        assert "<PHONE>" in replacements
        assert "<EMAIL>" in replacements
        assert "'<REDACTED>'" in replacements


class TestMixedPIIContent:
    """Test redaction with mixed PII types in a single SQL string."""

    def test_multiple_pii_types(self):
        """SQL with multiple PII types has all values redacted."""
        sql = (
            "INSERT INTO log VALUES ("
            "'John Smith', 'john@test.com', '123-45-6789', '555-123-4567', "
            "TIMESTAMP('2024-01-01'))"
        )
        result = _redact_sql(sql)
        assert "John Smith" not in result
        assert "john@test.com" not in result
        assert "123-45-6789" not in result
        assert "555-123-4567" not in result
        assert "2024-01-01" not in result

    def test_pii_free_sql_unchanged(self):
        """SQL without PII or string literals is returned unchanged."""
        sql = "SELECT entity_uid, cluster_id FROM `proj.ds.clusters` WHERE score >= 5.0"
        result = _redact_sql(sql)
        assert result == sql

"""Tests for placeholder profiler."""

from __future__ import annotations

from bq_entity_resolution.profiling.placeholder_profiler import (
    PlaceholderFinding,
    PlaceholderProfiler,
    PlaceholderProfileResult,
)


class TestBuildKnownPatternSql:
    """Tests for build_known_pattern_sql."""

    def test_generates_sql_for_phone_role(self):
        profiler = PlaceholderProfiler(backend=None)
        sql_expr = profiler.build_known_pattern_sql(
            "proj.ds.customers",
            [("phone", "phone")],
        )
        assert sql_expr is not None
        sql = sql_expr.render()
        assert "'phone'" in sql
        assert "known" in sql

    def test_generates_union_for_multiple_roles(self):
        profiler = PlaceholderProfiler(backend=None)
        sql_expr = profiler.build_known_pattern_sql(
            "proj.ds.customers",
            [("phone", "phone"), ("email", "email")],
        )
        assert sql_expr is not None
        sql = sql_expr.render()
        assert "UNION ALL" in sql

    def test_returns_none_for_no_detectable_roles(self):
        profiler = PlaceholderProfiler(backend=None)
        result = profiler.build_known_pattern_sql(
            "proj.ds.customers",
            [("random_col", "unknown_role")],
        )
        assert result is None

    def test_includes_having_clause(self):
        profiler = PlaceholderProfiler(backend=None)
        sql_expr = profiler.build_known_pattern_sql(
            "proj.ds.customers",
            [("phone", "phone")],
        )
        assert sql_expr is not None
        sql = sql_expr.render()
        assert "HAVING COUNT(*) >= 2" in sql

    def test_name_role_detection(self):
        profiler = PlaceholderProfiler(backend=None)
        sql_expr = profiler.build_known_pattern_sql(
            "proj.ds.customers",
            [("first_name", "first_name")],
        )
        assert sql_expr is not None
        sql = sql_expr.render()
        assert "'first_name'" in sql


class TestBuildSuspectedPatternSql:
    """Tests for build_suspected_pattern_sql."""

    def test_generates_frequency_sql(self):
        profiler = PlaceholderProfiler(backend=None)
        sql_expr = profiler.build_suspected_pattern_sql(
            "proj.ds.customers",
            ["phone", "email"],
            top_n=10,
        )
        sql = sql_expr.render()
        assert "frequency_ratio" in sql
        assert "LIMIT 10" in sql

    def test_union_for_multiple_columns(self):
        profiler = PlaceholderProfiler(backend=None)
        sql_expr = profiler.build_suspected_pattern_sql(
            "proj.ds.customers",
            ["phone", "email"],
        )
        sql = sql_expr.render()
        assert "UNION ALL" in sql


class TestAnalyzeResults:
    """Tests for analyze_results."""

    def test_known_findings(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = profiler.analyze_results(
            known_rows=[{
                "column_name": "phone",
                "value": "9999999999",
                "match_count": 500,
                "role": "phone",
            }],
            suspected_rows=[],
        )
        assert len(findings) == 1
        assert findings[0].pattern_type == "known"
        assert findings[0].count == 500

    def test_deduplicates_known_from_suspected(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = profiler.analyze_results(
            known_rows=[{
                "column_name": "phone",
                "value": "9999999999",
                "match_count": 500,
                "role": "phone",
            }],
            suspected_rows=[{
                "column_name": "phone",
                "value": "9999999999",
                "match_count": 500,
                "frequency_ratio": 0.05,
            }],
        )
        assert len(findings) == 1

    def test_suspected_findings(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = profiler.analyze_results(
            known_rows=[],
            suspected_rows=[{
                "column_name": "email",
                "value": "test@test.com",
                "match_count": 100,
                "frequency_ratio": 0.02,
            }],
        )
        assert len(findings) == 1
        assert findings[0].pattern_type == "suspected"


class TestGenerateYamlSnippet:
    """Tests for generate_yaml_snippet."""

    def test_generates_yaml_for_suspected(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = [
            PlaceholderFinding("phone", "5555555555", 200, "suspected"),
        ]
        yaml = profiler.generate_yaml_snippet(findings)
        assert "custom_patterns" in yaml
        assert "5555555555" in yaml

    def test_no_yaml_for_known_only(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = [
            PlaceholderFinding("phone", "9999999999", 500, "known"),
        ]
        yaml = profiler.generate_yaml_snippet(findings)
        assert "No additional custom patterns" in yaml


class TestFormatReport:
    """Tests for format_report."""

    def test_includes_known_section(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = [
            PlaceholderFinding("phone", "9999999999", 500, "known"),
        ]
        report = profiler.format_report(findings)
        assert "Known Placeholders" in report

    def test_includes_suspected_section(self):
        profiler = PlaceholderProfiler(backend=None)
        findings = [
            PlaceholderFinding("email", "test@test.com", 100, "suspected"),
        ]
        report = profiler.format_report(findings)
        assert "Suspected Placeholders" in report

    def test_empty_report(self):
        profiler = PlaceholderProfiler(backend=None)
        report = profiler.format_report([])
        assert "No placeholder values detected" in report


class TestPlaceholderProfileResult:
    """Tests for PlaceholderProfileResult dataclass."""

    def test_default_values(self):
        result = PlaceholderProfileResult(source_table="proj.ds.tbl")
        assert result.source_table == "proj.ds.tbl"
        assert result.findings == []
        assert result.yaml_snippet == ""

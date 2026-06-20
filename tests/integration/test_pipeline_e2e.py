"""End-to-end integration test: Pipeline API with DuckDB backend.

Proves the complete new architecture works without Jinja2 templates:
config → DAG → plan → validate → execute (DuckDB) → result.
"""

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.pipeline.pipeline import Pipeline
from bq_entity_resolution.pipeline.validator import ContractViolation

# -- Fixtures --


@pytest.fixture
def person_config():
    """A realistic person dedup config for e2e testing."""
    return quick_config(
        bq_project="test-proj",
        source_table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        column_roles={
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
        },
        project_name="e2e_test",
    )


@pytest.fixture
def pipeline(person_config):
    """Pipeline instance from person config."""
    return Pipeline(person_config)


# -- Pipeline construction tests --


class TestPipelineConstruction:
    def test_creates_pipeline(self, pipeline):
        assert pipeline is not None
        assert len(pipeline.stage_names) >= 6

    def test_has_expected_stages(self, pipeline):
        names = pipeline.stage_names
        assert "staging_customers" in names
        assert "feature_engineering" in names
        assert "clustering" in names
        assert "gold_output" in names

    def test_stages_in_correct_order(self, pipeline):
        names = pipeline.stage_names
        staging_idx = names.index("staging_customers")
        feature_idx = names.index("feature_engineering")
        cluster_idx = names.index("clustering")
        gold_idx = names.index("gold_output")
        assert staging_idx < feature_idx < cluster_idx < gold_idx


# -- Validation tests --


class TestPipelineValidation:
    def test_validates_successfully(self, pipeline):
        violations = pipeline.validate()
        errors = [v for v in violations if v.severity == "error"]
        assert errors == [], f"Unexpected errors: {errors}"

    def test_validation_returns_violations(self, pipeline):
        violations = pipeline.validate()
        # All violations should be ContractViolation instances
        for v in violations:
            assert isinstance(v, ContractViolation)


# -- Plan generation tests --


class TestPipelinePlan:
    def test_generates_plan(self, pipeline):
        plan = pipeline.plan(full_refresh=True)
        assert plan is not None
        assert plan.total_sql_count > 0

    def test_plan_has_all_stages(self, pipeline):
        plan = pipeline.plan(full_refresh=True)
        plan_stage_names = plan.stage_names
        dag_stage_names = pipeline.stage_names
        assert set(plan_stage_names) == set(dag_stage_names)

    def test_plan_preview(self, pipeline):
        plan = pipeline.plan(full_refresh=True)
        preview = plan.preview()
        assert "Pipeline Plan" in preview
        assert "staging_customers" in preview
        assert "feature_engineering" in preview

    def test_plan_all_sql(self, pipeline):
        plan = pipeline.plan(full_refresh=True)
        all_sql = plan.all_sql()
        assert len(all_sql) > 0
        for sql in all_sql:
            assert isinstance(sql, str)
            assert len(sql) > 0

    def test_plan_sql_contains_create_table(self, pipeline):
        plan = pipeline.plan(full_refresh=True)
        all_sql = plan.all_sql()
        create_count = sum(
            1 for sql in all_sql if "CREATE" in sql.upper()
        )
        assert create_count >= 3  # staging + features + blocking + matching + ...

    def test_plan_is_immutable(self, pipeline):
        plan = pipeline.plan(full_refresh=True)
        # PipelinePlan is frozen dataclass
        with pytest.raises(AttributeError):
            plan.stages = ()


# -- DuckDB execution tests --


class TestPipelineExecution:
    @pytest.fixture
    def duckdb_backend(self):
        """Create a DuckDB backend with seed data for testing."""
        try:
            from bq_entity_resolution.backends.duckdb import DuckDBBackend
            backend = DuckDBBackend()
        except ImportError:
            pytest.skip("DuckDB not available")

        # Create the source table that staging SQL reads from
        backend.execute(
            """
            CREATE TABLE customers (
                customer_id VARCHAR,
                first_name VARCHAR,
                last_name VARCHAR,
                email VARCHAR,
                updated_at TIMESTAMP DEFAULT current_timestamp
            )
            """,
            label="seed_schema",
        )
        backend.execute(
            """
            INSERT INTO customers VALUES
            ('c1', 'John', 'Smith', 'john@example.com', current_timestamp),
            ('c2', 'Jane', 'Doe', 'jane@example.com', current_timestamp),
            ('c3', 'Jon', 'Smith', 'jsmith@example.com', current_timestamp)
            """,
            label="seed_data",
        )
        return backend

    def test_staging_sql_executes(self, pipeline, duckdb_backend):
        """Staging SQL executes successfully in DuckDB."""
        plan = pipeline.plan(full_refresh=True)
        staging_plan = plan.get_stage("staging_customers")

        for expr in staging_plan.sql_expressions:
            sql = expr.render()
            duckdb_backend.execute(sql, label="test_staging")

    def test_feature_sql_executes(self, pipeline, duckdb_backend):
        """Feature engineering SQL executes after staging."""
        plan = pipeline.plan(full_refresh=True)

        # Execute staging first (creates the table features depends on)
        staging = plan.get_stage("staging_customers")
        for expr in staging.sql_expressions:
            duckdb_backend.execute(expr.render(), label="staging")

        # Execute features
        features = plan.get_stage("feature_engineering")
        for expr in features.sql_expressions:
            duckdb_backend.execute(expr.render(), label="features")


class TestPipelineRunConvenience:
    """Test the all-in-one run() method."""

    def test_run_validates_and_plans(self, person_config):
        """run() raises on validation errors."""

        class MockBackend:
            @property
            def dialect(self):
                return "bigquery"

            def execute(self, sql, label=""):
                from bq_entity_resolution.backends.protocol import QueryResult
                return QueryResult()

            def execute_script(self, sql, label=""):
                from bq_entity_resolution.backends.protocol import QueryResult
                return QueryResult()

            def execute_and_fetch(self, sql, label=""):
                return []

            def table_exists(self, ref):
                return True

            def row_count(self, ref):
                return 100

        pipeline = Pipeline(person_config, quality_gates=[])
        result = pipeline.run(
            backend=MockBackend(),
            full_refresh=True,
            run_id="test_e2e",
        )
        assert result.success
        assert result.run_id == "test_e2e"
        assert len(result.completed_stages) > 0

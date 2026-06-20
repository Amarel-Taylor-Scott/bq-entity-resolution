"""Integration tests for the BigQuery emulator backend.

These tests require a running BigQuery emulator container.
Start with: docker compose --profile test up -d bq-emulator

Tests are skipped unless BQEMU_HOST environment variable is set.
"""

import os

import pytest

# Skip all tests in this module unless BQEMU_HOST is set
pytestmark = pytest.mark.skipif(
    not os.environ.get("BQEMU_HOST"),
    reason="BQEMU_HOST not set — BigQuery emulator not available",
)


@pytest.fixture
def bqemu():
    """BQ emulator backend connected to running container."""
    from bq_entity_resolution.backends.bqemulator import BQEmulatorBackend

    host = os.environ.get("BQEMU_HOST", "localhost")
    port = int(os.environ.get("BQEMU_PORT", "9050"))
    return BQEmulatorBackend(
        project="test-project",
        dataset="test_dataset",
        host=host,
        port=port,
    )


class TestBQEmulatorBasics:
    def test_dialect(self, bqemu):
        assert bqemu.dialect == "bigquery"

    def test_execute_simple_select(self, bqemu):
        rows = bqemu.execute_and_fetch("SELECT 1 AS x, 'hello' AS y")
        assert len(rows) == 1
        assert rows[0]["x"] == 1
        assert rows[0]["y"] == "hello"

    def test_create_and_query_table(self, bqemu):
        bqemu.execute(
            "CREATE OR REPLACE TABLE `test-project.test_dataset.emu_test` "
            "(id STRING, name STRING)"
        )
        bqemu.execute(
            "INSERT INTO `test-project.test_dataset.emu_test` VALUES ('1', 'Alice')"
        )
        rows = bqemu.execute_and_fetch(
            "SELECT * FROM `test-project.test_dataset.emu_test`"
        )
        assert len(rows) >= 1

    def test_table_exists(self, bqemu):
        bqemu.execute(
            "CREATE OR REPLACE TABLE `test-project.test_dataset.exists_test` "
            "(id STRING)"
        )
        assert bqemu.table_exists("test-project.test_dataset.exists_test")
        assert not bqemu.table_exists("test-project.test_dataset.nonexistent_table")

    def test_row_count(self, bqemu):
        bqemu.execute(
            "CREATE OR REPLACE TABLE `test-project.test_dataset.count_test` "
            "(id STRING)"
        )
        bqemu.execute(
            "INSERT INTO `test-project.test_dataset.count_test` "
            "VALUES ('a'), ('b'), ('c')"
        )
        count = bqemu.row_count("test-project.test_dataset.count_test")
        assert count == 3


class TestBQEmulatorFunctions:
    def test_farm_fingerprint(self, bqemu):
        rows = bqemu.execute_and_fetch(
            "SELECT FARM_FINGERPRINT('hello') AS h1, FARM_FINGERPRINT('hello') AS h2"
        )
        assert rows[0]["h1"] == rows[0]["h2"]

    def test_soundex(self, bqemu):
        rows = bqemu.execute_and_fetch("SELECT SOUNDEX('Robert') AS s")
        assert rows[0]["s"] == "R163"

    def test_regexp_replace(self, bqemu):
        rows = bqemu.execute_and_fetch(
            r"SELECT REGEXP_REPLACE('abc123', r'[0-9]', '') AS cleaned"
        )
        assert rows[0]["cleaned"] == "abc"

    def test_qualify_clause(self, bqemu):
        bqemu.execute(
            "CREATE OR REPLACE TABLE `test-project.test_dataset.qualify_test` "
            "(id STRING, val INT64)"
        )
        bqemu.execute(
            "INSERT INTO `test-project.test_dataset.qualify_test` "
            "VALUES ('a', 1), ('a', 2), ('b', 3)"
        )
        rows = bqemu.execute_and_fetch(
            "SELECT id, val FROM `test-project.test_dataset.qualify_test` "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY val DESC) = 1"
        )
        assert len(rows) == 2


class TestBQEmulatorGeo:
    def test_st_geogpoint(self, bqemu):
        rows = bqemu.execute_and_fetch(
            "SELECT ST_GEOGPOINT(-122.4194, 37.7749) AS pt"
        )
        assert rows[0]["pt"] is not None

    def test_st_distance(self, bqemu):
        rows = bqemu.execute_and_fetch(
            "SELECT ST_DISTANCE("
            "  ST_GEOGPOINT(-122.4194, 37.7749),"
            "  ST_GEOGPOINT(-73.9857, 40.7484)"
            ") AS dist"
        )
        # SF to NYC is roughly 4,000,000 meters
        assert rows[0]["dist"] > 3_000_000
        assert rows[0]["dist"] < 5_000_000

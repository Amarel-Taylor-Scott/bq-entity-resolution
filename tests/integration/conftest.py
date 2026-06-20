"""Integration test fixtures using DuckDB as local backend."""

import pytest

from bq_entity_resolution.backends.duckdb import DuckDBBackend


@pytest.fixture
def backend():
    """Fresh in-memory DuckDB backend with test data."""
    db = DuckDBBackend(":memory:")

    # Create a featured table with sample entity resolution data
    db.execute("""
        CREATE TABLE featured (
            entity_uid VARCHAR NOT NULL,
            source_name VARCHAR NOT NULL,
            source_updated_at TIMESTAMP,
            pipeline_loaded_at TIMESTAMP,
            first_name VARCHAR,
            last_name VARCHAR,
            dob VARCHAR,
            email VARCHAR,
            first_name_clean VARCHAR,
            last_name_clean VARCHAR,
            name_soundex VARCHAR,
            bk_name_dob VARCHAR
        )
    """)

    # Insert sample records with known matches
    db.execute("""
        INSERT INTO featured VALUES
        ('e1', 'src_a', '2024-01-01', '2024-01-01',
         'John', 'Smith', '1990-01-15', 'john@example.com',
         'JOHN', 'SMITH', 'S530', 'JOHN_SMITH_19900115'),
        ('e2', 'src_a', '2024-01-01', '2024-01-01',
         'Jon', 'Smith', '1990-01-15', 'jon.smith@example.com',
         'JON', 'SMITH', 'S530', 'JON_SMITH_19900115'),
        ('e3', 'src_a', '2024-01-01', '2024-01-01',
         'Jane', 'Doe', '1985-06-20', 'jane.doe@example.com',
         'JANE', 'DOE', 'D000', 'JANE_DOE_19850620'),
        ('e4', 'src_b', '2024-01-01', '2024-01-01',
         'John', 'Smith', '1990-01-15', 'jsmith@work.com',
         'JOHN', 'SMITH', 'S530', 'JOHN_SMITH_19900115'),
        ('e5', 'src_b', '2024-01-01', '2024-01-01',
         'Alice', 'Johnson', '1992-03-10', 'alice@example.com',
         'ALICE', 'JOHNSON', 'J525', 'ALICE_JOHNSON_19920310')
    """)

    return db

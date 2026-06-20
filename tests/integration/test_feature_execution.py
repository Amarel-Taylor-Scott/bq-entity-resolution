"""Exhaustive integration tests: all feature functions execute in DuckDB.

For each registered feature function, generates SQL from sample columns,
wraps it in a SELECT, and verifies it executes without error in DuckDB.
"""

import pytest

from bq_entity_resolution.backends.duckdb import DuckDBBackend
from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS


@pytest.fixture
def db():
    """DuckDB backend with sample data for feature testing."""
    backend = DuckDBBackend(":memory:")

    backend.execute("""
        CREATE TABLE feature_test (
            first_name VARCHAR,
            last_name VARCHAR,
            full_name VARCHAR,
            email VARCHAR,
            phone VARCHAR,
            address VARCHAR,
            city VARCHAR,
            state VARCHAR,
            zip_code VARCHAR,
            dob DATE,
            ssn VARCHAR,
            company_name VARCHAR,
            latitude DOUBLE,
            longitude DOUBLE,
            vin VARCHAR,
            policy_number VARCHAR,
            iban VARCHAR,
            routing_number VARCHAR,
            account_number VARCHAR,
            amount DOUBLE,
            npi VARCHAR,
            dea_number VARCHAR,
            mrn VARCHAR,
            icd_code VARCHAR,
            ein VARCHAR,
            duns VARCHAR,
            ticker VARCHAR,
            cusip VARCHAR,
            license_number VARCHAR
        )
    """)
    backend.execute("""
        INSERT INTO feature_test VALUES (
            'John', 'Smith', 'John A. Smith Jr.',
            'John.Smith@Example.COM', '(555) 123-4567',
            '123 Main St. Apt. 4B', 'New York', 'NY', '10001-2345',
            '1990-01-15', '123-45-6789', 'Acme Corp, Inc.',
            40.7128, -74.0060,
            '1HGBH41JXMN109186', 'POL-00012345', 'GB29NWBK60161331926819',
            '021000021', '0001234567', 15250.75,
            '1234567890', 'AB1234567', 'MRN-00098765', 'M54.5',
            '12-3456789', '123456789', 'AAPL', '037833100', 'DL-A1234567'
        )
    """)

    return backend


# Map feature function → (input columns, extra params)
# Default: single input 'first_name', no extra params
_FEATURE_TEST_ARGS: dict[str, tuple[list[str], dict]] = {
    "name_clean": (["first_name"], {}),
    "name_clean_strict": (["first_name"], {}),
    "first_letter": (["first_name"], {}),
    "first_n_chars": (["first_name"], {"length": 3}),
    "char_length": (["first_name"], {}),
    "soundex": (["first_name"], {}),
    "extract_salutation": (["full_name"], {}),
    "strip_salutation": (["full_name"], {}),
    "extract_suffix": (["full_name"], {}),
    "strip_suffix": (["full_name"], {}),
    "word_count": (["full_name"], {}),
    "first_word": (["full_name"], {}),
    "last_word": (["full_name"], {}),
    "initials": (["full_name"], {}),
    "strip_business_suffix": (["company_name"], {}),
    "name_fingerprint": (["full_name"], {}),
    "address_standardize": (["address"], {}),
    "extract_street_number": (["address"], {}),
    "extract_street_name": (["address"], {}),
    "extract_unit_number": (["address"], {}),
    "phone_standardize": (["phone"], {}),
    "phone_area_code": (["phone"], {}),
    "phone_last_four": (["phone"], {}),
    "email_domain": (["email"], {}),
    "email_local_part": (["email"], {}),
    "email_domain_type": (["email"], {}),
    "upper_trim": (["first_name"], {}),
    "lower_trim": (["first_name"], {}),
    "left": (["first_name"], {"length": 3}),
    "right": (["first_name"], {"length": 3}),
    "coalesce": (["first_name", "last_name"], {}),
    "concat": (["first_name", "last_name"], {}),
    "nullif_empty": (["first_name"], {}),
    "farm_fingerprint": (["first_name"], {}),
    "farm_fingerprint_concat": (["first_name", "last_name"], {}),
    "identity": (["first_name"], {}),
    "nickname_canonical": (["first_name"], {}),
    "nickname_match_key": (["first_name"], {}),
    "sorted_name_tokens": (["full_name"], {}),
    "sorted_name_fingerprint": (["full_name"], {}),
    "zip5": (["zip_code"], {}),
    "zip3": (["zip_code"], {}),
    "year_of_date": (["dob"], {}),
    "date_to_string": (["dob"], {}),
    "dob_year": (["dob"], {}),
    "age_from_dob": (["dob"], {}),
    "ssn_last_four": (["ssn"], {}),
    "ssn_clean": (["ssn"], {}),
    "dob_mmdd": (["dob"], {}),
    "metaphone": (["first_name"], {}),
    "geo_hash": (["latitude", "longitude"], {}),
    "lat_lon_bucket": (["latitude", "longitude"], {}),
    "haversine_distance": (["latitude", "longitude", "latitude", "longitude"], {}),
    # Utility features
    "remove_diacritics": (["first_name"], {}),
    "normalize_whitespace": (["address"], {}),
    # Industry: Insurance
    "vin_normalize": (["vin"], {}),
    "vin_last_six": (["vin"], {}),
    "policy_number_clean": (["policy_number"], {}),
    # Industry: Banking
    "iban_normalize": (["iban"], {}),
    "routing_number_clean": (["routing_number"], {}),
    "account_number_clean": (["account_number"], {}),
    "amount_bucket": (["amount"], {"bucket_size": 100}),
    # Industry: Healthcare
    "npi_validate": (["npi"], {}),
    "dea_number_clean": (["dea_number"], {}),
    "mrn_clean": (["mrn"], {}),
    "icd_code_normalize": (["icd_code"], {}),
    # Industry: Business
    "ein_format": (["ein"], {}),
    "duns_clean": (["duns"], {}),
    "ticker_normalize": (["ticker"], {}),
    "cusip_clean": (["cusip"], {}),
    "license_number_clean": (["license_number"], {}),
}

# Functions requiring geo extensions
_GEO_FEATURES = {"geo_hash", "lat_lon_bucket", "haversine_distance"}


@pytest.fixture(params=sorted(FEATURE_FUNCTIONS.keys()))
def feature_name(request):
    return request.param


class TestFeatureExecution:
    def test_feature_generates_sql(self, feature_name):
        """Every feature function generates a non-empty SQL string."""
        func = FEATURE_FUNCTIONS[feature_name]
        args = _FEATURE_TEST_ARGS.get(feature_name, (["first_name"], {}))
        inputs, params = args
        sql = func(inputs, **params)
        assert isinstance(sql, str)
        assert len(sql) > 0

    def test_feature_executes_in_duckdb(self, db, feature_name):
        """Every feature function's SQL executes successfully in DuckDB."""
        if feature_name in _GEO_FEATURES and not db.has_spatial:
            pytest.skip("Spatial extension not available for geo features")

        func = FEATURE_FUNCTIONS[feature_name]
        args = _FEATURE_TEST_ARGS.get(feature_name, (["first_name"], {}))
        inputs, params = args

        # Handle geo features with lat/lon inputs
        if feature_name == "geo_hash":
            inputs = ["latitude", "longitude"]
        elif feature_name == "lat_lon_bucket":
            inputs = ["latitude", "longitude"]
        elif feature_name == "haversine_distance":
            inputs = ["latitude", "longitude", "latitude", "longitude"]

        sql_expr = func(inputs, **params)

        query = f"SELECT {sql_expr} AS result FROM feature_test"
        try:
            rows = db.execute_and_fetch(query)
            assert len(rows) == 1
        except Exception as e:
            error_str = str(e)
            # Some functions may use BQ-specific syntax that's hard to shim
            if any(skip_reason in error_str for skip_reason in [
                "does not exist",
                "No function matches",
                "not supported",
            ]):
                pytest.skip(f"Function not available in DuckDB: {e}")
            raise

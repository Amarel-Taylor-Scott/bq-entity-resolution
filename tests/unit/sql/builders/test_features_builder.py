"""Tests for the features SQL builder."""

from bq_entity_resolution.sql.builders.features import (
    CustomJoin,
    EnrichmentJoin,
    FeatureExpr,
    FeatureParams,
    TFColumn,
    build_features_sql,
    build_term_frequencies_sql,
)


def test_basic_features():
    """Feature engineering generates multi-pass CTE."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged_crm"],
        source_columns=["first_name", "last_name"],
        feature_expressions=[
            FeatureExpr("name_clean", "TRIM(UPPER(first_name))"),
            FeatureExpr("name_soundex", "SOUNDEX(last_name)"),
        ],
        blocking_keys=[
            FeatureExpr("bk_soundex", "SOUNDEX(last_name)"),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "WITH base AS" in sql
    assert "features_pass1 AS" in sql
    assert "featured AS" in sql
    assert "TRIM(UPPER(first_name)) AS name_clean" in sql
    assert "SOUNDEX(last_name) AS name_soundex" in sql
    assert "SOUNDEX(last_name) AS bk_soundex" in sql


def test_features_multiple_sources():
    """Multiple source tables are UNIONed."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged_a", "proj.ds.staged_b"],
        source_columns=["name"],
        feature_expressions=[FeatureExpr("upper_name", "UPPER(name)")],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "UNION ALL" in sql
    assert "staged_a" in sql
    assert "staged_b" in sql


def test_features_dependent_features():
    """Dependent features appear in pass 2."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["first_name"],
        feature_expressions=[
            FeatureExpr("name_clean", "TRIM(UPPER(first_name))"),
        ],
        dependent_features=[
            FeatureExpr("name_soundex", "SOUNDEX(name_clean)"),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "features_pass1 AS" in sql
    assert "featured AS" in sql
    assert "SOUNDEX(name_clean) AS name_soundex" in sql


def test_features_composite_keys():
    """Composite keys are generated in pass 3."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["first_name", "last_name", "dob"],
        feature_expressions=[],
        composite_keys=[
            FeatureExpr(
                "bk_name_dob",
                "CONCAT(UPPER(first_name), '_', UPPER(last_name), '_', CAST(dob AS STRING))",
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "bk_name_dob" in sql
    assert "CONCAT(" in sql


def test_features_custom_joins():
    """Custom joins are included in pass 1."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["name"],
        feature_expressions=[FeatureExpr("upper_name", "UPPER(name)")],
        custom_joins=[
            CustomJoin(
                table="proj.ref.lookup",
                alias="lkp",
                on="b.type_id = lkp.id",
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "LEFT JOIN" in sql
    assert "proj.ref.lookup" in sql
    assert "lkp" in sql


def test_term_frequencies_single_column():
    """Term frequency for a single column."""
    expr = build_term_frequencies_sql(
        target_table="proj.ds.tf_stats",
        source_table="proj.ds.featured",
        tf_columns=[TFColumn("last_name")],
    )
    sql = expr.render()

    assert "CREATE OR REPLACE TABLE" in sql
    assert "'last_name' AS term_frequency_column" in sql
    assert "term_frequency_ratio" in sql
    assert "COUNT(*)" in sql


def test_term_frequencies_multiple_columns():
    """Term frequency for multiple columns uses UNION ALL."""
    expr = build_term_frequencies_sql(
        target_table="proj.ds.tf_stats",
        source_table="proj.ds.featured",
        tf_columns=[TFColumn("last_name"), TFColumn("city")],
    )
    sql = expr.render()

    assert "UNION ALL" in sql
    assert "'last_name' AS term_frequency_column" in sql
    assert "'city' AS term_frequency_column" in sql


def test_features_returns_sql_expression():
    """Builder returns SQLExpression."""
    params = FeatureParams(
        target_table="p.d.target",
        source_tables=["p.d.source"],
        source_columns=[],
        feature_expressions=[FeatureExpr("x", "1")],
    )
    expr = build_features_sql(params)
    assert expr.is_raw is True
    assert isinstance(expr.render(), str)


# ---------------------------------------------------------------------------
# Enrichment join tests
# ---------------------------------------------------------------------------


def test_enrichment_join_basic():
    """Enrichment join inserts an 'enriched' CTE with LEFT JOIN."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["address_line_1", "city", "state"],
        feature_expressions=[FeatureExpr("addr_upper", "UPPER(address_line_1)")],
        enrichment_joins=[
            EnrichmentJoin(
                table="proj.census.address_lookup",
                alias="census",
                join_key_expression=(
                    "FARM_FINGERPRINT(CONCAT("
                    "COALESCE(CAST(address_line_1 AS STRING), ''), '||', "
                    "COALESCE(CAST(city AS STRING), ''), '||', "
                    "COALESCE(CAST(state AS STRING), '')))"
                ),
                lookup_key="address_fp",
                columns=["matched_address", "latitude", "longitude"],
                column_prefix="census_",
                match_flag="has_census_match",
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    # Enriched CTE should exist
    assert "enriched AS" in sql

    # Columns should have prefix
    assert "census.matched_address AS census_matched_address" in sql
    assert "census.latitude AS census_latitude" in sql
    assert "census.longitude AS census_longitude" in sql

    # Match flag should be generated
    assert "has_census_match" in sql
    assert "CASE WHEN census.matched_address IS NOT NULL THEN 1 ELSE 0 END" in sql

    # LEFT JOIN on the computed key
    assert "LEFT JOIN `proj.census.address_lookup` AS census" in sql
    assert "FARM_FINGERPRINT(CONCAT(" in sql
    assert "= census.address_fp" in sql

    # Pass 1 should reference enriched, not base
    assert "FROM enriched e" in sql


def test_enrichment_join_no_prefix():
    """Enrichment join without column_prefix uses raw column names."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["name"],
        feature_expressions=[FeatureExpr("upper_name", "UPPER(name)")],
        enrichment_joins=[
            EnrichmentJoin(
                table="proj.ref.lookup",
                alias="ref",
                join_key_expression="FARM_FINGERPRINT(name)",
                lookup_key="name_fp",
                columns=["canonical_name", "category"],
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "ref.canonical_name AS canonical_name" in sql
    assert "ref.category AS category" in sql
    assert "enriched AS" in sql


def test_enrichment_join_inner():
    """INNER enrichment join uses INNER JOIN."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["ssn"],
        feature_expressions=[FeatureExpr("ssn_clean", "REGEXP_REPLACE(ssn, r'[^0-9]', '')")],
        enrichment_joins=[
            EnrichmentJoin(
                table="proj.ref.verified_ssn",
                alias="verified",
                join_key_expression="FARM_FINGERPRINT(ssn)",
                lookup_key="ssn_fp",
                columns=["verified_name"],
                join_type="INNER",
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "INNER JOIN `proj.ref.verified_ssn` AS verified" in sql


def test_no_enrichment_joins_no_enriched_cte():
    """Without enrichment joins, no 'enriched' CTE is generated."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["name"],
        feature_expressions=[FeatureExpr("upper_name", "UPPER(name)")],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "enriched AS" not in sql
    assert "FROM base b" in sql


def test_enrichment_join_with_features_and_blocking():
    """Enrichment columns are available for feature computation and blocking."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["address_line_1"],
        feature_expressions=[
            FeatureExpr("addr_fp", "FARM_FINGERPRINT(census_matched_address)"),
        ],
        blocking_keys=[
            FeatureExpr("bk_census_addr", "FARM_FINGERPRINT(census_matched_address)"),
        ],
        enrichment_joins=[
            EnrichmentJoin(
                table="proj.census.lookup",
                alias="census",
                join_key_expression="FARM_FINGERPRINT(address_line_1)",
                lookup_key="address_fp",
                columns=["matched_address"],
                column_prefix="census_",
                match_flag="has_census_match",
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    # Enrichment columns flow through to features and blocking
    assert "census_matched_address" in sql
    assert "FARM_FINGERPRINT(census_matched_address) AS addr_fp" in sql
    assert "FARM_FINGERPRINT(census_matched_address) AS bk_census_addr" in sql


def test_multiple_enrichment_joins():
    """Multiple enrichment joins produce multiple LEFT JOINs in the enriched CTE."""
    params = FeatureParams(
        target_table="proj.ds.featured",
        source_tables=["proj.ds.staged"],
        source_columns=["address_line_1", "company_name"],
        feature_expressions=[FeatureExpr("x", "1")],
        enrichment_joins=[
            EnrichmentJoin(
                table="proj.census.lookup",
                alias="census",
                join_key_expression="FARM_FINGERPRINT(address_line_1)",
                lookup_key="address_fp",
                columns=["matched_address"],
                column_prefix="census_",
            ),
            EnrichmentJoin(
                table="proj.ref.companies",
                alias="company_ref",
                join_key_expression="FARM_FINGERPRINT(UPPER(company_name))",
                lookup_key="company_fp",
                columns=["sic_code", "industry"],
                column_prefix="ref_",
            ),
        ],
    )
    expr = build_features_sql(params)
    sql = expr.render()

    assert "LEFT JOIN `proj.census.lookup` AS census" in sql
    assert "LEFT JOIN `proj.ref.companies` AS company_ref" in sql
    assert "census_matched_address" in sql
    assert "ref_sic_code" in sql
    assert "ref_industry" in sql
